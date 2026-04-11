# Cat Litter Anti-Pinch Alert — Implementation Plan

**Feature:** Home Assistant sensor and HomeKit-native alert for `relay_status = "2"`
("Bottom infrared anti-pinch triggered")
**Status:** Planning
**Reference:** `docs/Tuya-Research.md` § 13, § 14

---

## 1. Goal

When the cat litter box bottom infrared sensor detects an obstruction, HA should:

1. Expose a `binary_sensor` (device_class: `problem`) reflecting the error state for HA dashboards and automations
2. Expose a `binary_sensor` (device_class: `door`) that opens on error, surfaced to HomeKit as a Contact Sensor
3. Deliver native iOS push notifications via the Home app when the contact sensor opens and closes
4. (Optional) Mirror notifications through HA notify automations as a fallback

Notifications are delivered **primarily through HomeKit** rather than HA's notify service. This leverages iOS Home app's native "notify when door opens/closes" feature and delivers alerts even when HA cloud connectivity is unavailable.

---

## 2. Source Entity

`select.cat_litter_relay_status` (DP 105, extended — MQTT-only)

| State | Meaning |
|-------|---------|
| `"1"` | Normal — infrared sensor clear |
| `"2"` | **Anti-pinch triggered** — obstruction detected |

This entity is already tracked in the HA recorder and transitions reliably.
Confirmed source of the Tuya app "Bottom infrared anti-pinch triggered!" log entry (§ 13).

**Note on door anti-pinch (§ 14):** The door anti-pinch event also routes through `relay_status` but self-clears in sub-second time — too fast for HA to capture. This plan covers only the bottom anti-pinch (`"2"`), which persists until manually cleared.

---

## 3. Components

### 3a. Problem Sensor (HA dashboards)

A `binary_sensor` with `device_class: problem` for clean representation in HA dashboards,
logbook ("Problem detected / Problem cleared"), and future automations.

Add under the existing `template:` block in `configuration.yaml`:

```yaml
# Under template: → binary_sensor:
- binary_sensor:
  - name: "Cat Litter Anti-Pinch"
    unique_id: cat_litter_anti_pinch
    device_class: problem
    state: "{{ is_state('select.cat_litter_relay_status', '2') }}"
    icon: >
      {% if is_state('select.cat_litter_relay_status', '2') %}
        mdi:alert-circle
      {% else %}
        mdi:check-circle
      {% endif %}
```

### 3b. Door Sensor (HomeKit notification trigger)

A second `binary_sensor` with `device_class: door` targeting the same source.
HomeKit interprets `on` as **Open** and `off` as **Closed**.
Because `binary_sensor` is already in the HomeKit bridge's `include_domains`, this entity
will appear automatically in the Home app as a Contact Sensor — no additional bridge
configuration required.

Add alongside 3a under the same `template:` → `binary_sensor:` block:

```yaml
  - name: "Cat Litter Box Drawer Sensor"
    unique_id: cat_litter_anti_pinch_door
    device_class: door
    state: "{{ is_state('select.cat_litter_relay_status', '2') }}"
    icon: >
      {% if is_state('select.cat_litter_relay_status', '2') %}
        mdi:door-open
      {% else %}
        mdi:door-closed
      {% endif %}
```

**HomeKit behaviour:**

> **Note:** `device_class: door` in HA maps to a HAP **Contact Sensor** (service 0x80,
> accessory category: Sensor). HomeKit's Door category is reserved for motorized door
> openers. This entity appears in the Home app's Sensors section — not as a door tile —
> and issues notifications as "Cat Litter Box Drawer Sensor is Open/Closed".

| relay_status | HA state | Contact Sensor state | Home app notification |
|---|---|---|---|
| `"2"` (anti-pinch) | `on` | Open | "Cat Litter Box Drawer Sensor is Open" |
| `"1"` (normal) | `off` | Closed | "Cat Litter Box Drawer Sensor is Closed" (if enabled) |

### 3c. HomeKit Notification Setup (Home app — user action, no code)

After the contact sensor appears in HomeKit (Sensors section):

1. Open the **Home app** on iPhone/iPad
2. Tap **···** (three dots) top right → **Home Settings**
3. Tap **Sensors**
4. Find **Cat Litter Box Drawer Sensor** and tap it
5. Enable **Activity Notifications** (open, close, or both)

This delivers a native iOS push notification via the Home app daemon — no HA cloud
dependency, no `notify.*` service required.

### 3d. HA Automations (Optional — backup / Android fallback)

Keep the trigger and clear automations from the original plan as a complementary
notification path for non-Apple devices or when richer message content is desired
(e.g., including elapsed duration in the clear notification).

**Trigger automation** (`automations.yaml`):

```yaml
- alias: "Cat Litter — Anti-Pinch Triggered"
  id: cat_litter_anti_pinch_triggered
  description: >
    Push notification when the bottom infrared anti-pinch sensor trips.
    Complements HomeKit native notifications.
  trigger:
    - platform: state
      entity_id: select.cat_litter_relay_status
      to: "2"
  action:
    - service: notify.PLACEHOLDER
      data:
        title: "⚠️ Cat Litter Box — Sensor Error"
        message: >
          Bottom infrared anti-pinch triggered at
          {{ now().strftime('%-I:%M %p') }}.
          Check for obstruction and clear manually.
  mode: single
```

**Clear automation** (`automations.yaml`):

