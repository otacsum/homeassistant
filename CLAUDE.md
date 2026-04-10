# Home Assistant Config — Claude Guidelines

## Connection & Access

- **SSH alias:** `homeassistant` (configured in `~/.ssh/config`)
- **REST API:** Available via MCP (`mcp__homeassistant__*` tools) for reading live state and triggering services
- **Config root:** `/root/homeassistant/` on the HA host
- **All config changes go directly to the HA host via SSH** — do not edit the local mirror at `~/GIT/homeassistant/`

---

## Deployment Workflow

### Reload vs Restart

| Change type | Required action |
|---|---|
| Automations, scripts, scenes | `ha core reload` or service call `automation.reload` / `script.reload` |
| Template entities, helpers (`input_*`), HomeKit filter | Full restart: `ssh homeassistant "ha core restart"` |
| Lovelace dashboards | Browser refresh only |

### Reloading scripts via REST API

`ha core reload-scripts` is not a valid CLI command. Use the REST API instead:

```bash
curl -s -X POST "http://192.168.0.10:8123/api/services/script/reload" \
  -H "Authorization: $TOKEN" -H "Content-Type: application/json"
```

### Workflow

1. Edit files directly on the host via SSH heredoc or `cat >` redirect
2. Validate: `ssh homeassistant "ha core check"` — see known false positive below
3. Reload or restart as appropriate
4. Test via MCP tools or REST API
5. Commit and push from `/root/homeassistant/` on the host

---

## Known HA Quirks

### `ha core check` false positive
Static config validation reports `KeyError: 'triggers'` on automations. This is a known HA bug where trigger platforms are not registered during static analysis. The config is valid and HA will start correctly — safe to ignore.

### `wait_for_trigger` race condition with template entities
When a script action updates a value via a template entity (e.g., a template light whose `set_level` calls another script or service), the async device state update propagates back through the template entity *after* HA has already moved to the next action. A subsequent `wait_for_trigger` watching that same entity will fire immediately on the script's own change, not on an external one.

**Fix:** Use plain `delay` for timing in scripts instead of `wait_for_trigger` when the trigger entity is a template wrapper over a hardware device.

### Template light `turn_on` does not set brightness
A template light's `turn_on` action only executes what is defined under `turn_on:` — typically just switching the underlying switch on. HA then calls `set_level` separately as a second step.

### Template light `set_level` is single-mode
HA creates an internal script for each template light's `set_level` action. This script runs in `single` mode — if it is still executing from a previous call when a new `light.turn_on` arrives, the new `set_level` is silently dropped with a `WARNING: Already running` log entry. Avoid rapid successive `light.turn_on` calls on template lights.

---

## Script vs Automation for Long-Running Sequences

Use a **script** (not an automation) when a sequence needs to be cancellable mid-execution:

- `script.turn_off` stops a running script immediately without affecting future runs
- `automation.turn_off` disables the automation entirely, preventing future triggers until re-enabled

Pattern for externally-cancellable sequences:
1. Automation A triggers `script.turn_on` for the long-running sequence
2. Automation B watches the relevant entity for the cancel condition, calls `script.turn_off` + cleanup

### Distinguishing script-initiated vs external state changes

When a script continuously updates an entity (e.g., incrementing brightness), a cancel-watching automation cannot rely on a simple state change trigger — the script's own updates will also fire it.

**Solution:** Track the expected value in a helper (e.g., `input_number`). Update the helper immediately after each script step. The cancel automation checks whether the actual value deviates from the expected value beyond a tolerance threshold. Choose the threshold to be larger than normal HA-internal state jitter but smaller than a meaningful manual adjustment.

---

## Tuya Integration

### Scale and float requirement

- Brightness is on a **0–1000 scale** (not 0–255)
- Always use **genuine non-integer float values** when calling `number.set_value` near hardware minimums. Integer-like floats (e.g. `10.0`, `12.0`, `20.0`) are treated as boundary sentinels by the integration and may be bumped up to the next valid step. True non-integer floats (e.g. `11.76`) pass through to the device correctly.
- State updates from Tuya devices are asynchronous — there is a delay between calling a service and the entity state reflecting the change.

### Brightness conversion: HA → Tuya

The template light path converts `brightness_pct` via a 0–255 intermediate:

```
brightness_pct → round(pct/100 * 255) → (brightness/255) * 1000 → raw Tuya value
```

This produces non-integer floats that the device accepts:

