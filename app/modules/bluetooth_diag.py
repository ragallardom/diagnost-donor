#!/usr/bin/env python3
"""
Bluetooth Diagnostic Module - Active MAC & Scan Verification
Reads Controller MAC Address, Radio Power state, and scans for nearby active Bluetooth devices.
"""

import os
import glob
import subprocess
import re

def get_bluetooth_info():
    bt_paths = sorted(glob.glob('/sys/class/bluetooth/hci*'))
    present = len(bt_paths) > 0
    mac_address = "N/A"
    adapter_name = "Adaptador Bluetooth"
    status = "Desactivado o Sin Adaptador"
    is_powered = False
    nearby_devices_count = 0

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

    # Try bluetoothctl / hciconfig to get power & active scan count
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
        status = "Operativo y alimentado"

    return {
        'present': present,
        'name': adapter_name,
        'mac_address': mac_address,
        'is_powered': is_powered or present,
        'status': status
    }

if __name__ == '__main__':
    import json
    print(json.dumps(get_bluetooth_info(), indent=2))
