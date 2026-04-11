# Tuya Cat Litter Box — Operation Logs Research

**Date:** 2026-04-10  
**Device:** NEO-B Cat Litter Box (NEO-B Public)  
**Integration:** Xtend Tuya v4.4.1 (`azerty9971/xtend_tuya`)

---

## 1. Device Identification

| Field | Value |
|-------|-------|
| HA Device ID | `f446635127a54a026b27bf20c5a70c9c` |
| Tuya Device UUID | `ebf32ecd372cf16d81xske` |
| Product ID | `djxo7tynpa1aocaa` |
| Tuya Category | `msp` (Pet Care — Smart Pet Toilet) |
| Model | NEO-B |
| HA Area | Mud Room |
| Online | Yes |
| Local Key | `><oQ<K9}HVB&(.kh` (for LAN protocol) |

---

## 2. Tuya API Credentials (from xtend_tuya config entry)

| Field | Value |
|-------|-------|
| Access ID | `<ACCESS_ID>` |
| Access Secret | `<ACCESS_SECRET>` |
| Endpoint | `https://openapi.tuyaus.com` |
| Auth Endpoint | `/v1.0/iot-01/associated-users/actions/authorized-login` |
| App Schema | `tuyaSmart` |
| Country Code | `1` (US) |
| Sharing Endpoint | `https://apigw.tuyaus.com` (used by tuya_sharing manager) |

### Authentication Flow

```python
import hashlib, hmac, json, time, urllib.request, urllib.parse

ACCESS_ID = '<ACCESS_ID>'
ACCESS_SECRET = '<ACCESS_SECRET>'
ENDPOINT = 'https://openapi.tuyaus.com'

def calc_sign(method, path, params=None, body=None, access_token=''):
    """Sign a Tuya OpenAPI request (matches openapi.py exactly — no nonce)."""
    str_to_sign = method + '\n'
    content = '' if not body else json.dumps(body)
    str_to_sign += hashlib.sha256(content.encode('utf8')).hexdigest().lower()
    str_to_sign += '\n\n' + path  # empty header line between hash and URL
    if params:
        str_to_sign += '?' + ''.join(f'{k}={params[k]}&' for k in sorted(params.keys()))[:-1]
    t = int(time.time() * 1000)
    message = ACCESS_ID + access_token + str(t) + str_to_sign
    sign = hmac.new(ACCESS_SECRET.encode('utf8'), message.encode('utf8'), hashlib.sha256).hexdigest().upper()
    return sign, t

# Get access token (valid 2 hours)
auth_body = {
    'country_code': '1',
    'username': '<USERNAME_EMAIL>',
    'password': hashlib.md5('<password>'.encode('utf8')).hexdigest(),
    'schema': 'tuyaSmart'
}
response = tuya_request('POST', '/v1.0/iot-01/associated-users/actions/authorized-login', body=auth_body)
token = response['result']['access_token']
refresh_token = response['result']['refresh_token']

# Refresh an expired token (simpler — no user credentials needed)
refresh_response = tuya_request('GET', f'/v1.0/token/{refresh_token}')
new_token = refresh_response['result']['access_token']
```

---

## 3. All Data Points (DPs)

### 3a. Standard DPs (Tuya `msp` Category Spec)

These are logged by the Tuya cloud and accessible via the device logs API.

| DP ID | Code | Type | Values | Notes |
|-------|------|------|--------|-------|
| 1 | `switch` | Boolean | true/false | Device power |
| 2 | `work_mode` | Enum | `auto_clean`, `manual_clean` | Cleaning mode |
| 3 | `start` | Boolean | true/false | Start clean trigger |
| 4 | `auto_clean` | Boolean | true/false | Auto-clean enabled |
| 5 | `delay_clean_time` | Integer | 1–60 min | Delay after cat exits |
| 6 | `cat_weight` | Integer | 0–500 (scale 1) | **Cat weight in 0.1 kg** (50 = 5.0 kg) |
| 7 | `excretion_times_day` | Integer | 0–60 | **Visit count — resets at midnight** |
| 8 | `excretion_time_day` | Integer | 0–600 sec | **Duration of most recent visit** |
| 9 | `manual_clean` | Boolean | true/false | Manual clean in progress |
| 23 | `factory_reset` | Boolean | true/false | Factory reset trigger |

