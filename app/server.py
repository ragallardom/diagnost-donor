#!/usr/bin/env python3
"""
DIAGNOSTDONOR - Local Backend Server
Runs a lightweight HTTP REST server on localhost:8080.
Exposes JSON endpoints for Battery, Thermal/Fans, System Info, Storage,
Bluetooth, HDMI, Wi-Fi, RAM Test, TCG Opal Unlock, Shutdown and Reboot.
"""

import http.server
import socketserver
import json
import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(BASE_DIR, 'modules')

for path_dir in [BASE_DIR, MODULES_DIR]:
    if path_dir not in sys.path:
        sys.path.insert(0, path_dir)

from battery import get_battery_info
from thermal import get_thermal_and_fans
from system_info import get_system_summary
from wifi_diag import get_wifi_status
from storage_diag import get_storage_info
from bluetooth_diag import get_bluetooth_info
from display_hdmi_diag import get_display_and_mobo
from ram_benchmark import run_ram_benchmark
from cpu_benchmark import run_cpu_benchmark
from opal_diag import list_target_drives, execute_psid_revert
from stress_diag import start_stress_test, stop_stress_test, get_stress_status

PORT = 8080
STATIC_DIR = os.path.join(BASE_DIR, 'static')


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

class DiagnosticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, format, *args):  # noqa: A002
        pass  # Suppress request logs for cleaner terminal output

    def do_GET(self):
        routes = {
            '/api/system':  get_system_summary,
            '/api/battery': get_battery_info,
            '/api/thermal': get_thermal_and_fans,
            '/api/wifi':    get_wifi_status,
            '/api/storage': get_storage_info,
            '/api/bluetooth': get_bluetooth_info,
            '/api/display': get_display_and_mobo,
            '/api/drives':  list_target_drives,
        }

        if self.path in routes:
            try:
                self.send_json(routes[self.path]())
            except Exception as exc:
                self.send_json({'error': str(exc)}, 500)
            return

        if self.path == '/api/ram-test':
            try:
                self.send_json(run_ram_benchmark(256))
            except Exception as exc:
                self.send_json({'error': str(exc)}, 500)
            return

        if self.path == '/api/cpu-test':
            try:
                self.send_json(run_cpu_benchmark())
            except Exception as exc:
                self.send_json({'error': str(exc)}, 500)
            return

        if self.path == '/api/stress/status':
            try:
                self.send_json(get_stress_status())
            except Exception as exc:
                self.send_json({'error': str(exc)}, 500)
            return

        if self.path == '/api/static':
            try:
                self.send_json({
                    'system':    get_system_summary(),
                    'storage':   get_storage_info(),
                    'bluetooth': get_bluetooth_info(),
                    'display':   get_display_and_mobo(),
                    'drives':    list_target_drives(),
                })
            except Exception as exc:
                self.send_json({'error': str(exc)}, 500)
            return

        if self.path == '/api/telemetry':
            try:
                self.send_json({
                    'battery':   get_battery_info(),
                    'thermal':   get_thermal_and_fans(),
                    'wifi':      get_wifi_status(),
                    'storage':   get_storage_info(),
                    'display':   get_display_and_mobo(),
                })
            except Exception as exc:
                self.send_json({'error': str(exc)}, 500)
            return

        if self.path == '/api/all':
            try:
                self.send_json({
                    'system':    get_system_summary(),
                    'battery':   get_battery_info(),
                    'thermal':   get_thermal_and_fans(),
                    'wifi':      get_wifi_status(),
                    'storage':   get_storage_info(),
                    'bluetooth': get_bluetooth_info(),
                    'display':   get_display_and_mobo(),
                    'drives':    list_target_drives(),
                })
            except Exception as exc:
                self.send_json({'error': str(exc)}, 500)
            return

        super().do_GET()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        if self.path == '/api/stress/start':
            try:
                payload = json.loads(body.decode('utf-8')) if body else {}
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
            try:
                payload = json.loads(body.decode('utf-8'))
                vol = payload.get('volume', 80)
                self.send_json(set_system_volume(vol))
            except Exception as exc:
                self.send_json({'success': False, 'message': f'Error: {exc}'}, 400)
            return

        if self.path == '/api/opal-revert':
            try:
                payload = json.loads(body.decode('utf-8'))
                device = payload.get('device', '/dev/nvme0n1')
                psid   = payload.get('psid', '')
                self.send_json(execute_psid_revert(device, psid))
            except Exception as exc:
                self.send_json({'success': False, 'message': f'Error: {exc}'}, 400)
            return

        if self.path == '/api/shutdown':
            self.send_json({'ok': True, 'message': 'Apagando el sistema...'})
            subprocess.Popen(['shutdown', '-h', 'now'])
            return

        if self.path == '/api/reboot':
            self.send_json({'ok': True, 'message': 'Reiniciando el sistema...'})
            subprocess.Popen(['reboot'])
            return

        self.send_response(404)
        self.end_headers()

    def send_json(self, data, code=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Keep backward-compat alias
    send_json_response = send_json


def run_server(port=PORT):
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('0.0.0.0', port), DiagnosticHandler) as httpd:
        print(f'==================================================')
        print(f'DIAGNOSTDONOR: http://localhost:{port}')
        print(f'==================================================')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\nServidor detenido.')


if __name__ == '__main__':
    run_server()
