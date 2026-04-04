# Bedroom Sunrise Dimmer Automation

## Overview

A virtual switch (`input_boolean`) in Home Assistant exposed to HomeKit triggers a two-phase brightness ramp on the bedroom dimmer. All iOS users in the home can activate it from Apple Home or an iOS Shortcut.

- **Phase 1:** 1% → 20%, stepping +1% every 30 seconds (19 steps, ~9.5 min)
- **Phase 2:** 25% → 100%, stepping +5% every 60 seconds (16 steps, ~16 min)
- **Total runtime:** ~25 min 30 sec
- Cancels immediately if the dimmer is turned off or brightness is manually adjusted during the ramp
- Resets the virtual switch to off on completion or cancellation

---

## Architecture

The automation uses a **HA script** for the ramp sequence, triggered by separate automations. Scripts (unlike automations) can be stopped mid-execution with `script.turn_off` without disabling future runs — essential for the external cancellation requirement.

### Entities

| Entity | Type | Purpose |
|---|---|---|
| `input_boolean.bedroom_sunrise_start` | Helper | Virtual switch; HomeKit-exposed trigger |
| `input_number.bedroom_sunrise_expected_brightness` | Helper | Tracks the last brightness set by the script (0-1000 scale) for cancellation detection |
| `script.bedroom_sunrise` | Script | Executes the two-phase ramp |
| `switch.bedroom_dimmer_fan_light` | Tuya switch | Physical on/off for the bedroom dimmer |
| `number.bedroom_dimmer_fan_bright_value` | Tuya number | Raw brightness value (0-1000 scale) |
| `light.bedroom_dimmer` | Template light | HA abstraction; `set_level` calls `script.bedroom_light_level` which sets the Tuya number |

### Hardware Notes

The Tuya dimmer uses a 0-1000 brightness scale. The hardware minimum is `10.0` (float) — sending integer `10` causes the Tuya integration to bump it to `20`. The `number.bedroom_dimmer_fan_bright_value` entity reports actual device state; `brightness_pct` values in the script map approximately as `brightness_pct * 10`.

---

## File Changes

### `configuration.yaml`

Added two helpers:

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

> Requires a full HA restart to take effect (helpers in `configuration.yaml` cannot be hot-reloaded).

### `automations.yaml`

Three automations:

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
  description: "Phase 1: minimum to 20% at 1%/30s. Phase 2: 25% to 100% at 5%/60s."
  mode: single
  sequence:
    # Pre-set brightness BEFORE turning on the switch to prevent startup flicker.
    # The template light's turn_on only calls switch.turn_on (no brightness).
    # Without this, the switch comes on at its previous brightness then jumps.
    - service: number.set_value
      target:
        entity_id: number.bedroom_dimmer_fan_bright_value
      data:
        value: 10.0   # Float required — integer 10 gets bumped to 20 by Tuya
    - service: input_number.set_value
      target:
        entity_id: input_number.bedroom_sunrise_expected_brightness
      data:
        value: 10.0
    - service: switch.turn_on
      target:
        entity_id: switch.bedroom_dimmer_fan_light

    # Phase 1: 2% to 20%, 1% every 30 seconds (19 steps)
    - repeat:
        count: 19
        sequence:
          - delay:
              seconds: 30
          - service: light.turn_on
            target:
              entity_id: light.bedroom_dimmer
            data:
              brightness_pct: "{{ 2 + repeat.index - 1 }}"
          - service: input_number.set_value
            target:
              entity_id: input_number.bedroom_sunrise_expected_brightness
            data:
              value: "{{ (2 + repeat.index - 1) * 10 }}"

    # Phase 2: 25% to 100%, 5% every 60 seconds (16 steps)
    - repeat:
        count: 16
        sequence:
          - delay:
              seconds: 60
          - service: light.turn_on
            target:
              entity_id: light.bedroom_dimmer
            data:
              brightness_pct: "{{ 25 + (repeat.index - 1) * 5 }}"
          - service: input_number.set_value
            target:
              entity_id: input_number.bedroom_sunrise_expected_brightness
            data:
              value: "{{ (25 + (repeat.index - 1) * 5) * 10 }}"

    - service: input_boolean.turn_off
      target:
        entity_id: input_boolean.bedroom_sunrise_start
```

> **Why `delay` instead of `wait_for_trigger`:** The template light's `set_level` triggers an async device state update that propagates back through the template light after HA moves on. This caused `wait_for_trigger` to fire immediately on the script's own changes regardless of settling delay. Plain `delay` eliminates this race condition entirely.

---

## HomeKit Exposure

`input_boolean.bedroom_sunrise_start` was added to the HomeKit Bridge `include_entities` filter via `.storage/core.config_entries` (entry ID `01KHYQ16V48Q9FAN2P70J10A6A`). A full HA restart applied the change.

The switch appears in Apple Home as **"Bedroom Sunrise Start"** and is visible to all household members.

---

## iOS Shortcut

1. Open **Shortcuts** -> New Shortcut
2. Add action: **Control My Home**
3. Select **Set "Bedroom Sunrise Start"** -> **On**
4. Save (e.g., "Start Bedroom Sunrise")

Optionally add to Lock Screen, Home Screen, or trigger via Siri.

---

## Ramp Time Table

| Phase | Range | Step | Delay | Steps | Time |
|---|---|---|---|---|---|
| Phase 1 | ~1% to 20% | +1% | 30 sec | 19 | 9 min 30 sec |
| Phase 2 | 25% to 100% | +5% | 60 sec | 16 | 16 min |
| **Total** | | | | **35** | **25 min 30 sec** |
