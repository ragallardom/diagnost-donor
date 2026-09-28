#!/usr/bin/env python3
"""
DIAGNOSTDONOR - Local Backend Server
Runs a lightweight multi-threaded HTTP REST server bound to 127.0.0.1:8080.
Exposes JSON endpoints for Battery, Thermal/Fans, System Info, Storage,
Bluetooth, HDMI, Wi-Fi, RAM Test, TCG Opal Unlock, Shutdown and Reboot.

Security model (kiosk):
  - Listens only on loopback and rejects requests whose Host header is not
    the loopback address (blocks DNS-rebinding style access).
  - Every POST (state-changing / destructive action) must carry the per-boot
    session token that is injected into index.html when it is served, and a
    same-origin Origin header when the browser sends one.
  - No CORS headers are emitted, and a restrictive Content-Security-Policy
    keeps the UI from loading or contacting anything outside this server.
"""

import http.server
import socketserver
import functools
import json
import os
import re
import secrets
import sys
import subprocess
import tempfile
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(BASE_DIR, 'modules')

for path_dir in [BASE_DIR, MODULES_DIR]:
    if path_dir not in sys.path:
        sys.path.insert(0, path_dir)

from battery import get_battery_info
from thermal import get_thermal_and_fans
from system_info import get_system_summary
from wifi_diag import get_wifi_status
from storage_diag import get_storage_info, get_storage_snapshot, exclusive_disk_access
from bluetooth_diag import (
    get_bluetooth_info,
    start_bluetooth_receiver,
    stop_bluetooth_receiver,
    get_bluetooth_receiver_status
)
from display_hdmi_diag import get_display_and_mobo
from opal_diag import (
    list_target_drives,
    execute_psid_revert,
    execute_nvme_crypto_erase,
    validate_target_device,
)
from stress_diag import start_stress_test, stop_stress_test, get_stress_status

HOST = '127.0.0.1'
PORT = 8080
STATIC_DIR = os.path.join(BASE_DIR, 'static')


def _load_session_token():
    """Per-boot secret required on every POST. Injected into index.html at serve time.

    Persisted (mode 0600, owned by this user) in a runtime dir so a supervisor
    restart of this server keeps the token the already-open kiosk page holds.
    """
    runtime_dir = '/run' if os.access('/run', os.W_OK) else tempfile.gettempdir()
    token_path = os.path.join(runtime_dir, 'diagnost-donor.token')
    try:
        fd = os.open(token_path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'r') as f:
            st = os.fstat(f.fileno())
            token = f.read().strip()
        if st.st_uid == os.getuid() and not (st.st_mode & 0o077) and len(token) >= 32:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    try:
        if os.path.lexists(token_path):
            os.unlink(token_path)
        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(token)
    except OSError:
        pass  # Token stays in memory only; a restart will require a page reload.
    return token


SESSION_TOKEN = _load_session_token()
TOKEN_PLACEHOLDER = '__DIAG_SESSION_TOKEN__'
TOKEN_HEADER = 'X-Diag-Token'

MAX_BODY_BYTES = 64 * 1024

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob: mediastream:; "
    "connect-src 'self'; "
    "worker-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)

BT_NAME_RE = re.compile(r'^[A-Za-z0-9 _-]{1,32}$')


def _serialized(fn, lock=None):
    """Wrap fn so concurrent requests never run it at the same time.

    Diagnostic modules keep module-level state (AC debounce, loopback cache,
    receiver process...) that is not safe to mutate from several threads.
    """
    lock = lock or threading.Lock()

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with lock:
            return fn(*args, **kwargs)
    return wrapper


# Serialize each stateful probe independently so slow ones don't block the others.
get_battery_info = _serialized(get_battery_info)
get_thermal_and_fans = _serialized(get_thermal_and_fans)
get_system_summary = _serialized(get_system_summary)
get_wifi_status = _serialized(get_wifi_status)
get_bluetooth_info = _serialized(get_bluetooth_info)
get_display_and_mobo = _serialized(get_display_and_mobo)
list_target_drives = _serialized(list_target_drives)


def run_isolated(module_name, func_name, *args, timeout=120):
    """Run a CPU-bound module function in a separate Python process.

    The benchmarks hold the GIL for seconds; running them in-process would
    stall every other request thread (telemetry polling) until they finish.
    """
    code = (
        'import json, sys\n'
        'mod = __import__(sys.argv[1])\n'
        'print(json.dumps(getattr(mod, sys.argv[2])(*json.loads(sys.argv[3]))))\n'
    )
    res = subprocess.run(
        [sys.executable, '-c', code, module_name, func_name, json.dumps(args)],
        cwd=MODULES_DIR, capture_output=True, text=True, timeout=timeout
    )
    lines = res.stdout.strip().splitlines()
    if res.returncode != 0 or not lines:
        detail = (res.stderr or '').strip().splitlines()[-1:] or ['sin salida']
        raise RuntimeError(f'{module_name}.{func_name} falló: {detail[0]}')
    return json.loads(lines[-1])


