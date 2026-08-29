#!/usr/bin/env python3
"""
Bluetooth Diagnostic & PSID Wireless Receiver Module
- Reads Controller MAC Address, Radio Power state, and scans for nearby active Bluetooth devices.
- Bluetooth OBEX Receiver for wireless PSID code transfers from Android phones without apps.
"""

import os
import glob
import subprocess
import re
import time
import threading

BT_INBOX_DIR = "/tmp/diagnost_bt_inbox"
_receiver_lock = threading.Lock()
_receiver_thread = None
_receiver_running = False
_obex_proc = None
_latest_psid = None
_latest_timestamp = 0
_latest_source = None

def get_bluetooth_info():
    bt_paths = sorted(glob.glob('/sys/class/bluetooth/hci*'))
    present = len(bt_paths) > 0
    mac_address = "N/A"
    adapter_name = "Adaptador Bluetooth"
    status = "Desactivado o Sin Adaptador"
    is_powered = False

    if present:
        hci_dev = os.path.basename(bt_paths[0])
        adapter_name = hci_dev.upper()
        
        # Read MAC address from sysfs
        addr_file = os.path.join(bt_paths[0], 'address')
        if os.path.exists(addr_file):
            try:
                with open(addr_file, 'r') as f:
                    mac_address = f.read().strip().upper()
            except Exception:
                pass

    # Try bluetoothctl to get power & controller info
    try:
        res = subprocess.run(['bluetoothctl', 'show'], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            stdout = res.stdout
            if 'Powered: yes' in stdout:
                is_powered = True
                present = True
            mac_match = re.search(r'Controller\s+([0-9A-Fa-f:]+)', stdout)
            if mac_match:
                mac_address = mac_match.group(1).upper()
    except Exception:
        pass

    if present:
        status = "Operativo y alimentado" if is_powered else "Adaptador detectado (Apagado)"

    return {
        'present': present,
        'name': adapter_name,
        'mac_address': mac_address,
        'is_powered': is_powered or present,
        'status': status
    }

def extract_psid_from_text(raw_text):
    if not raw_text:
        return ""
    # 1. Strip HTML head, script, style sections
    text = re.sub(r'<head.*?>.*?</head>', '', raw_text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style.*?>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # 2. Strip all HTML/XML tags (e.g. <a href="tel:206">206</a>, <body>, etc.)
    text = re.sub(r'<[^>]+>', '', text)

    # 3. Unescape HTML entities (&nbsp;, &amp;, etc.)
    try:
        import html
        text = html.unescape(text).strip()
    except Exception:
        text = text.strip()

    # 4. Remove common prefix labels
    text = re.sub(r'^(PSID|SERIAL|SN|S/N|KEY|CODIGO|QR)[:=\s]+', '', text, flags=re.IGNORECASE)

    # 5. Check if there is an exact 32-character word in the clean body
    words = re.findall(r'[A-Za-z0-9]{32}', text)
    if words:
        return words[0].upper()

    # 6. Remove remaining delimiters (spaces, hyphens, colons, underscores)
    cleaned = re.sub(r'[^A-Za-z0-9]', '', text).upper()
    if cleaned.startswith('PSID') and len(cleaned) >= 36:
        cleaned = cleaned[4:]
    if len(cleaned) >= 32:
        return cleaned[:32]
    if len(cleaned) >= 16:
        return cleaned
    return cleaned

def _find_obexd_bin():
    paths = [
        "/usr/lib/bluetooth/obexd",
        "/usr/libexec/bluetooth/obexd",
        "/usr/bin/obexd",
        "/usr/local/bin/obexd"
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def _inbox_monitor_loop():
    global _receiver_running, _latest_psid, _latest_timestamp, _latest_source
    os.makedirs(BT_INBOX_DIR, exist_ok=True)

    while _receiver_running:
        try:
            files = glob.glob(os.path.join(BT_INBOX_DIR, "*"))
            for fpath in files:
                if not os.path.isfile(fpath):
                    continue
                try:
                    content = ""
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                    except Exception:
                        with open(fpath, "rb") as f:
                            content = f.read().decode("latin-1", errors="ignore")

                    psid = extract_psid_from_text(content)
                    if psid and len(psid) >= 16:
                        with _receiver_lock:
                            _latest_psid = psid
                            _latest_timestamp = time.time()
                            _latest_source = os.path.basename(fpath)

                    try:
                        os.remove(fpath)
                    except Exception:
                        pass
                except Exception as ex:
                    print(f"Error procesando archivo Bluetooth {fpath}: {ex}")
        except Exception:
            pass

        time.sleep(0.5)

def start_bluetooth_receiver(device_name="DIAGNOST-DONOR"):
    global _receiver_running, _receiver_thread, _obex_proc

    os.makedirs(BT_INBOX_DIR, exist_ok=True)

    try:
        subprocess.run(['rfkill', 'unblock', 'bluetooth'], capture_output=True, timeout=2)
    except Exception:
        pass

    try:
        subprocess.run(['bluetoothctl', 'power', 'on'], capture_output=True, timeout=3)
        subprocess.run(['bluetoothctl', 'system-alias', device_name], capture_output=True, timeout=2)
        subprocess.run(['bluetoothctl', 'discoverable', 'on'], capture_output=True, timeout=2)
        subprocess.run(['bluetoothctl', 'pairable', 'on'], capture_output=True, timeout=2)
        subprocess.run(['bluetoothctl', 'discoverable-timeout', '0'], capture_output=True, timeout=2)
    except Exception as exc:
        print(f"Aviso configurando bluetoothctl: {exc}")

    obexd_bin = _find_obexd_bin()
    if obexd_bin:
        try:
            res = subprocess.run(['pgrep', '-f', 'obexd'], capture_output=True, text=True)
            if res.returncode != 0:
                _obex_proc = subprocess.Popen(
                    [obexd_bin, '-a', '-r', BT_INBOX_DIR, '-n'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        except Exception as exc:
            print(f"Aviso iniciando obexd: {exc}")

    with _receiver_lock:
        if not _receiver_running:
            _receiver_running = True
            _receiver_thread = threading.Thread(target=_inbox_monitor_loop, daemon=True)
            _receiver_thread.start()

    return get_bluetooth_receiver_status()

def stop_bluetooth_receiver():
    global _receiver_running, _obex_proc
    with _receiver_lock:
        _receiver_running = False

    if _obex_proc:
        try:
            _obex_proc.terminate()
        except Exception:
            pass
        _obex_proc = None

    return {"active": False, "message": "Receptor Bluetooth detenido"}

def get_bluetooth_receiver_status():
    global _latest_psid, _latest_timestamp, _latest_source, _receiver_running
    info = get_bluetooth_info()
    return {
        "active": _receiver_running,
        "adapter_present": info.get("present", False),
        "adapter_powered": info.get("is_powered", False),
        "device_name": "DIAGNOST-DONOR",
        "inbox_dir": BT_INBOX_DIR,
        "last_psid": _latest_psid,
        "last_timestamp": _latest_timestamp,
        "last_source": _latest_source
    }

if __name__ == '__main__':
    import json
    print(json.dumps(get_bluetooth_info(), indent=2))

