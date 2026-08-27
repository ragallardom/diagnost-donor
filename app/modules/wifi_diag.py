#!/usr/bin/env python3
"""
Wi-Fi Diagnostic Module
Scans Wi-Fi networks, checks Wi-Fi hardware adapter status, and test network latency (ping).
Uses nmcli (NetworkManager) or wireless sysfs interfaces.
"""

import subprocess
import shutil
import re

def get_wifi_status():
    has_nmcli = shutil.which('nmcli') is not None
    wifi_enabled = False
    connected_ssid = None
    signal_quality = 0
    networks = []
    hardware_present = False

    # Check physical Wi-Fi hardware interfaces via sysfs, rfkill, lspci or nmcli
    try:
        import os
        if os.path.exists('/sys/class/net'):
            net_devs = os.listdir('/sys/class/net')
            for d in net_devs:
                if d.startswith('wl') or 'wifi' in d or 'wlan' in d:
                    hardware_present = True
                    break
                if os.path.exists(f'/sys/class/net/{d}/wireless') or os.path.exists(f'/sys/class/net/{d}/phy80211'):
                    hardware_present = True
                    break
        if not hardware_present and os.path.exists('/sys/class/rfkill'):
            rf_devs = os.listdir('/sys/class/rfkill')
            for r in rf_devs:
                try:
                    with open(f'/sys/class/rfkill/{r}/type', 'r') as f:
                        if 'wlan' in f.read().lower():
                            hardware_present = True
                            break
                except Exception:
                    pass
        if not hardware_present:
            # Check lspci / lsusb for Wi-Fi hardware controller presence
            try:
                pci_res = subprocess.run(['lspci'], capture_output=True, text=True, timeout=1)
                if pci_res.returncode == 0 and any(w in pci_res.stdout.lower() for w in ['network controller', 'wireless', 'wi-fi', 'be200', 'ax211', 'ath12k', 'mt7921', 'mt7922', 'mt7925', 'rtw89']):
                    hardware_present = True
            except Exception:
                pass
    except Exception:
        hardware_present = False

    if has_nmcli:
        try:
            # Check wifi radio status
            res = subprocess.run(['nmcli', 'radio', 'wifi'], capture_output=True, text=True, timeout=3)
            wifi_enabled = 'enabled' in res.stdout.lower()

            if not wifi_enabled:
                subprocess.run(['nmcli', 'radio', 'wifi', 'on'], capture_output=True, timeout=3)
                wifi_enabled = True

            # Query available networks
            res_conn = subprocess.run(['nmcli', '-t', '-f', 'ACTIVE,SSID,SIGNAL,DEVICE', 'dev', 'wifi'], capture_output=True, text=True, timeout=5)
            
            # If no networks were returned, trigger an explicit rescan and try once more
            if res_conn.returncode != 0 or not res_conn.stdout.strip():
                subprocess.run(['nmcli', 'dev', 'wifi', 'rescan'], capture_output=True, timeout=5)
                res_conn = subprocess.run(['nmcli', '-t', '-f', 'ACTIVE,SSID,SIGNAL,DEVICE', 'dev', 'wifi'], capture_output=True, text=True, timeout=5)

            if res_conn.returncode == 0:
                lines = res_conn.stdout.strip().split('\n')
                seen_ssids = set()
                for line in lines:
                    if not line:
                        continue
                    parts = line.split(':')
                    if len(parts) >= 3:
                        is_active = parts[0].lower() == 'yes'
                        ssid = parts[1]
                        try:
                            signal = int(parts[2])
                        except ValueError:
                            signal = 0

                        if ssid and ssid not in seen_ssids:
                            seen_ssids.add(ssid)
                            networks.append({
                                'ssid': ssid,
                                'signal': signal,
                                'connected': is_active
                            })
                            if is_active:
                                connected_ssid = ssid
                                signal_quality = signal
        except Exception:
            pass

    # Quick ping test
    ping_ok = False
    ping_ms = 0.0
    try:
        ping_res = subprocess.run(['ping', '-c', '1', '-W', '2', '1.1.1.1'], capture_output=True, text=True, timeout=3)
        if ping_res.returncode == 0:
            ping_ok = True
            match = re.search(r'time=([\d.]+)\s*ms', ping_res.stdout)
            if match:
                ping_ms = float(match.group(1))
    except Exception:
        pass

    return {
        'wifi_hardware_present': hardware_present or len(networks) > 0,
        'wifi_enabled': wifi_enabled,
        'connected_ssid': connected_ssid,
        'signal_quality': signal_quality,
        'internet_ping_ok': ping_ok,
        'ping_ms': ping_ms,
        'networks_count': len(networks),
        'nearby_networks': networks[:10] # Top 10 SSIDs
    }

if __name__ == '__main__':
    import json
    print(json.dumps(get_wifi_status(), indent=2))