| `brightness_pct` | HA brightness (0–255) | Raw Tuya sent | Device reports |
|---|---|---|---|
| 1% | 3 | 11.76 | 12.0 |
| 2% | 5 | 19.61 | 20.0 |
| 10% | 26 | 102.0 | 102.0 |

At low brightness percentages the rounding is significant (1% and 2% are 8 raw units apart). For precise low-brightness control in scripts, bypass the template light and set `number.bedroom_dimmer_fan_bright_value` directly with exact raw values.

### Tuya commands sent while switch is off

Any `number.set_value` command sent to a Tuya entity **while its switch is off** queues a delayed state report. This report typically arrives 3–5 seconds after the switch next turns on and will overwrite any brightness command sent in the same window. This means:

- Pre-setting brightness while the switch is off **does not reliably control the startup brightness** directly.
- Sending a command while off followed by `switch.turn_on` + a short delay + a post-set will usually have the post-set overwritten by the delayed report from the pre-set.

### Preventing bright flash on startup (bedroom dimmer pattern)

The Tuya dimmer restores its last stored brightness on power-on. If the light was last used at a high value (e.g. 500 = 50%), it will flash at that brightness when next switched on.

**Effective pattern:** Send a sub-minimum non-integer float (e.g. `11.76`) to the number entity while the switch is off. The device stores this value; because it is below the firmware minimum, the device clamps to its minimum (raw 20 = 2%) on the next power-on rather than restoring the high stored value. No post-set is needed — the clamped startup state is the intended behaviour.

```yaml
- service: number.set_value          # pre-set while switch is off
  data: { value: 11.76 }             # sub-minimum non-integer float
- service: switch.turn_on            # device starts at raw 20 (2%), not stored value
```

Do **not** follow this with a `delay` + post-set to try to reach a lower value — the delayed state report from the pre-set will overwrite the post-set. Accept raw 20 as the startup brightness and begin the ramp from there.

### Firmware startup minimum

The bedroom dimmer's firmware minimum is **raw 20** (2%). The entity reports `min: 10` but values at or below ~11 are clamped to 20 by device firmware on power-on.

---

## HomeKit Bridge

- The HomeKit Bridge integration is configured via the UI, stored in `.storage/core.config_entries`
- `input_boolean` entities are **not** included in the default domain filter — they must be explicitly added to `include_entities`
- To add an entity programmatically: modify the `options.filter.include_entities` array in the relevant HomeKit entry in `.storage/core.config_entries` using Python, then restart HA
- Changes to the HomeKit filter require a **full HA restart** to take effect
- After restart, verify the entity was assigned a HomeKit AID in `.storage/homekit.<entry_id>.aids`

---

## Documentation

- Place automation/feature documentation in `docs/` as Markdown files
- Name files descriptively (e.g., `docs/Feature-Name.md`)

---

## custom-sidebar Plugin

**HACS install location:** `www/community/custom-sidebar/`
**Config file:** `/root/homeassistant/www/custom-sidebar-config.yaml`
**Version installed:** v13.1.0 (compatible with HA 2026.3.0+)

### Version Compatibility

| Home Assistant version | Minimum custom-sidebar version |
|---|---|
| < 2025.5.0 | any (up to v9.4.1) |
| 2025.5.0 – 2026.1.3 | v10.0.0 – v11.2.0 |
| 2026.1.3 – 2026.2.3 | v12.x |
| 2026.3.0+ | v13.0.0+ |

### Critical Installation Rules

1. **`extra_module_url` must use `/hacsfiles/` path** — not `/local/community/...`:
   ```yaml
   frontend:
     extra_module_url:
       - /hacsfiles/custom-sidebar/custom-sidebar-plugin.js
   ```
   HACS serves files via a custom `/hacsfiles/` request handler. Using the `/local/community/` path will silently fail even though the file is physically there.

2. **Reference `custom-sidebar-plugin.js`**, not `custom-sidebar.js`.

3. **Delete the `id` field** from the config if copied from the example file — leaving it causes the plugin to fail silently.

4. **Config changes do not require an HA restart** — hard-refresh the browser (`Cmd+Shift+R`) to apply.

5. **Full HA restart is required** after changing `extra_module_url` in `configuration.yaml`.

### Item Names

The `item` property matches the sidebar item's **lowercase text label** as it appears in the UI:
- `canon madera` — the Canon Madera dashboard
- `to-do list` — the To-do lists built-in item
- `overview` — the default Home dashboard
- `config` — the Settings item
- `hacs` — the HACS item