# CPU and RAM benchmarks share a lock so they never skew each other's timings.
_BENCH_LOCK = threading.Lock()
run_ram_benchmark = _serialized(
    lambda chunk_mb=256: run_isolated('ram_benchmark', 'run_ram_benchmark', chunk_mb), _BENCH_LOCK)
run_cpu_benchmark = _serialized(
    lambda: run_isolated('cpu_benchmark', 'run_cpu_benchmark'), _BENCH_LOCK)

_BT_RECEIVER_LOCK = threading.Lock()
start_bluetooth_receiver = _serialized(start_bluetooth_receiver, _BT_RECEIVER_LOCK)
stop_bluetooth_receiver = _serialized(stop_bluetooth_receiver, _BT_RECEIVER_LOCK)

_POWER_LOCK = threading.Lock()


def set_system_volume(vol_percent):
    try:
        vol = max(0, min(100, int(vol_percent)))
        subprocess.run(['amixer', 'sset', 'Master', f'{vol}%', 'unmute'], capture_output=True)
        subprocess.run(['amixer', 'sset', 'Speaker', f'{vol}%', 'unmute'], capture_output=True)
        subprocess.run(['amixer', 'sset', 'Headphone', f'{vol}%', 'unmute'], capture_output=True)
        subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{vol}%'], capture_output=True)
        subprocess.run(['pactl', 'set-sink-mute', '@DEFAULT_SINK@', '0'], capture_output=True)
        return {'success': True, 'volume': vol}
    except Exception as exc:
        return {'success': False, 'error': str(exc)}


def run_disk_operation(operation, device, *args):
    """Run a destructive disk operation on a validated device, holding the disk lock."""
    ok, reason = validate_target_device(device)
    if not ok:
        return {'success': False, 'message': reason, 'log': reason + '\n'}
    with exclusive_disk_access():
        return operation(device, *args)