### 3b. Extended DPs (Manufacturer-Specific, NOT in Tuya Category Spec)

These DPs are pushed by the device via MQTT and captured by xtend_tuya, but are **NOT stored in Tuya's cloud device logs**. They are only available in real-time via MQTT push and from the HA state recorder.

| DP ID | HA Entity | Current Value | Notes |
|-------|-----------|---------------|-------|
| 101 | `number.cat_litter_dis_current` | 1 | Unknown — possibly motor position |
| 102 | `select.cat_litter_doorbell_song` | `white` | Notification tone |
| 103 | `sensor.cat_litter_use_time` | 9 | **Cumulative lifetime clean count** |
| 104 | `sensor.cat_litter_cold_temp_current` | 0 | Internal temperature |
| 105 | `select.cat_litter_relay_status` | `1` | Relay state (`1`=normal, `2`=inverted?) |
| 106 | `number.cat_litter_flow_set` | 200 | Flow rate setting |
| 107 | `number.cat_litter_bright_value` | 200 | Indicator brightness |
| 108 | `sensor.cat_litter_work_state` | `5` | **Operational state — see table below** |
| 109 | `sensor.cat_litter_battery_state` | `Auto` | Power/charging status |
| 110 | `sensor.cat_litter_data_identification` | `Standby` | **Human-readable operation label** |

---

## 4. Work State Decode (DP 108)

Decoded from HA state history correlated with known events:

| Value | Interpretation | Evidence |
|-------|---------------|----------|
| `9` | Cat detected / cat entering box | Precedes cleaning cycle start |
| `3` | Drum rotating / cleaning in progress | Occurs after `9`, before `5` |
| `5` | Clean complete / standby | Most common terminal state |
| `4` | Idle / waiting | Common resting state |
| `2` | Error / anomaly | Observed once, context unclear |

**Observed state sequence during a cleaning cycle:**
```
work_state → 9  (cat detected)
work_state → 3  (cleaning rotating)
work_state → 5  (clean complete)
```

**HA history example (04-09):**
```
06:56 → work_state: 9   (cat entered)
06:56 → work_state: 3   (cleaning)
06:59 → work_state: 5   (done)
07:01 → work_state: 9   (cat entered again)
07:03 → work_state: 3   (cleaning)
07:21 → work_state: 5   (done)
```

---

## 5. Data Identification (DP 110)

`sensor.cat_litter_data_identification` provides a **human-readable string** describing the current device operation. Confirmed values:
- `Standby` — device idle
- `Cleaning` — active cleaning cycle

Additional expected values (inferred from msp category documentation):
- `Cat Using` — cat is in the box
- `Cat Detected` — motion/weight sensor triggered
- `Auto Clean Complete` — auto cleaning finished
- `Manual Clean Complete` — manual cleaning finished
- `Trash Bin Full` — waste bin needs emptying

> **⚠️ Critical Issue:** `sensor.cat_litter_data_identification` has **zero entries in the HA state recorder database** (`states_meta` table shows no record for this entity). This means HA is not recording its history. States are received via MQTT but never persisted.

---

## 6. Tuya API Device Logs

### Endpoint

```
GET https://openapi.tuyaus.com/v1.0/devices/{device_id}/logs
```

Use Tuya device UUID: `ebf32ecd372cf16d81xske`

### Log Types

| Type | Description | Example |
|------|-------------|---------|
| 1 | Device online/offline | ~7 events in 7 days |
| 2 | Automated event (pairing/bind) | 1 event (setup only) |
| 7 | **DP state reports** | All standard DP changes |
| 8 | RSSI/WiFi signal strength | Every ~1 hour (-69 to -72 dBm) |
| 9 | Device registration | 1 event |

