# Bedroom Sunrise Dimmer Automation

## Overview

A virtual switch (`input_boolean`) in Home Assistant exposed to HomeKit triggers a three-phase brightness ramp on the bedroom dimmer. All iOS users in the home can activate it from Apple Home or an iOS Shortcut.

- **Phase 1:** 2% → 10%, direct raw values, +1% every 2.5 min (9 steps, 22 min 30 sec)
- **Phase 2:** 11% → 30%, +1% every 60 sec (20 steps, 20 min)
- **Phase 3:** 35% → 100%, +5% every 75 sec (14 steps, 17 min 30 sec)
- **Total runtime:** 60 min
- Cancels immediately if the dimmer is turned off or brightness is manually adjusted during the ramp
- Resets the virtual switch to off on completion or cancellation

### Design rationale

LED dimmers have a roughly logarithmic lumen response — each +1% step at low brightness produces a disproportionately large visible change compared to the same step at high brightness. Phase 1 allocates 22.5 of the 60 minutes to just the 2%–10% range, making the initial light appear to breathe on almost imperceptibly.

---

## Architecture

The automation uses a **HA script** for the ramp sequence, triggered by separate automations. Scripts (unlike automations) can be stopped mid-execution with `script.turn_off` without disabling future runs — essential for the external cancellation requirement.

### Entities

| Entity | Type | Purpose |
|---|---|---|
| `input_boolean.bedroom_sunrise_start` | Helper | Virtual switch; HomeKit-exposed trigger |
| `input_number.bedroom_sunrise_expected_brightness` | Helper | Tracks the last brightness set by the script (0–1000 scale) for cancellation detection |
| `script.bedroom_sunrise` | Script | Executes the three-phase ramp |
| `switch.bedroom_dimmer_fan_light` | Tuya switch | Physical on/off for the bedroom dimmer |
| `number.bedroom_dimmer_fan_bright_value` | Tuya number | Raw brightness value (0–1000 scale) |
| `light.bedroom_dimmer` | Template light | HA abstraction; `set_level` calls `script.bedroom_light_level` which sets the Tuya number |

### Hardware Notes

The Tuya dimmer uses a 0–1000 brightness scale. The **firmware startup minimum is raw 20** (2%) — the device always initialises here on power-on regardless of stored brightness, provided the stored target is below the minimum (see startup sequence below).

The standard HA brightness conversion (`brightness_pct * 255/100`, then `brightness/255 * 1000`) produces non-integer floats (e.g. `(3/255)*1000 = 11.76` for 1%). The Tuya integration passes true floats through to the device cleanly. Integer-like values near the hardware minimum (e.g. `10.0`, `12.0`) are treated as boundary sentinels and bumped up to 20 by the integration.

---

## Startup Sequence

Getting the light to start at a reliably dim level requires working around two Tuya async behaviours:

1. **Stored brightness restore** — if the device was last used at a high brightness (e.g. 500 = 50%), it restores that value on the next power-on, causing a bright flash.
2. **Delayed state reports** — any Tuya command sent while the switch is off queues a state report that arrives ~3–5s after the switch turns on. This overwrites subsequent brightness-set commands sent in the same window.

The solution is a **pre-set-only** startup (no post-set):

1. `number.set_value: 11.76` while switch is off — sends a sub-minimum float to the device's WiFi MCU, which stores it as the target brightness. On next power-on the device clamps to its firmware minimum (raw 20), preventing a restore of any previously stored high value.
2. `input_number.set_value: 20.0` — arms the cancellation guard at the startup brightness.
3. `switch.turn_on` — device comes on at raw 20 (2%) regardless of previous stored brightness.

No post-set is used because the delayed state report from step 1 would overwrite it. Raw 20 (2%) is the reliable, stable starting point.

Phase 1 Step 1 (index 1) also sets raw 20 — a 2.5-minute timing hold at startup brightness while the Tuya state settles before the ramp increments begin.

---

## File Changes

### `configuration.yaml`

Added two helpers (requires full HA restart):

```yaml
input_boolean:
  bedroom_sunrise_start:
    name: Bedroom Sunrise Start
    icon: mdi:weather-sunny-alert

input_number:
  bedroom_sunrise_expected_brightness:
    name: Bedroom Sunrise Expected Brightness
    min: 0
    max: 1000
    step: 1
```

### `automations.yaml`

Three automations (unchanged from original):

**1. Start** — triggers the script when the switch is turned on:

```yaml
- alias: "Bedroom Sunrise - Start"
  trigger:
    - platform: state
      entity_id: input_boolean.bedroom_sunrise_start
      to: "on"
  action:
    - service: script.turn_on
      target:
        entity_id: script.bedroom_sunrise
  mode: single
```

**2. Cancel on Light Off** — stops the script if the dimmer switch is turned off externally:

```yaml
- alias: "Bedroom Sunrise - Cancel on Light Off"
  trigger:
    - platform: state
      entity_id: switch.bedroom_dimmer_fan_light
      to: "off"
  condition:
    - condition: state
      entity_id: script.bedroom_sunrise
      state: "on"
  action:
    - service: script.turn_off
      target:
        entity_id: script.bedroom_sunrise
    - service: input_boolean.turn_off
      target:
        entity_id: input_boolean.bedroom_sunrise_start
```

**3. Cancel on Brightness Adjustment** — stops the script if brightness deviates more than 50 units (~5%) from the expected ramp value:

```yaml
- alias: "Bedroom Sunrise - Cancel on Brightness Adjustment"
  trigger:
    - platform: state
      entity_id: number.bedroom_dimmer_fan_bright_value
  condition:
    - condition: state
      entity_id: script.bedroom_sunrise
      state: "on"
    - condition: template
      value_template: >
        {{ (trigger.to_state.state | float - states('input_number.bedroom_sunrise_expected_brightness') | float) | abs > 50 }}
  action:
    - service: script.turn_off
      target:
        entity_id: script.bedroom_sunrise
    - service: input_boolean.turn_off
      target:
        entity_id: input_boolean.bedroom_sunrise_start
```

### `scripts.yaml`

```yaml
bedroom_sunrise:
  alias: "Bedroom Sunrise Dimmer"
  description: "Phase 1: 2%→10% direct raw (+1%/150s). Phase 2: 11%→30% template (+1%/60s). Phase 3: 35%→100% template (+5%/75s). Total 60 min."
  mode: single
  sequence:
    # Pre-set brightness to 11.76 (a non-integer float) while the switch is off.
    # This causes the device to store 11.76 as its target, so it starts at its
    # firmware minimum (raw 20 = 2%) on the next turn-on rather than restoring a
    # previously stored high value. Prevents bright flash on startup.
    # Note: any Tuya command sent while the switch is off queues a delayed state
    # report that interferes with post-set commands, so no post-set is used here.
    - service: number.set_value
      target:
        entity_id: number.bedroom_dimmer_fan_bright_value
      data:
        value: 11.76
    # Track expected brightness as 20.0 — the firmware minimum the device reliably
    # starts at after the 11.76 pre-set.
    - service: input_number.set_value
      target:
        entity_id: input_number.bedroom_sunrise_expected_brightness
      data:
        value: 20.0
    # Turn on the switch. Device starts at firmware minimum (raw 20 = 2%).
    - service: switch.turn_on
      target:
        entity_id: switch.bedroom_dimmer_fan_light

    # Phase 1: 2%→10%, direct number.set_value, +1% (raw +10) every 150 seconds (22m30s)
    # Step 1 (index 1) sets raw 20 — a timing hold at startup brightness while the
    # device Tuya state settles. Steps 2-9 increment from 30 to 100 (3%–10%).
    # Direct number.set_value bypasses template light 0-255 rounding at low brightness.
    - repeat:
        count: 9
        sequence:
          - delay:
              seconds: 150
          - service: number.set_value
            target:
              entity_id: number.bedroom_dimmer_fan_bright_value
            data:
              value: "{{ 20 + (repeat.index - 1) * 10 }}"
          - service: input_number.set_value
            target:
              entity_id: input_number.bedroom_sunrise_expected_brightness
            data:
              value: "{{ 20 + (repeat.index - 1) * 10 }}"

    # Phase 2: 11%→30%, via template light, +1% every 60 seconds (20 min)
    - repeat:
        count: 20
        sequence:
          - delay:
              seconds: 60
          - service: light.turn_on
            target:
              entity_id: light.bedroom_dimmer
            data:
              brightness_pct: "{{ 11 + repeat.index - 1 }}"
          - service: input_number.set_value
            target:
              entity_id: input_number.bedroom_sunrise_expected_brightness
            data:
              value: "{{ (11 + repeat.index - 1) * 10 }}"

    # Phase 3: 35%→100%, via template light, +5% every 75 seconds (17m30s)
    - repeat:
        count: 14
        sequence:
          - delay:
              seconds: 75
          - service: light.turn_on
            target:
              entity_id: light.bedroom_dimmer
            data:
              brightness_pct: "{{ 35 + (repeat.index - 1) * 5 }}"
          - service: input_number.set_value
            target:
              entity_id: input_number.bedroom_sunrise_expected_brightness
            data:
              value: "{{ (35 + (repeat.index - 1) * 5) * 10 }}"

    - service: input_boolean.turn_off
      target:
        entity_id: input_boolean.bedroom_sunrise_start
```

> **Why `delay` instead of `wait_for_trigger`:** The template light's `set_level` triggers an async device state update that propagates back through the template light after HA moves on. This caused `wait_for_trigger` to fire immediately on the script's own changes. Plain `delay` eliminates this race condition entirely.

---

## HomeKit Exposure

`input_boolean.bedroom_sunrise_start` was added to the HomeKit Bridge `include_entities` filter via `.storage/core.config_entries` (entry ID `01KHYQ16V48Q9FAN2P70J10A6A`). A full HA restart applied the change.

The switch appears in Apple Home as **"Bedroom Sunrise Start"** and is visible to all household members.

---

## iOS Shortcut

1. Open **Shortcuts** → New Shortcut
2. Add action: **Control My Home**
3. Select **Set "Bedroom Sunrise Start"** → **On**
4. Save (e.g., "Start Bedroom Sunrise")

Optionally add to Lock Screen, Home Screen, or trigger via Siri.

---

## Ramp Time Table

| Phase | Range | Step | Method | Delay | Steps | Time |
|---|---|---|---|---|---|---|
| Phase 1 | 2% → 10% | +1% (raw +10) | Direct `number.set_value` | 150 s | 9 | 22 min 30 sec |
| Phase 2 | 11% → 30% | +1% | `light.turn_on brightness_pct` | 60 s | 20 | 20 min |
| Phase 3 | 35% → 100% | +5% | `light.turn_on brightness_pct` | 75 s | 14 | 17 min 30 sec |
| **Total** | | | | | **43** | **60 min** |

*Phase 1 Step 1 (index 1) sets raw 20, matching the startup brightness — a 2.5-minute timing hold before incrementing.*
