#!/usr/bin/env python3
"""
tuya_shadow.py — Tuya device shadow inspector

Reads the current shadow state (all DPs) for a device, sorted by last-updated
timestamp, and optionally dumps type-7 log history for a date range.

Usage:
    python3 tuya_shadow.py <DEVICE_ID> [YYYY-MM-DD [YYYY-MM-DD]]

    DEVICE_ID   Tuya device ID (required)
    Date args   Optional inclusive date range for type-7 log query (default: today only)
                Note: type-7 logs only capture standard DPs (1–23); extended DPs (100+)
                are MQTT-only and will never appear here.

Credentials are read automatically from the HA config entry stored at:
    /root/homeassistant/.storage/core.config_entries  (looks for any tuya domain entry)

Examples:
    # Show current shadow state for a device
    python3 tuya_shadow.py ebf32ecd372cf16d81xske

    # Shadow + type-7 logs for April 9
    python3 tuya_shadow.py ebf32ecd372cf16d81xske 2026-04-09

    # Shadow + type-7 logs for a date range
    python3 tuya_shadow.py ebf32ecd372cf16d81xske 2026-04-09 2026-04-11
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

date_start = datetime.datetime.strptime(sys.argv[2], '%Y-%m-%d') if len(sys.argv) >= 3 else datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
date_end   = datetime.datetime.strptime(sys.argv[3], '%Y-%m-%d').replace(hour=23, minute=59, second=59) if len(sys.argv) >= 4 else date_start.replace(hour=23, minute=59, second=59)

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

# 1. Full shadow with timestamps
print('=== Shadow: all DPs (sorted by last-updated) ===')
result = api_get(f'/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties', {}, token)
if result.get('success'):
    props = sorted(result['result'].get('properties', []), key=lambda p: p.get('time', 0))
    for p in props:
        t_ms  = p.get('time', 0)
        local = str(datetime.datetime.fromtimestamp(t_ms / 1000)) if t_ms else '?'
        print(f"  dp_id={str(p.get('dp_id', '?')):3s}  code={p.get('code', '?'):30s}  value={str(p.get('value', '?')):15s}  updated={local}")
else:
    print('  Error:', result)

# 2. Type-7 device logs (standard DPs 1–23 only; extended DPs 100+ never appear)
print(f'\n=== Type-7 logs: {date_start.date()} → {date_end.date()} ===')
print('  (Note: extended DPs 100+ are MQTT-only and will not appear here)')
r = api_get(f'/v1.0/devices/{DEVICE_ID}/logs', {
    'start_row_key': '',
    'start_time': int(date_start.timestamp() * 1000),
    'end_time':   int(date_end.timestamp()   * 1000),
    'size': 100,
    'type': 7,
}, token)
if r.get('success'):
    logs  = r['result']
    items = logs.get('logs', []) if isinstance(logs, dict) else (logs or [])
    print(f'  {len(items)} entries')
    for item in items:
        et = item.get('event_time', 0)
        if et:
            item['_local'] = str(datetime.datetime.fromtimestamp(et / 1000))
        print(' ', json.dumps(item))
else:
    print('  Error:', r)
