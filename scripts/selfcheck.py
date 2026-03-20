import json
import os
import sys
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

BASE_URL = os.getenv('VF_BASE_URL', 'http://127.0.0.1:5000').rstrip('/') + '/'
USERNAME = os.getenv('VF_USER') or ''
PASSWORD = os.getenv('VF_PASS') or ''
TIMEOUT = int(os.getenv('VF_TIMEOUT', '10'))

results = []

def record(name, ok, detail=''):
    results.append((name, ok, detail))
    status = 'OK' if ok else 'FAIL'
    print(f'[{status}] {name} {detail}'.strip())


def _request(method, path, payload=None, auth=None):
    url = urljoin(BASE_URL, path.lstrip('/'))
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if auth:
        headers['Authorization'] = f'Bearer {auth}'
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
            return resp.status, body
    except HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b''
        return e.code, body
    except URLError as e:
        raise e


def safe_get(path, auth=None):
    return _request('GET', path, None, auth)


def safe_post(path, payload=None, auth=None):
    return _request('POST', path, payload or {}, auth)


def check_public():
    checks = [
        ('effects/types', lambda: safe_get('/api/effects/types')),
        ('duo/resources/categories', lambda: safe_get('/api/duo/resources/categories')),
        ('duo/cache/status', lambda: safe_get('/api/duo/cache/status')),
        ('duo/ffmpeg/status', lambda: safe_get('/api/duo/ffmpeg/status')),
    ]
    for name, fn in checks:
        try:
            status, _ = fn()
            record(name, status == 200, f'status={status}')
        except Exception as e:
            record(name, False, f'error={e}')


def login_and_check():
    if not USERNAME or not PASSWORD:
        record('auth/login', False, 'missing VF_USER/VF_PASS')
        return None
    try:
        status, body = safe_post('/api/auth/login', {'account': USERNAME, 'password': PASSWORD})
    except Exception as e:
        record('auth/login', False, f'error={e}')
        return None
    if status != 200:
        record('auth/login', False, f'status={status}')
        return None
    data = {}
    if body:
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            data = {}
    token = data.get('token')
    record('auth/login', bool(token), 'token' if token else 'no token')
    return token


def check_authed(token):
    if not token:
        return
    checks = [
        ('user/info', lambda: safe_get('/api/user/info', auth=token)),
        ('materials/list', lambda: safe_get('/api/materials/list', auth=token)),
        ('drafts-folder', lambda: safe_get('/api/drafts-folder', auth=token)),
        ('user/config', lambda: safe_get('/api/user/config', auth=token)),
    ]
    for name, fn in checks:
        try:
            status, _ = fn()
            ok = status in (200, 400, 401, 403)
            record(name, ok, f'status={status}')
        except Exception as e:
            record(name, False, f'error={e}')


def main():
    print('VideoFactory self-check')
    print('Base URL:', BASE_URL)
    check_public()
    token = login_and_check()
    check_authed(token)

    failed = [r for r in results if not r[1]]
    print('\nSummary')
    print('Total:', len(results), 'Failed:', len(failed))
    if failed:
        for name, ok, detail in failed:
            print(f'- {name}: {detail}')

if __name__ == '__main__':
    main()