### Type 7 Log — Per-Visit Data Structure

Each cat visit triggers a batch of 3 log entries (same timestamp):

```json
{
  "code": "excretion_times_day",
  "event_id": 7,
  "event_time": 1775826457421,
  "value": "2"
},
{
  "code": "cat_weight",
  "event_id": 7,
  "event_time": 1775826457425,
  "value": "50"
},
{
  "code": "excretion_time_day",
  "event_id": 7,
  "event_time": 1775826457429,
  "value": "60"
}
```

### Sample Type 7 Query

```python
import time

end_time = int(time.time() * 1000)
start_time = end_time - 7 * 24 * 3600 * 1000  # 7 days

params = {
    'type': '7',
    'start_time': str(start_time),
    'end_time': str(end_time),
    'size': '100',
    # 'start_row_key': '<next_row_key>'  # for pagination
}
response = tuya_request('GET', f'/v1.0/devices/{DEVICE_ID}/logs', params=params, access_token=token)

# Paginate
while response['result'].get('has_next'):
    params['start_row_key'] = response['result']['next_row_key']
    response = tuya_request('GET', f'/v1.0/devices/{DEVICE_ID}/logs', params=params, access_token=token)
```

### 7-Day Observed Visit Log (Type 7, Apr 3–10 2026)

The standard DP logs provide a complete visit history:

```
04-03 12:00 | visit #2 | weight: 5.4kg | duration: 170s
04-03 18:19 | visit #3 | weight: 5.6kg | duration: 22s
04-03 18:27 | visit #4 | weight: 5.2kg | duration: 111s
04-03 21:20 | visit #5 | weight: 5.0kg | duration: 65s
04-04 04:46 | visit #1 | weight: 5.3kg | duration: 84s
04-04 12:56 | visit #2 | weight: 5.2kg | duration: 152s
04-04 19:52 | visit #3 | weight: 5.4kg | duration: 172s
... (full history available via API)
04-10 07:07 | visit #2 | weight: 5.0kg | duration: 60s
```

### Limitations

- **7 days** of log retention on free Tuya IoT plan
- Extended DPs (101–110) including `work_state` and `data_identification` are **not captured** in any log type
- `iot-03` device logs endpoint requires separate API subscription (`No permissions. This API is not subscribed.`)
- `v1.2` device logs endpoint does not exist (`uri path invalid`)
- Property history endpoint (`/v2.0/cloud/thing/{id}/shadow/properties/history`) also returned `uri path invalid`

---

## 7. xtend_tuya Architecture

The integration uses two parallel managers:

### tuya_iot Manager
- Uses `access_id`/`access_secret` with HMAC-SHA256 signing
- Endpoint: `https://openapi.tuyaus.com`
- Handles: device control commands (set DP values)
- No operation log functionality implemented

### tuya_sharing Manager
- Uses `tuya_sharing` Python library (CustomerApi)
- Endpoint: `https://apigw.tuyaus.com`
- Different auth: AES-GCM encrypted request body with `X-*` headers
- Handles: real-time device state via MQTT subscription
- No operation log functionality implemented

**Both managers lack any operation log retrieval.** All operational state comes from real-time MQTT pushes only.

### MQTT Push Coverage

The extended DPs (108–110) are received exclusively via MQTT push (`tuya_sharing` manager → MQ → HA state machine). They are NOT polled and NOT stored in Tuya's cloud log system.

---

## 8. Current HA Recorder Status

| Entity | In HA DB | History Coverage |
|--------|---------|-----------------|
| `sensor.cat_litter_number_of_excretion` | ✅ Yes | Full history since 04-08 |
| `sensor.cat_litter_cat_weight` | ✅ Yes | Full history since 04-08 |
| `sensor.cat_litter_duration_of_excretion` | ✅ Yes | Full history since 04-08 |
| `sensor.cat_litter_work_state` | ✅ Yes | History since 04-07 |
| `sensor.cat_litter_battery_state` | ✅ Yes | History since 04-08 |
| **`sensor.cat_litter_data_identification`** | **❌ No** | **Never recorded** |

