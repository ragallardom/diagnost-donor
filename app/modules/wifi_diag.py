#!/usr/bin/env python3
"""
Network Diagnostic Module (Wi-Fi & Ethernet)
Scans Wi-Fi networks and checks Ethernet physical port, cable link status and
RJ-45 loopback plugs.

The kiosk never joins a network (firewall drops all non-loopback IP traffic and
NetworkManager has no connection profiles), so these checks only use radio
scans, sysfs link state and raw layer-2 frames; there is no internet test.
"""

import os
import subprocess
import shutil
import socket
import select
import struct
import time

_ETH_LOOPBACK_CACHE = {}


def test_ethernet_loopback(dev, timeout_s=0.12):
    """
    Sends a specialized Ethernet test frame to determine if an RJ-45 loopback
    plug (TX pins 1-2 bridged to RX pins 3-6) is connected, echoing the packet
    directly back to the receiver without external network infrastructure.
    """
    global _ETH_LOOPBACK_CACHE
    if _ETH_LOOPBACK_CACHE.get(dev, {}).get("verified"):
        return True, _ETH_LOOPBACK_CACHE[dev].get("rtt_ms", 0.1)

    if os.geteuid() != 0:
        return False, "not_permitted"

    sock = None
    try:
        # ETH_P_ALL = 0x0003
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
        sock.bind((dev, 0))
        sock.setblocking(False)

        # Flush any pending incoming packets
        while True:
            try:
                sock.recv(2048)
            except Exception:
                break

        mac_bytes = b"\xff\xff\xff\xff\xff\xff"
        try:
            with open(f"/sys/class/net/{dev}/address", "r") as f:
                mac_bytes = bytes.fromhex(f.read().strip().replace(":", ""))
        except Exception:
            pass

        token = f"DONOR_LP_{int(time.time() * 1000)}".encode()
        # EtherType 0x88B5 (IEEE 802 Local Experimental)
        eth_header = mac_bytes + mac_bytes + struct.pack("!H", 0x88B5)
        payload = token + b"\x00" * max(0, 46 - len(token))
        frame = eth_header + payload

        t_start = time.perf_counter()
        sock.send(frame)

        deadline = t_start + timeout_s
        while time.perf_counter() < deadline:
            rem = deadline - time.perf_counter()
            if rem <= 0:
                break
            r, _, _ = select.select([sock], [], [], min(rem, 0.02))
            if r:
                try:
                    data = sock.recv(2048)
                    if token in data:
                        rtt_ms = round((time.perf_counter() - t_start) * 1000, 2)
                        _ETH_LOOPBACK_CACHE[dev] = {"verified": True, "rtt_ms": rtt_ms}
                        return True, rtt_ms
                except Exception:
                    pass

        return False, "no_echo"
    except Exception as e:
        return False, str(e)
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass


def get_ethernet_status():
    global _ETH_LOOPBACK_CACHE
    eth_interfaces = []
    if os.path.exists("/sys/class/net"):
        for dev in sorted(os.listdir("/sys/class/net")):
            if dev == "lo" or dev.startswith(("wl", "docker", "veth", "virbr", "tun", "tap", "br-")):
                continue
            dev_path = f"/sys/class/net/{dev}"
            # Check if wireless
            if os.path.exists(f"{dev_path}/wireless") or os.path.exists(f"{dev_path}/phy80211"):
                continue

            # Bring interface UP so carrier sensing is active
            try:
                subprocess.run(['ip', 'link', 'set', dev, 'up'], capture_output=True, timeout=1)
            except Exception:
                pass

            is_physical = os.path.exists(f"{dev_path}/device")
            carrier_file = f"{dev_path}/carrier"
            speed_file = f"{dev_path}/speed"
            oper_file = f"{dev_path}/operstate"
            addr_file = f"{dev_path}/address"

            carrier = False
            if os.path.exists(carrier_file):
                try:
                    with open(carrier_file, "r") as f:
                        carrier = (f.read().strip() == "1")
                except Exception:
                    carrier = False

            speed = 0
            if os.path.exists(speed_file):
                try:
                    with open(speed_file, "r") as f:
                        s_val = int(f.read().strip())
                        if s_val > 0:
                            speed = s_val
                except Exception:
                    pass

            operstate = "unknown"
            if os.path.exists(oper_file):
                try:
                    with open(oper_file, "r") as f:
                        operstate = f.read().strip()
                except Exception:
                    pass

            mac = ""
            if os.path.exists(addr_file):
                try:
                    with open(addr_file, "r") as f:
                        mac = f.read().strip()
                except Exception:
                    pass

            cable_connected = carrier or operstate == "up"

            # Automatic Loopback Test
            loopback_status = "idle"
            loopback_label = "En espera de cable"
            if cable_connected:
                is_lp, rtt = test_ethernet_loopback(dev)
                if is_lp:
                    loopback_status = "verified"
                    loopback_label = f"Enlace activo ({rtt} ms)"
                elif rtt == "no_echo":
                    loopback_status = "standard_link"
                    loopback_label = "Enlace activo"
                else:
                    loopback_status = "carrier_ok"
                    loopback_label = "Enlace activo"
            else:
                if dev in _ETH_LOOPBACK_CACHE:
                    del _ETH_LOOPBACK_CACHE[dev]

            eth_interfaces.append({
                "interface": dev,
                "is_physical": is_physical,
                "cable_connected": cable_connected,
                "operstate": operstate,
                "speed_mbps": speed,
                "mac": mac,
                "loopback_status": loopback_status,
                "loopback_label": loopback_label
            })

    present = len(eth_interfaces) > 0
    connected = any(i["cable_connected"] for i in eth_interfaces)
    loopback_verified = any(i.get("loopback_status") == "verified" for i in eth_interfaces)

    return {
        "present": present,
        "connected": connected,
        "loopback_verified": loopback_verified,
        "interfaces": eth_interfaces,
        "primary": eth_interfaces[0] if eth_interfaces else None,
        "status_label": "Cable conectado OK" if connected else ("Cable desconectado" if present else "Sin puerto Ethernet integrado")
    }


def get_wifi_status():
    has_nmcli = shutil.which('nmcli') is not None
    wifi_enabled = False
    connected_ssid = None
    signal_quality = 0
    networks = []
    hardware_present = False

    # Check physical Wi-Fi hardware interfaces via sysfs, rfkill, lspci or nmcli
    try:
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
            res = subprocess.run(['nmcli', 'radio', 'wifi'], capture_output=True, text=True, timeout=3)
            wifi_enabled = 'enabled' in res.stdout.lower()

            if not wifi_enabled:
                subprocess.run(['nmcli', 'radio', 'wifi', 'on'], capture_output=True, timeout=3)
                wifi_enabled = True

            res_conn = subprocess.run(['nmcli', '-t', '-f', 'ACTIVE,SSID,SIGNAL,DEVICE', 'dev', 'wifi'], capture_output=True, text=True, timeout=5)
            
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

    return {
        'wifi_hardware_present': hardware_present or len(networks) > 0,
        'wifi_enabled': wifi_enabled,
        'connected_ssid': connected_ssid,
        'signal_quality': signal_quality,
        'networks_count': len(networks),
        'nearby_networks': networks[:10],
        'ethernet': get_ethernet_status()
    }


if __name__ == '__main__':
    import json
    print(json.dumps(get_wifi_status(), indent=2))

