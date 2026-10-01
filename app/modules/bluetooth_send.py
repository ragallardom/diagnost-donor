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
import shutil
import socket
import struct
import subprocess
import tempfile
import time

REPORT_DIR = os.path.join(tempfile.gettempdir(), 'diagnost_reports')
MAC_RE = re.compile(r'^[0-9A-F]{2}(:[0-9A-F]{2}){5}$')
_SAFE_NAME_RE = re.compile(r'^[A-Za-z0-9._-]{1,80}\.(html|pdf)$')
CHROME_CANDIDATES = ('google-chrome', 'google-chrome-stable', '/opt/google/chrome/google-chrome',
                     'chromium-browser', 'chromium')

OBEX = 'org.bluez.obex'
SEND_TIMEOUT_SEC = 60       # the phone shows an "accept file" prompt: give the technician time


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ── Report file ─────────────────────────────────────────────────────────────

def report_filename(serial, now=None, ext='html'):
    """informe_<serial>_<YYYYmmdd-HHMM>.<ext> with a filesystem-safe serial."""
    serial = re.sub(r'[^A-Za-z0-9]+', '', serial or '')[:24] or 'equipo'
    return f"informe_{serial}_{time.strftime('%Y%m%d-%H%M', time.localtime(now))}.{ext}"


def find_chrome():
    override = os.environ.get('DIAG_CHROME')
    if override and os.path.exists(override):
        return override
    for cand in CHROME_CANDIDATES:
        path = shutil.which(cand) or (cand if os.path.isabs(cand) and os.path.exists(cand) else None)
        if path:
            return path
    return None


# Headless Chrome must not touch the network: the kiosk firewall DROPs packets, so proxy auto-detection,
# component updates or sync would stall it for a long time.
_CHROME_OFFLINE_FLAGS = (
    '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
    '--no-proxy-server', '--disable-background-networking', '--disable-component-update',
    '--disable-sync', '--disable-extensions', '--disable-default-apps', '--disable-breakpad',
    '--disable-client-side-phishing-detection', '--no-first-run', '--no-default-browser-check',
    '--metrics-recording-only', '--mute-audio', '--no-pdf-header-footer',
)


def _pdf_is_complete(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(5)
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 1024))
            tail = f.read()
        return head == b'%PDF-' and b'%%EOF' in tail, size
    except OSError:
        return False, 0


def html_to_pdf(html_path, pdf_path, timeout=60):
    """Print an HTML file to PDF with headless Chrome (separate profile: the kiosk Chrome is running).

    Chrome can take long to exit (or hang on shutdown) even after the PDF is written, so the file
    itself is what is waited for: once it is complete and stable the browser is killed.
    """
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError('Chrome no disponible para crear el PDF')
    profile = tempfile.mkdtemp(prefix='diag_pdf_')
    log = tempfile.TemporaryFile()
    proc = subprocess.Popen(
        [chrome, *_CHROME_OFFLINE_FLAGS, f'--user-data-dir={profile}', f'--print-to-pdf={pdf_path}',
         'file://' + html_path],
        stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)
    try:
        deadline = time.monotonic() + timeout
        last_size = -1
        while time.monotonic() < deadline:
            complete, size = _pdf_is_complete(pdf_path)
            if complete and size == last_size:
                return                       # written and no longer growing
            last_size = size if complete else -1
            if proc.poll() is not None:      # Chrome exited: the file is final (or it failed)
                if _pdf_is_complete(pdf_path)[0]:
                    return
                log.seek(0)
                tail = log.read().decode('utf-8', 'replace').strip().splitlines()[-1:] or ['sin salida']
                raise RuntimeError(f'No se pudo crear el PDF ({tail[0][:80]})')
            time.sleep(0.3)
        raise RuntimeError('Tiempo agotado creando el PDF')
    finally:
        try:
            os.killpg(proc.pid, 9)           # the whole Chrome process tree
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        log.close()
        shutil.rmtree(profile, ignore_errors=True)