The `data_identification` entity exists in HA's entity registry but its state changes are not being written to the recorder database. This is the primary gap for operation log visibility.

---

## 9. Approaches to Expose Operation Logs

### Approach 1: Fix HA Recorder for `data_identification` ✅ Recommended First Step

**Problem:** `sensor.cat_litter_data_identification` is not being recorded.

**Solution:** Verify it is not excluded from the recorder in `configuration.yaml`, and confirm the entity is not disabled.

```yaml
# Check configuration.yaml for recorder exclude list
recorder:
  exclude:
    entities:
      # Confirm sensor.cat_litter_data_identification is NOT here
```

If the entity is enabled but states aren't being written, it may be because the entity sends the same value repeatedly (HA deduplicates unchanged states). The `data_identification` DP likely only changes transiently during operation.

### Approach 2: Template Sensors for Decoded States ✅ Easy

Create template sensors that translate work_state numeric codes into descriptive strings:

```yaml
template:
  - sensor:
      - name: "Cat Litter Operation"
        unique_id: cat_litter_operation_decoded
        state: >
          {% set ws = states('sensor.cat_litter_work_state') %}
          {% if ws == '9' %}Cat Detected
          {% elif ws == '3' %}Cleaning
          {% elif ws == '5' %}Standby
          {% elif ws == '4' %}Idle
          {% elif ws == '2' %}Error
          {% else %}Unknown ({{ ws }})
          {% endif %}
        icon: >
          {% set ws = states('sensor.cat_litter_work_state') %}
          {% if ws in ('3',) %}mdi:rotate-3d-variant
          {% elif ws == '9' %}mdi:cat
          {% elif ws == '5' %}mdi:check-circle
          {% elif ws == '2' %}mdi:alert-circle
          {% else %}mdi:toilet
          {% endif %}
```

### Approach 3: Automation Triggers from Existing Sensors ✅ Recommended

The existing sensors are sufficient to drive all meaningful automations:

```yaml
# Cat used the litter box
automation:
  - alias: "Cat Litter — Cat Visit Detected"
    trigger:
      - platform: state
        entity_id: sensor.cat_litter_number_of_excretion
    condition:
      - condition: template
        value_template: >
          {{ trigger.to_state.state | int > trigger.from_state.state | int }}
    action:
      - service: notify.mobile_app
        data:
          title: "Cat Litter"
          message: >
            Cat used the box (visit #{{ states('sensor.cat_litter_number_of_excretion') | int }}).
            Weight: {{ (states('sensor.cat_litter_cat_weight') | float / 10) | round(1) }} kg,
            Duration: {{ states('sensor.cat_litter_duration_of_excretion') | int }}s

  # Cleaning cycle started
  - alias: "Cat Litter — Cleaning Started"
    trigger:
      - platform: state
        entity_id: sensor.cat_litter_work_state
        to: "3"
    action:
      - service: notify.mobile_app
        data:
          message: "Cat litter box cleaning started."

  # Cleaning cycle complete
  - alias: "Cat Litter — Cleaning Complete"
    trigger:
      - platform: state
        entity_id: sensor.cat_litter_work_state
        to: "5"
        from: "3"
    action:
      - service: notify.mobile_app
        data:
          message: "Cat litter box cleaning complete."

  # Error state
  - alias: "Cat Litter — Error Detected"
    trigger:
      - platform: state
        entity_id: sensor.cat_litter_work_state
        to: "2"
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Cat Litter Error"
          message: "Cat litter box reported an error state."
```

### Approach 4: Custom REST Sensor Polling Tuya API Logs

For richer, timestamped operation history accessible outside HA:

