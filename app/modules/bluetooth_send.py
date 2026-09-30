#!/usr/bin/env python3
"""
Send the QA report to a phone over Bluetooth (OBEX Object Push).

Uses tools already in the image: bluetoothctl to find the phone and the BlueZ obex
service (bluez-obexd, on the D-Bus session bus) through gdbus to push the file.
The phone only has to be visible and tap "Accept"; if it refuses because it is not
paired, one "Just Works" pairing (no code to type) is tried and the send retried.
"""

import glob
import os
import re
import subprocess
import tempfile
import time

REPORT_DIR = os.path.join(tempfile.gettempdir(), 'diagnost_reports')
MAC_RE = re.compile(r'^[0-9A-F]{2}(:[0-9A-F]{2}){5}$')
_SAFE_NAME_RE = re.compile(r'^[A-Za-z0-9._-]{1,80}\.html$')

OBEX = 'org.bluez.obex'
SEND_TIMEOUT_SEC = 60       # the phone shows an "accept file" prompt: give the technician time


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ── Report file ─────────────────────────────────────────────────────────────

def report_filename(serial, now=None):
    """informe_<serial>_<YYYYmmdd-HHMM>.html with a filesystem-safe serial."""
    serial = re.sub(r'[^A-Za-z0-9]+', '', serial or '')[:24] or 'equipo'
    return f"informe_{serial}_{time.strftime('%Y%m%d-%H%M', time.localtime(now))}.html"


def save_report(html, serial, max_bytes=200_000):
    if not isinstance(html, str) or not html.strip():
        raise ValueError('Informe vacío')
    data = html.encode('utf-8')
    if len(data) > max_bytes:
        raise ValueError('Informe demasiado grande')
    os.makedirs(REPORT_DIR, mode=0o700, exist_ok=True)
    name = report_filename(serial)
    with open(os.path.join(REPORT_DIR, name), 'wb') as f:
        f.write(data)
    return name


def resolve_report(name):
    """Full path of a saved report, only for a plain file name inside REPORT_DIR."""
    if not isinstance(name, str) or not _SAFE_NAME_RE.fullmatch(name):
        raise ValueError('Archivo no válido')
    path = os.path.join(REPORT_DIR, name)
    if not os.path.isfile(path):
        raise ValueError('El informe no existe')
    return path


# ── Finding the phone ───────────────────────────────────────────────────────

def parse_devices(output):
    """[(mac, name)] from `bluetoothctl devices` lines ("Device AA:BB:.. Name")."""
    found = []
    for line in output.splitlines():
        m = re.match(r'^\s*Device\s+([0-9A-Fa-f:]{17})\s+(.*)$', line.strip())
        if m:
            found.append((m.group(1).upper(), m.group(2).strip()))
    return found


def parse_info(output):
    info = {}
    for line in output.splitlines():
        if ':' in line:
            key, _, val = line.strip().partition(':')
            info[key.strip()] = val.strip()
    return info


def _looks_unnamed(mac, name):
    return not name or name.replace('-', ':').upper() == mac


def scan_devices(seconds=8):
    """Nearby named devices, phones first, strongest signal first."""
    try:
        _run(['rfkill', 'unblock', 'bluetooth'], 3)
        _run(['bluetoothctl', 'power', 'on'], 5)
        _run(['bluetoothctl', '--timeout', str(int(seconds)), 'scan', 'on'], seconds + 5)
    except Exception:
        pass
    try:
        listing = _run(['bluetoothctl', 'devices'], 5).stdout
    except Exception as exc:
        raise RuntimeError(f'Bluetooth no disponible: {exc}')

    devices = []
    for mac, name in parse_devices(listing):
        if _looks_unnamed(mac, name):
            continue
        try:
            info = parse_info(_run(['bluetoothctl', 'info', mac], 4).stdout)
        except Exception:
            info = {}
        rssi = re.search(r'-?\d+', info.get('RSSI', ''))
        devices.append({
            'address': mac,
            'name': name,
            'phone': info.get('Icon') == 'phone',
            'rssi': int(rssi.group()) if rssi else -127,
        })
    devices.sort(key=lambda d: (not d['phone'], -d['rssi']))
    return devices[:12]


