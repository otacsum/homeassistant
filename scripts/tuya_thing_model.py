#!/usr/bin/env python3
"""
tuya_thing_model.py — Tuya device thing model + report log inspector

Fetches the v2.0 thing model for a device (services, properties, events, actions)
and optionally fetches report-logs and the current shadow for specific DP codes.

Use this when:
- You need to discover what DPs a device supports (name, type, enum values, ranges)
- You want to see if a device emits Thing Events (separate from DP reports)
- You want to inspect specific DP current values by code name

Usage:
    python3 tuya_thing_model.py <DEVICE_ID> [code1,code2,...]

    DEVICE_ID       Tuya device ID (required)
    code1,code2,... Optional comma-separated DP code names to show current shadow values for
                    (e.g. relay_status,work_state,data_identification)

Credentials are read automatically from the HA config entry.

Examples:
    # Full thing model for a device
    python3 tuya_thing_model.py ebf32ecd372cf16d81xske

    # Model + current shadow values for specific codes
    python3 tuya_thing_model.py ebf32ecd372cf16d81xske relay_status,work_state
"""

import json, hmac, hashlib, time, urllib.request, urllib.parse, datetime, sys

# ── Credentials from HA config ────────────────────────────────────────────────
path = '/root/homeassistant/.storage/core.config_entries'
data = json.load(open(path))
entries = [e for e in data['data']['entries'] if 'tuya' in e.get('domain', '').lower()]
if not entries:
    raise SystemExit('No Tuya config entry found in core.config_entries')
opts = entries[0]['options']
ACCESS_ID     = opts['access_id']
ACCESS_SECRET = opts['access_secret']
BASE_URL      = 'https://openapi.tuyaus.com'

# ── Args ──────────────────────────────────────────────────────────────────────
if len(sys.argv) < 2:
    raise SystemExit(__doc__)
DEVICE_ID = sys.argv[1]
CODES = sys.argv[2] if len(sys.argv) >= 3 else None

# ── Signing ───────────────────────────────────────────────────────────────────
def _sign(method, path, params, body, token, t):
    str_to_sign  = method + '\n'
    str_to_sign += hashlib.sha256((body or '').encode()).hexdigest() + '\n'
    str_to_sign += '\n'
    str_to_sign += (path + '?' + '&'.join(f'{k}={v}' for k, v in sorted(params.items()))) if params else path
    return hmac.new(ACCESS_SECRET.encode(), (ACCESS_ID + token + str(t) + str_to_sign).encode(), hashlib.sha256).hexdigest().upper()

def get_token():
    t = int(time.time() * 1000)
    p, q = '/v1.0/token', {'grant_type': '1'}
    s = _sign('GET', p, q, '', '', t)
    req = urllib.request.Request(BASE_URL + p + '?' + urllib.parse.urlencode(q),
          headers={'client_id': ACCESS_ID, 'sign': s, 'sign_method': 'HMAC-SHA256', 't': str(t), 'lang': 'en'})
    resp = json.loads(urllib.request.urlopen(req).read())
    if not resp.get('success'):
        raise SystemExit('Token failed: ' + str(resp))
    return resp['result']['access_token']

def api_get(endpoint, params=None, token=''):
    t = int(time.time() * 1000)
    s = _sign('GET', endpoint, params or {}, '', token, t)
    url = BASE_URL + endpoint + (('?' + urllib.parse.urlencode(params)) if params else '')
    req = urllib.request.Request(url, headers={
        'client_id': ACCESS_ID, 'access_token': token, 'sign': s,
        'sign_method': 'HMAC-SHA256', 't': str(t), 'lang': 'en'})
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as ex:
        return {'_http_error': f'{ex.code} {ex.reason}', '_body': ex.read().decode()[:300]}

# ── Main ──────────────────────────────────────────────────────────────────────
token = get_token()
print(f'Token OK  |  Device: {DEVICE_ID}\n')

# 1. v2.0 thing model
print('=== v2.0 Thing Model (services → properties / events / actions) ===')
result = api_get(f'/v2.0/cloud/thing/{DEVICE_ID}/model', {}, token)
if result.get('success'):
    model_str = result['result'].get('model', '')
    try:
        model = json.loads(model_str)
        for svc in model.get('services', []):
            name = svc.get('name', svc.get('code', ''))
            print(f'\nService: {name}')
            props   = svc.get('properties', [])
            events  = svc.get('events', [])
            actions = svc.get('actions', [])
            if props:
                print(f'  Properties ({len(props)}):')
                for p in props:
                    spec = p.get('typeSpec', {})
                    extra = ''
                    if spec.get('type') == 'enum':
                        extra = f"  values={spec.get('range', [])}"
                    elif spec.get('type') in ('int', 'float'):
                        extra = f"  range=[{spec.get('min')}, {spec.get('max')}] step={spec.get('step')}"
                    print(f"    dp_id={str(p.get('dp_id','?')):3s}  code={p.get('code','?'):30s}  name={p.get('name','?'):30s}  type={spec.get('type','?')}{extra}")
            if events:
                print(f'  Events ({len(events)}):')
                for ev in events:
                    print(f"    code={ev.get('code')}  name={ev.get('name')}")
                    for out in ev.get('outputParams', []):
                        print(f"      param: code={out.get('code')}  name={out.get('name')}  type={out.get('typeSpec',{}).get('type','?')}")
            if actions:
                print(f"  Actions ({len(actions)}): {[a.get('code') for a in actions]}")
    except Exception as ex:
        print('Parse error:', ex)
        print(model_str[:500])
else:
    print('Error:', result)

# 2. Current shadow for specific codes (if requested)
if CODES:
    print(f'\n=== Current shadow for codes: {CODES} ===')
    r = api_get(f'/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties', {'codes': CODES}, token)
    if r.get('success'):
        props = r['result'].get('properties', [])
        for p in props:
            t_ms  = p.get('time', 0)
            local = str(datetime.datetime.fromtimestamp(t_ms / 1000)) if t_ms else '?'
            print(f"  code={p.get('code'):30s}  value={str(p.get('value')):15s}  updated={local}")
    else:
        print('Error:', r)

# 3. Report-logs for today (Thing-level events, not DP reports)
today_start = int(datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
today_end   = int(time.time() * 1000)
print(f'\n=== v2.0 Report-logs (today, thing-level events) ===')
r2 = api_get(f'/v2.0/cloud/thing/{DEVICE_ID}/report-logs', {
    'start_time': today_start, 'end_time': today_end, 'size': 50
}, token)
if '_http_error' in r2:
    print('HTTP error:', r2['_http_error'])
elif r2.get('success'):
    items = r2['result']
    if isinstance(items, dict):
        items = items.get('logs', items.get('list', items.get('data', [])))
    print(f'  {len(items)} events')
    for item in items:
        et = item.get('event_time', item.get('time', item.get('ts', 0)))
        if et:
            item['_local'] = str(datetime.datetime.fromtimestamp(int(et) / 1000))
        print(' ', json.dumps(item))
else:
    print('  API error:', r2.get('code'), r2.get('msg'))