```yaml
# In configuration.yaml
rest:
  - resource: "https://openapi.tuyaus.com/v1.0/devices/ebf32ecd372cf16d81xske/logs"
    # Headers require dynamic HMAC signing — not directly possible with standard REST sensor
    # Requires a custom component or command_line sensor with signing script
    scan_interval: 300  # 5 minutes
```

> **Note:** Because Tuya API requires HMAC-SHA256 signing with a timestamp in both the query string and headers, a standard REST sensor cannot be used directly. A `command_line` sensor running a Python signing script, or a custom HA component, would be required.

**Alternative — AppDaemon script:**
An AppDaemon app could poll the Tuya API every 5 minutes, parse the logs, and expose them as HA entities or fire events.

### Approach 5: Extend xtend_tuya with Log Polling (Advanced)

File a feature request or fork `xtend_tuya` to add:
- A `button` entity that fetches recent device logs from Tuya API
- A `sensor` entity that exposes the last N operation events as attributes
- A `service` call that fires HA events for each log entry

The integration already has the Tuya API authentication infrastructure (`TuyaOpenAPI` class in `lib/tuya_iot/openapi.py`). Adding a log fetch would require:
1. Adding a new service definition in `services.yaml`
2. Calling `openapi.get(f'/v1.0/devices/{device_id}/logs', params={'type': '7', ...})`
3. Firing `hass.bus.async_fire()` events for each log entry

---

## 10. Recommended Implementation Plan

### Step 1 — Verify `data_identification` is being recorded (no config change needed if recorder is default)

Check HA logbook for `sensor.cat_litter_data_identification` to see if it's producing state changes at all.

### Step 2 — Add decoded template sensor

Add the `sensor.cat_litter_operation` template sensor from Approach 2 to expose human-readable cleaning states.

### Step 3 — Add visit automations

Use the `excretion_times_day` increment trigger to log each cat visit with weight/duration.

### Step 4 — Add work_state automations

Trigger on `work_state` changes for cleaning start/complete/error alerts.

### Step 5 (Optional) — Tuya API log poller

If cross-session history or richer timestamps are needed, implement an AppDaemon app or command_line sensor to periodically poll the Tuya API type=7 logs.

---

## 11. Key Technical Constraints