def save_report(html, serial, fmt='html', max_bytes=200_000):
    if not isinstance(html, str) or not html.strip():
        raise ValueError('Informe vacío')
    data = html.encode('utf-8')
    if len(data) > max_bytes:
        raise ValueError('Informe demasiado grande')
    if fmt not in ('html', 'pdf'):
        raise ValueError('Formato no válido')
    os.makedirs(REPORT_DIR, mode=0o700, exist_ok=True)
    name = report_filename(serial)
    html_path = os.path.join(REPORT_DIR, name)
    with open(html_path, 'wb') as f:
        f.write(data)
    if fmt == 'html':
        return name
    pdf_name = name[:-len('.html')] + '.pdf'
    try:
        html_to_pdf(html_path, os.path.join(REPORT_DIR, pdf_name))
    except RuntimeError as exc:
        raise ValueError(str(exc))
    finally:
        os.unlink(html_path)          # only the chosen format is kept
    return pdf_name


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


def _send_file_call(session, path, wait=8.0):
    """SendFile, retrying while obexd has not exported the ObjectPush1 interface yet."""
    deadline = time.monotonic() + wait
    while True:
        try:
            return _gdbus(['--dest', OBEX, '--object-path', session,
                           '--method', 'org.bluez.obex.ObjectPush1.SendFile', path], 15)
        except RuntimeError as exc:
            missing = 'UnknownObject' in str(exc) or "doesn't exist" in str(exc) or 'UnknownMethod' in str(exc)
            if not missing or time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


def _push(address, path):
    session = _path(_gdbus(['--dest', OBEX, '--object-path', '/org/bluez/obex',
                            '--method', 'org.bluez.obex.Client1.CreateSession', address,
                            "{'Target': <'opp'>}"], 30), '/org/bluez/obex/client/session')
    try:
        out = _send_file_call(session, path)
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


# ── Direct OBEX Object Push over RFCOMM (fallback when the obexd D-Bus client misbehaves) ──

OPP_UUID = 0x1105


def sdp_request(uuid16, cont=b'\x00', tid=1):
    """ServiceSearchAttributeRequest for one UUID16, asking for ProtocolDescriptorList."""
    params = (b'\x35\x03\x19' + struct.pack('>H', uuid16) + b'\x04\x00'
              + b'\x35\x03\x09\x00\x04' + cont)
    return struct.pack('>BHH', 0x06, tid, len(params)) + params


def sdp_parse_response(data):
    """(attribute bytes, continuation state) of a ServiceSearchAttributeResponse."""
    if len(data) < 9 or data[0] != 0x07:
        raise RuntimeError('Respuesta SDP inválida')
    (_tid, plen) = struct.unpack('>HH', data[1:5])
    (count,) = struct.unpack('>H', data[5:7])
    attrs = data[7:7 + count]
    cont = data[7 + count:5 + plen] or b'\x00'
    return attrs, cont


def sdp_rfcomm_channel(attr_bytes):
    """RFCOMM channel from the ProtocolDescriptorList bytes (UUID 0x0003 followed by uint8)."""
    m = re.search(rb'\x19\x00\x03\x08(.)', attr_bytes, re.S)
    return m.group(1)[0] if m else None


def _recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError('El celular cerró la conexión')
        buf += chunk
    return buf


def find_opp_channel(address):
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
    sock.settimeout(10)
    try:
        sock.connect((address, 1))
        cont, attrs, tid = b'\x00', b'', 1
        for _ in range(8):
            sock.send(sdp_request(OPP_UUID, cont, tid))
            part, cont = sdp_parse_response(sock.recv(4096))
            attrs += part
            if cont == b'\x00':
                break
            tid += 1
    finally:
        sock.close()
    channel = sdp_rfcomm_channel(attrs)
    if channel is None:
        raise RuntimeError('El celular no ofrece recepción de archivos por Bluetooth')
    return channel