# ── Sending ─────────────────────────────────────────────────────────────────

def _gdbus(args, timeout=10):
    res = _run(['gdbus', 'call', '--session'] + args, timeout)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout or 'gdbus falló').strip().splitlines()[-1])
    return res.stdout


def _path(text, prefix):
    m = re.search(r"'(" + re.escape(prefix) + r"[^']*)'", text)
    if not m:
        raise RuntimeError('Respuesta inesperada de obex')
    return m.group(1)


def _ensure_obex():
    """Start the obex service if nobody owns its name on the session bus."""
    try:
        out = _gdbus(['--dest', 'org.freedesktop.DBus', '--object-path', '/org/freedesktop/DBus',
                      '--method', 'org.freedesktop.DBus.NameHasOwner', OBEX], 5)
        if 'true' in out:
            return
    except Exception:
        pass
    for cand in ('/usr/lib/bluetooth/obexd', '/usr/libexec/bluetooth/obexd', '/usr/bin/obexd'):
        if os.path.exists(cand):
            subprocess.Popen([cand, '-n'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
            return


def _transfer_status(transfer):
    out = _gdbus(['--dest', OBEX, '--object-path', transfer, '--method', 'org.freedesktop.DBus.Properties.Get',
                  'org.bluez.obex.Transfer1', 'Status'], 5)
    m = re.search(r"'(\w+)'", out)
    return m.group(1) if m else ''


def _push(address, path):
    session = _path(_gdbus(['--dest', OBEX, '--object-path', '/org/bluez/obex',
                            '--method', 'org.bluez.obex.Client1.CreateSession', address,
                            "{'Target': <'opp'>}"], 30), '/org/bluez/obex/client/session')
    try:
        out = _gdbus(['--dest', OBEX, '--object-path', session,
                      '--method', 'org.bluez.obex.ObjectPush1.SendFile', path], 15)
        transfer = _path(out, '/org/bluez/obex/client/session')
        deadline = time.monotonic() + SEND_TIMEOUT_SEC
        while time.monotonic() < deadline:
            status = _transfer_status(transfer)
            if status == 'complete':
                return True
            if status == 'error':
                raise RuntimeError('El celular rechazó o canceló el archivo')
            time.sleep(1)
        raise RuntimeError('Tiempo agotado: acepta el archivo en el celular')
    finally:
        try:
            _gdbus(['--dest', OBEX, '--object-path', '/org/bluez/obex',
                    '--method', 'org.bluez.obex.Client1.RemoveSession', session], 5)
        except Exception:
            pass


def _pair(address):
    """One-tap "Just Works" pairing (no PIN comparison), best effort."""
    try:
        _run(['bluetoothctl', '--agent', 'NoInputNoOutput', 'pair', address], 30)
        _run(['bluetoothctl', 'trust', address], 5)
    except Exception:
        pass


def send_report(address, name):
    """Push a saved report to `address`. Returns {'success': bool, 'message': str}."""
    if not isinstance(address, str) or not MAC_RE.fullmatch(address.upper()):
        return {'success': False, 'message': 'Dirección Bluetooth no válida'}
    address = address.upper()
    try:
        path = resolve_report(name)
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}

    try:
        _ensure_obex()
        try:
            _push(address, path)
        except RuntimeError as first:
            # Not paired / connection refused: pair once and retry. A refusal or timeout
            # on the phone is final, retrying would only ask the user again.
            if 'rechaz' in str(first) or 'Tiempo agotado' in str(first):
                raise
            _pair(address)
            _push(address, path)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return {'success': False, 'message': str(exc)[:160]}
    return {'success': True, 'message': 'Informe enviado'}