```yaml
- alias: "Cat Litter — Anti-Pinch Cleared"
  id: cat_litter_anti_pinch_cleared
  description: >
    Push notification when the anti-pinch error clears, with elapsed duration.
  trigger:
    - platform: state
      entity_id: select.cat_litter_relay_status
      to: "1"
      from: "2"
  action:
    - service: notify.PLACEHOLDER
      data:
        title: "✅ Cat Litter Box — Error Cleared"
        message: >
          Anti-pinch sensor cleared at {{ now().strftime('%-I:%M %p') }}.
          Error was active for
          {% set secs = (as_timestamp(now()) - as_timestamp(trigger.from_state.last_changed)) | int %}
          {% if secs < 60 %}{{ secs }} seconds.
          {% elif secs < 3600 %}{{ (secs // 60) }} min {{ (secs % 60) }} sec.
          {% else %}{{ (secs // 3600) }} hr {{ ((secs % 3600) // 60) }} min.{% endif %}
  mode: single
```

`notify.PLACEHOLDER` must be confirmed before use. Check in HA → Developer Tools → Services.

---

## 4. HomeKit Bridge — No Additional Config Required

The existing HomeKit bridge (`HASS Bridge:21064`, bridge mode) already includes
`binary_sensor` in its `include_domains` list. Both new entities will be exposed to
HomeKit automatically on the next HA restart.

No changes to `configuration.yaml` HomeKit settings are needed.

---

## 5. Files to Edit

| File | Change |
|------|--------|
| `configuration.yaml` | Add **two** binary sensor blocks under existing `template:` section |
| `automations.yaml` | (Optional) Append two automations for HA notify fallback |

---

## 6. Reload / Restart Requirements

| Component | Required action |
|-----------|----------------|
| Both template binary sensors | **Full HA restart** |
| HomeKit bridge (new accessories) | **Full HA restart** — new accessories register on restart |
| Automations (if added) | `automation.reload` (no restart needed after initial restart) |

One full HA restart covers all components. HomeKit may take 30–60 seconds to surface new
accessories after restart.

---

## 7. Testing Procedure

### Pre-test checklist
- [ ] HA restarted after adding both binary sensor templates
- [ ] `binary_sensor.cat_litter_anti_pinch` visible in Developer Tools → States, state `off`
- [ ] `binary_sensor.cat_litter_anti_pinch_door` visible in Developer Tools → States, state `off`
- [ ] "Cat Litter Box Drawer Sensor" visible in Home app (Sensors section) showing "Closed"
- [ ] Activity Notifications enabled for the contact sensor via Home Settings → Sensors (§ 3c)
- [ ] (If using 3d) `notify.PLACEHOLDER` replaced with real service name

### Test 1 — Both binary sensors reflect live state
1. In Developer Tools → Services, call `select.select_option` on `select.cat_litter_relay_status` with `option: "2"`
2. Verify `binary_sensor.cat_litter_anti_pinch` → `on` ("Problem detected")
3. Verify `binary_sensor.cat_litter_anti_pinch_door` → `on` ("Open")
4. Verify Home app tile shows "Open" for Cat Litter Box Drawer Sensor
5. Call `select.select_option` with `option: "1"` — verify both sensors return to `off` / "Closed"

### Test 2 — HomeKit native notification fires
1. With Activity Notifications enabled (§ 3c), trigger error as in Test 1 step 1
2. Verify iOS push notification arrives: **"Cat Litter Box Drawer Sensor is Open"**
3. Clear the error — verify optional "Closed" notification arrives if enabled
4. Check Home app → ··· → Notification History for correct timestamps

### Test 3 — HA automations fire (if 3d implemented)
1. Trigger error as in Test 1
2. Verify HA notify push notification arrives with correct title and time
3. Leave active ≥ 2 min, then clear
4. Verify clear notification shows elapsed time

### Test 4 — Physical device trip (real sensor)
1. With litter box powered and idle, physically interrupt the bottom infrared beam
2. Observe `select.cat_litter_relay_status` → `"2"` in HA within seconds
3. Confirm both binary sensors change state
4. Confirm HomeKit notification arrives on device
5. Remove obstruction — confirm `relay_status` → `"1"` and both sensors clear

### Test 5 — HA restart with error active
1. Trigger error
2. Restart HA
3. Confirm both binary sensors correctly show `on` after restart (state restored)
4. Confirm no spurious trigger notifications on restart

---

## 8. Caveats and Known Limitations

1. **Repeat triggers while active are silent.** HA state deduplication prevents re-firing
   automations if `relay_status` is already `"2"`. HomeKit similarly will not re-notify
   if the contact sensor is already "Open".

2. **HA offline = missed HA notify alerts.** HomeKit notifications are delivered by the iOS
   Home daemon independently of HA cloud; as long as HA is reachable on LAN, HomeKit
   notifications will work.

3. **Duration in clear notification depends on `trigger.from_state.last_changed`.** If HA
   restarts while the error is active, `last_changed` resets to restart time, making the
   elapsed time in the clear notification shorter than actual.

4. **HomeKit accessory re-pairing on bridge reset.** If the HomeKit bridge is reset or
   re-paired, notification preferences for the contact sensor must be re-enabled in the
   Home app (§ 3c).

5. **Door anti-pinch not covered.** The door anti-pinch (§ 14) self-clears in
   sub-second time and cannot be captured by HA state change triggers. This plan covers
   the bottom anti-pinch (`relay_status = "2"`) only.

6. **`notify.PLACEHOLDER` unconfirmed.** The HA notify service name for 3d must be
   verified in Developer Tools before implementing automations.