def _obex_headers(data):
    """{header id: value bytes} from a block of OBEX headers."""
    out, i = {}, 0
    while i < len(data):
        hid, kind = data[i], data[i] & 0xC0
        if kind in (0x00, 0x40):
            (ln,) = struct.unpack('>H', data[i + 1:i + 3])
            out[hid] = data[i + 3:i + ln]
            i += ln
        elif kind == 0x80:
            out[hid] = data[i + 1:i + 2]
            i += 2
        else:
            out[hid] = data[i + 1:i + 5]
            i += 5
    return out


def obex_connect_packet():
    return struct.pack('>BHBBH', 0x80, 7, 0x10, 0x00, 0x2000)


def obex_put_packets(name, data, conn_id=None, max_packet=0x2000):
    """PUT packets for one object: name + length in the first, EndOfBody in the last."""
    head = b''
    if conn_id is not None:
        head += b'\xCB' + conn_id
    uname = name.encode('utf-16-be') + b'\x00\x00'
    head += b'\x01' + struct.pack('>H', len(uname) + 3) + uname
    head += b'\xC3' + struct.pack('>I', len(data))
    limit = min(max_packet, 0x2000)
    packets, first, pos = [], True, 0
    while True:
        hdr = head if first else (b'\xCB' + conn_id if conn_id is not None else b'')
        size = max(64, limit - 3 - len(hdr) - 3)     # packet header + body header overhead
        chunk = data[pos:pos + size]
        pos += len(chunk)
        final = pos >= len(data)
        body = (b'\x49' if final else b'\x48') + struct.pack('>H', len(chunk) + 3) + chunk
        payload = hdr + body
        packets.append((0x82 if final else 0x02, struct.pack('>BH', 0x82 if final else 0x02, len(payload) + 3) + payload))
        first = False
        if final:
            return packets


def _obex_exchange(sock, packet):
    """Send a packet, return (response code, response bytes)."""
    sock.send(packet)
    head = _recv_exact(sock, 3)
    (ln,) = struct.unpack('>H', head[1:3])
    return head[0], head + _recv_exact(sock, ln - 3)


def push_direct(address, path):
    """Send `path` with a hand-made OBEX session over RFCOMM. Raises RuntimeError on failure."""
    channel = find_opp_channel(address)
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.settimeout(SEND_TIMEOUT_SEC)   # the phone waits for the user to tap "accept"
    try:
        sock.connect((address, channel))
        code, resp = _obex_exchange(sock, obex_connect_packet())
        if code != 0xA0:
            raise RuntimeError('El celular rechazó la conexión')
        max_packet = struct.unpack('>H', resp[5:7])[0] if len(resp) >= 7 else 0x2000
        conn_id = _obex_headers(resp[7:]).get(0xCB)
        with open(path, 'rb') as f:
            data = f.read()
        for want, packet in obex_put_packets(os.path.basename(path), data, conn_id, max_packet):
            code, _ = _obex_exchange(sock, packet)
            if code not in (0x90, 0xA0):
                raise RuntimeError('El celular rechazó o canceló el archivo')
        try:
            sock.send(struct.pack('>BH', 0x81, 3))
        except OSError:
            pass
    except socket.timeout:
        raise RuntimeError('Tiempo agotado: acepta el archivo en el celular')
    finally:
        sock.close()


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

    final = ('rechaz', 'Tiempo agotado')    # the phone said no / nobody tapped accept: do not retry
    try:
        try:
            _ensure_obex()
            _push(address, path)
        except RuntimeError as first:
            if any(w in str(first) for w in final):
                raise
            # obexd failed (not paired, interface missing...): pair once and use the direct push.
            _pair(address)
            try:
                push_direct(address, path)
            except (RuntimeError, OSError) as second:
                if any(w in str(second) for w in final):
                    raise
                raise RuntimeError(f'{str(first)[:70]} | {str(second)[:70]}')
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return {'success': False, 'message': str(exc)[:160]}
    return {'success': True, 'message': 'Informe enviado'}