class DiagnosticHandler(http.server.SimpleHTTPRequestHandler):
    server_version = 'DiagnostDonor'
    sys_version = ''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Content-Security-Policy', CONTENT_SECURITY_POLICY)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def log_message(self, format, *args):  # noqa: A002
        pass  # Suppress request logs for cleaner terminal output

    # ── Request guards ──────────────────────────────────────────────────
    def _allowed_hosts(self):
        port = self.server.server_address[1]
        return {f'127.0.0.1:{port}', f'localhost:{port}'}

    def _host_ok(self):
        return (self.headers.get('Host') or '').lower() in self._allowed_hosts()

    def _origin_ok(self):
        origin = self.headers.get('Origin')
        if origin is None:
            return True
        return origin.lower() in {f'http://{h}' for h in self._allowed_hosts()}

    def _token_ok(self):
        return secrets.compare_digest(self.headers.get(TOKEN_HEADER, ''), SESSION_TOKEN)

    def _reject(self, code, message):
        self.send_json({'success': False, 'error': message, 'message': message}, code)

    def _read_json_body(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError('Cuerpo de la solicitud demasiado grande')
        body = self.rfile.read(length) if length > 0 else b''
        if not body:
            return {}
        payload = json.loads(body.decode('utf-8'))
        if not isinstance(payload, dict):
            raise ValueError('El cuerpo debe ser un objeto JSON')
        return payload

    # ── GET ─────────────────────────────────────────────────────────────
    def do_GET(self):
        if not self._host_ok():
            self._reject(403, 'Host no permitido')
            return

        path = self.path.split('?', 1)[0]

        routes = {
            '/api/system':  get_system_summary,
            '/api/battery': get_battery_info,
            '/api/thermal': get_thermal_and_fans,
            '/api/wifi':    get_wifi_status,
            '/api/storage': get_storage_info,
            '/api/bluetooth': get_bluetooth_info,
            '/api/display': get_display_and_mobo,
            '/api/drives':  list_target_drives,
            '/api/ram-test': lambda: run_ram_benchmark(256),
            '/api/cpu-test': run_cpu_benchmark,
            '/api/stress/status': get_stress_status,
            '/api/bluetooth-psid-status': get_bluetooth_receiver_status,
            '/api/static': lambda: {
                'system':    get_system_summary(),
                'storage':   get_storage_info(),
                'bluetooth': get_bluetooth_info(),
                'display':   get_display_and_mobo(),
                'drives':    list_target_drives(),
            },
            '/api/telemetry': lambda: {
                'battery':   get_battery_info(),
                'thermal':   get_thermal_and_fans(),
                'wifi':      get_wifi_status(),
                'storage':   get_storage_snapshot(),
                'display':   get_display_and_mobo(),
            },
            '/api/all': lambda: {
                'system':    get_system_summary(),
                'battery':   get_battery_info(),
                'thermal':   get_thermal_and_fans(),
                'wifi':      get_wifi_status(),
                'storage':   get_storage_info(),
                'bluetooth': get_bluetooth_info(),
                'display':   get_display_and_mobo(),
                'drives':    list_target_drives(),
            },
        }

        if path in routes:
            try:
                self.send_json(routes[path]())
            except Exception as exc:
                self.send_json({'error': str(exc)}, 500)
            return

        if path.startswith('/api/'):
            self._reject(404, 'Endpoint no encontrado')
            return

        if path in ('/', '/index.html'):
            self.send_index()
            return

        super().do_GET()

    def do_HEAD(self):
        if not self._host_ok():
            self._reject(403, 'Host no permitido')
            return
        super().do_HEAD()

    def list_directory(self, path):
        self._reject(404, 'No encontrado')
        return None

    def send_index(self):
        with open(os.path.join(STATIC_DIR, 'index.html'), 'rb') as f:
            html = f.read().replace(TOKEN_PLACEHOLDER.encode(), SESSION_TOKEN.encode())
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    # ── POST ────────────────────────────────────────────────────────────
    def do_POST(self):
        if not self._host_ok():
            self._reject(403, 'Host no permitido')
            return
        if not self._origin_ok():
            self._reject(403, 'Origen no permitido')
            return
        if not self._token_ok():
            self._reject(403, 'Token de sesión inválido')
            return

        try:
            payload = self._read_json_body()
        except Exception as exc:
            self._reject(400, f'Solicitud inválida: {exc}')
            return

        if self.path == '/api/stress/start':
            try:
                comps = payload.get('components', ['cpu', 'ram', 'ssd', 'gpu'])
                lvl = payload.get('level', 'quick')
                self.send_json(start_stress_test(components=comps, level=lvl))
            except Exception as exc:
                self.send_json({'success': False, 'message': f'Error iniciando estrés: {exc}'}, 400)
            return

        if self.path == '/api/stress/stop':
            try:
                self.send_json(stop_stress_test())
            except Exception as exc:
                self.send_json({'success': False, 'message': f'Error abortando estrés: {exc}'}, 400)
            return

        if self.path == '/api/volume':
            self.send_json(set_system_volume(payload.get('volume', 80)))
            return

        if self.path == '/api/opal-revert':
            try:
                device = str(payload.get('device', ''))
                psid = str(payload.get('psid', ''))
                self.send_json(run_disk_operation(execute_psid_revert, device, psid))
            except Exception as exc:
                self.send_json({'success': False, 'message': f'Error: {exc}'}, 400)
            return

        if self.path == '/api/nvme-crypto-erase':
            try:
                device = str(payload.get('device', ''))
                self.send_json(run_disk_operation(execute_nvme_crypto_erase, device))
            except Exception as exc:
                self.send_json({'success': False, 'message': f'Error: {exc}'}, 400)
            return

        if self.path == '/api/bluetooth-receiver/start':
            try:
                dev_name = str(payload.get('name', 'DIAGNOST-DONOR'))
                if not BT_NAME_RE.match(dev_name):
                    dev_name = 'DIAGNOST-DONOR'
                self.send_json(start_bluetooth_receiver(dev_name))
            except Exception as exc:
                self.send_json({'error': str(exc)}, 500)
            return

        if self.path == '/api/bluetooth-receiver/stop':
            try:
                self.send_json(stop_bluetooth_receiver())
            except Exception as exc:
                self.send_json({'error': str(exc)}, 500)
            return

        if self.path in ('/api/shutdown', '/api/reboot'):
            if not _POWER_LOCK.acquire(blocking=False):
                self.send_json({'ok': True, 'message': 'Acción de energía ya en curso...'})
                return
            if self.path == '/api/shutdown':
                self.send_json({'ok': True, 'message': 'Apagando el sistema...'})
                subprocess.Popen(['shutdown', '-h', 'now'])
            else:
                self.send_json({'ok': True, 'message': 'Reiniciando el sistema...'})
                subprocess.Popen(['reboot'])
            return

        self._reject(404, 'Endpoint no encontrado')

    def send_json(self, data, code=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Keep backward-compat alias
    send_json_response = send_json


class DiagnosticServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run_server(port=PORT):
    with DiagnosticServer((HOST, port), DiagnosticHandler) as httpd:
        print(f'==================================================')
        print(f'DIAGNOSTDONOR: http://{HOST}:{port}')
        print(f'==================================================')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\nServidor detenido.')


if __name__ == '__main__':
    run_server()