Use `new_item: true` for items that don't already exist in the sidebar.

### Useful on_click Actions

```yaml
# Open the native HA restart dialog (same as the power button in Settings)
on_click:
  action: open-dialog
  type: restart

# Call a service on click
on_click:
  action: call-service
  service: script.my_script

# Execute arbitrary JavaScript
on_click:
  action: javascript
  code: alert('hello')
```

Omit `href` (or set `href: "#"`) to prevent navigation when using `on_click`.

### Troubleshooting

- Open browser DevTools → Console and look for the `custom-sidebar` info log to confirm the plugin loaded.
- Add `?cs_debug` to the HA URL for verbose debug output showing all detected item names and config parsing.
- If customisations are not applied, verify the `extra_module_url` path and that the config file is in `www/` (not a subdirectory).

---

## Home Assistant Recorder / Database

### Entity ID lookup requires a JOIN

The `states` table does **not** store `entity_id` as a queryable column — it stores a `metadata_id` foreign key. Always join against `states_meta` to filter or display entity IDs:

```python
import sqlite3
conn = sqlite3.connect('/homeassistant/home-assistant_v2.db')
cur = conn.cursor()
cur.execute('''
    SELECT sm.entity_id, s.state, s.last_updated_ts
    FROM states s
    JOIN states_meta sm ON s.metadata_id = sm.metadata_id
    WHERE sm.entity_id LIKE ?
    ORDER BY s.last_updated_ts DESC
''', ('%entity_name%',))
```

### HA deduplicates state changes

HA does **not** create a new `states` row when a device sends the same value it already holds. If an MQTT device broadcasts the same DP value twice (e.g., a sensor re-reporting an active error), only the first transition to that value appears in the DB. Subsequent identical values are silently dropped by the state machine.

Implication: a single HA state entry can represent multiple real-world events if they all produce the same entity state.

### HA host timezone

The HA host runs in **Mountain Daylight Time (MDT, UTC-6)**. All `datetime.datetime.fromtimestamp()` calls on the host return MDT local time. When converting between Tuya API millisecond timestamps and local display times, use MDT as the local reference.

---

## Tuya / Xtend Tuya

### Xtend Tuya architecture (two managers)

Xtend Tuya runs two parallel device managers:

| Manager | Auth | Endpoint | Role |
|---------|------|----------|------|
| `tuya_iot` | HMAC-SHA256 (`access_id` / `access_secret`) | `openapi.tuyaus.com` | Device commands |
| `tuya_sharing` | AES-GCM (`CustomerApi`, `X-*` headers) | `apigw.tuyaus.com` | Real-time MQTT state |

Neither manager implements operation log retrieval. All state comes from real-time MQTT pushes only.

### Tuya OpenAPI signing (no nonce)

The `TuyaOpenAPI` signing algorithm does **not** include a nonce — it is not in the string-to-sign and not in the request headers. The correct signature string is:

```
ACCESS_ID + access_token + timestamp_ms + str_to_sign
```

Where `str_to_sign` is:
```
METHOD\n
SHA256(body)\n
\n                        ← empty header line
/path?key1=val1&key2=val2  ← params sorted by key
```

### Extended DPs are MQTT-only — not in Tuya cloud logs

Tuya device log API (`GET /v1.0/devices/{id}/logs?type=7`) only captures DPs defined in the official product category specification (typically DP IDs 1–23). Manufacturer-extended DPs (IDs 100+) are **never stored in Tuya's cloud log system** — they are only available:
- In real-time via the MQTT push from `tuya_sharing`
- In the HA recorder (if the entity is not excluded)

Always verify which DPs an entity uses before assuming Tuya API log history is available for it.

### relay_status entity maps to infrared safety errors

For this device class (`msp` — smart pet toilet, model NEO-B), `relay_status` (DP 105) acts as an error flag rather than a power relay:

| Value | Meaning |
|-------|---------|
| `1` | Normal |
| `2` | Bottom infrared anti-pinch triggered |

See `docs/Tuya-Research.md` for full device DP mapping and confirmed error correlation.

### Secrets must never appear in docs or git

API keys, access secrets, tokens, passwords, and local keys must **never** be written into any Markdown document or any file tracked by git. Use placeholders (`<ACCESS_ID>`, `<API_KEY>`, etc.) or reference `secrets.yaml` instead.
