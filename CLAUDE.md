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
A template light's `turn_on` action only executes what is defined under `turn_on:` — typically just switching the underlying switch on. HA then calls `set_level` separately as a second step. If you need the device to come on at a specific brightness with no visible jump, pre-set the underlying hardware value *before* calling `turn_on`.

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

- Brightness is on a **0–1000 scale** (not 0–255)
- Use **float values** when setting `number.set_value` for Tuya entities. Integer values near hardware minimums may be bumped up by the integration to enforce device minimums
- State updates from Tuya devices are asynchronous — there is a delay between calling a service and the entity state reflecting the change

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