1. **Extended DPs (101–110) have no cloud log history** — they exist only in real-time MQTT and HA's recorder
2. **`data_identification` (DP110) is not being recorded by HA** — fix this first
3. **Tuya API token expires every 2 hours** — any polling solution must handle token refresh
4. **Free Tuya IoT plan = 7 days log retention** — longer history requires paid "Device Logs Storage Service"
5. **`work_state` values are undocumented** — mapping in Section 4 is inferred from observed behavior
6. **Type=7 logs miss some visits** — occasionally `cat_weight` is absent from a visit entry (device didn't register weight)
7. **`use_time` (DP103) = cumulative lifetime cleaning cycles** (currently 9), increments with each clean — can be used as a reliable trigger

---

## 12. API Quick Reference

```python
ENDPOINT = 'https://openapi.tuyaus.com'
DEVICE_UUID = 'ebf32ecd372cf16d81xske'

# Device info
GET /v1.0/devices/{DEVICE_UUID}

# Current DP values
GET /v1.0/devices/{DEVICE_UUID}/status
GET /v2.0/cloud/thing/{DEVICE_UUID}/shadow/properties

# Device functions (settable DPs)
GET /v1.0/devices/{DEVICE_UUID}/functions

# Product specification (standard DPs schema)
GET /v1.0/devices/{DEVICE_UUID}/specifications

# Operation logs (7-day retention, standard DPs only)
GET /v1.0/devices/{DEVICE_UUID}/logs?type=7&start_time=<ms>&end_time=<ms>&size=100

# Set a DP value
POST /v1.0/devices/{DEVICE_UUID}/commands
Body: {"commands": [{"code": "manual_clean", "value": true}]}
```

---

## 13. Confirmed Error Code Mapping: "Bottom Infrared Anti-Pinch Triggered"

### Finding

The Tuya app operation log entry **"Bottom infrared anti-pinch triggered!"** maps exactly to:

> **`select.cat_litter_relay_status` (DP 105) → value `"2"`**

Confirmed by correlating the Tuya app log timestamps (07:25:32 and 07:25:44 MDT, April 9, 2026) against HA state history:

| Timestamp (MDT) | Entity | Value | Source |
|-----------------|--------|-------|--------|
| 07:25:32.920 | `select.cat_litter_relay_status` | `2` | HA DB (exact match to first Tuya error log) |
| 07:25:44 | *(no HA state change)* | *(already `2`)* | User manually tripped sensor; state already "2" so no HA state change recorded |
| 09:31:41 | `select.cat_litter_relay_status` | `1` | HA DB — error cleared ~2hr 6min later |

### relay_status Values

| Value | Meaning |
|-------|---------|
| `1` | Normal — infrared sensor clear |
| `2` | **"Bottom infrared anti-pinch triggered!"** — obstruction detected |

### Event Context (April 9, 2026)

Reconstructed timeline showing the error occurred during the third manual cleaning cycle:

```
07:01:45  work_state → 9        Cat detected in box
07:03:18  work_state → 3        Auto-cleaning started
07:18:53  manual_clean → true   Manual clean cycle #1 triggered
07:21:33  manual_clean → false  Cycle #1 complete — work_state → 5
07:21:35  manual_clean → true   Manual clean cycle #2 triggered
07:24:04  manual_clean → false  Cycle #2 complete
07:24:32  manual_clean → true   Manual clean cycle #3 triggered
07:25:32  relay_status → 2      ⚠️ ANTI-PINCH TRIGGERED (Tuya app log entry #1)
07:25:44                        ⚠️ User manually tripped sensor (Tuya app log entry #2, no HA state change — state already "2")
07:27:02  manual_clean → false  Cycle #3 "complete" despite active error
09:28:26  excretion_times_day → 2   Next cat visit
09:31:41  relay_status → 1     ✅ Error cleared (~2hr 6min after trigger)
```

The second Tuya app log entry at 07:25:44 was a deliberate manual trigger of the infrared sensor by the user (12 seconds after the auto-trigger). HA records no second state change because the entity was already in state "2" — a genuine independent trigger event, not a re-broadcast.

### Historical Occurrences

All recorded `relay_status → 2` events since HA integration setup:

| Date | Triggered | Cleared | Duration |
|------|-----------|---------|----------|
| Apr 1 | 06:45 MDT (pre-existing at HA setup) | 07:41 MDT | ~56 min |
| Apr 7 | 18:05 MDT | 18:24 MDT | ~19 min |
| Apr 7 | 22:13 MDT | 22:14 MDT | ~15 sec |
| Apr 9 | 07:25 MDT | 09:31 MDT | ~2 hr 6 min |

### Automation to Alert on Anti-Pinch Error

```yaml
automation:
  - alias: "Cat Litter — Anti-Pinch Error Triggered"
    trigger:
      - platform: state
        entity_id: select.cat_litter_relay_status
        to: "2"
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Cat Litter Box Error"
          message: >
            Bottom infrared anti-pinch triggered!
            Manual inspection required.
            {{ now().strftime('%I:%M %p') }}

  - alias: "Cat Litter — Anti-Pinch Error Cleared"
    trigger:
      - platform: state
        entity_id: select.cat_litter_relay_status
        to: "1"
        from: "2"
    action:
      - service: notify.mobile_app
        data:
          title: "✅ Cat Litter Box Recovered"
          message: >
            Anti-pinch error cleared.
            Was triggered for {{ (as_timestamp(now()) - as_timestamp(trigger.from_state.last_changed)) | int // 60 }} minutes.
```


---

## Section 14 — Door Anti-Pinch vs Bottom Anti-Pinch Verification (April 11, 2026)

### Event Under Investigation

The Tuya app showed a **"door anti-pinch triggered!"** entry at **07:07:49 MDT, April 11, 2026**, occurring approximately 4 minutes after a cat visit (excretion logged at 07:03:31 MDT), during the subsequent auto-cleaning cycle.

### Verification Method

Three independent data sources were checked for any DP change at 07:07:49 ±5 min:

1. **HA recorder** — queried all `cat_litter` entity state changes for all of April 11
2. **Tuya API type 7 logs** — queried full April 11 UTC window via `/v1.0/devices/{DEVICE_ID}/logs?type=7`
3. **Tuya device shadow** — retrieved all current DP values via `/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties`

### Findings

#### HA Recorder — April 11 cat_litter state changes

| Time (MDT) | Entity | Value |
|------------|--------|-------|
| 00:00:02 | `sensor.cat_litter_number_of_excretion` | 0.0 (midnight reset) |
| 07:03:31 | `sensor.cat_litter_number_of_excretion` | 1.0 |
| 07:03:31 | `sensor.cat_litter_cat_weight` | 5.1 kg |
| 07:03:31 | `sensor.cat_litter_duration_of_excretion` | 120 sec |
| ~~07:07:49~~ | ~~`select.cat_litter_relay_status`~~ | ~~No change~~ |
| 07:57:36 | `sensor.cat_litter_number_of_excretion` | 2.0 |
| 07:57:36 | `sensor.cat_litter_cat_weight` | 5.2 kg |
| 07:57:36 | `sensor.cat_litter_duration_of_excretion` | 49 sec |

**`select.cat_litter_relay_status` had zero state updates on April 11** — last update was April 9 at 09:31:41 MDT (state = "1", normal).

#### Tuya API Type 7 Logs — April 11

7 entries returned for the full day; all are excretion-related DPs at 07:03 and 07:57 MDT. **Zero entries at 07:07:49 or nearby.** This is consistent with the finding from Section 13 that standard API type 7 logs do not capture extended DPs (101–110).

#### relay_status (DP105) — Full History Check

The select entity has no constrained options list; it accepts any raw DP value. With no entries for April 11, relay_status was never updated by any MQTT message that day. The door anti-pinch event **did not** cause relay_status to change to any value (including a hypothetical "3").

### Conclusion

> **The April 11 "door anti-pinch" and April 9 "bottom infrared anti-pinch" are distinct event types and map to different DPs.**

| Event | DP | HA Entity | Detectable in HA |
|-------|----|-----------|-----------------|
| Bottom infrared anti-pinch | DP105 `relay_status` = `"2"` | `select.cat_litter_relay_status` | ✅ Yes |
| Door anti-pinch | Unknown — NOT DP105 | Unknown — no active entity captures it | ❌ No |

### What Is the Door Anti-Pinch DP?

The door anti-pinch did not produce any observable HA state change in any of the 12 cat_litter entities tracked in the entity registry. The most likely candidates:

- **`sensor.cat_litter_data_identification` (DP110)** — disabled by integration, zero recorder history. During cleaning cycles this DP cycles through values including "Standby" and "Cleaning". It may also emit a transient "Door Anti-Pinch" value that clears immediately and is invisible because the entity is disabled.
- **An entirely different DP** not currently exposed by Xtend Tuya — the device may send a manufacturer-specific DP outside the 101–110 range that the integration ignores.

### Implication for Tuya-Plan.md

The implementation plan (`docs/Tuya-Plan.md`) covers detection of the **bottom anti-pinch only** (via `relay_status → "2"`). The door anti-pinch is currently **not detectable** in Home Assistant without additional investigation.

To detect door anti-pinch in a future session:
1. Enable `sensor.cat_litter_data_identification` (DP110) and monitor during a cleaning cycle
2. Enable Xtend Tuya debug logging (`logger: xtend_tuya: debug`) and capture the next door anti-pinch event to identify the raw DP code and value
