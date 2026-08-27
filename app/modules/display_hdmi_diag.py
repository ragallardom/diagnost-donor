#!/usr/bin/env python3
"""
Motherboard & HDMI Display Port Diagnostic Module
Checks Motherboard BIOS details and strictly external HDMI / DisplayPort connection.
Explicitly filters out internal laptop screens (eDP-1, LVDS-1, DSI-1).
Supports multi-strategy detection (sysfs status, EDID binary read, modes, xrandr).
"""

import os
import glob
import subprocess

_CACHED_MOBO = None
_CACHED_BIOS = None

def read_dmi(field):
    path = os.path.join('/sys/class/dmi/id', field)
    if os.path.exists(path):
        try:
            with open(path, 'r', errors='ignore') as f:
                return f.read().strip()
        except Exception:
            pass
    return 'N/A'

def _get_friendly_port_name(port_name):
    p = port_name
    if p.startswith('HDMI-A-'):
        return 'HDMI-' + p.replace('HDMI-A-', '')
    if p.startswith('HDMI-B-'):
        return 'HDMI-' + p.replace('HDMI-B-', '')
    if p.startswith('DP-'):
        return 'DisplayPort / HDMI (' + p + ')'
    if p.startswith('DisplayPort-'):
        return p
    if p.startswith('DVI-I-') or p.startswith('DVI-D-'):
        return 'DVI-' + p.split('-', 2)[-1]
    return p

def get_display_and_mobo():
    global _CACHED_MOBO, _CACHED_BIOS
    if _CACHED_MOBO is None:
        mobo_vendor = read_dmi('board_vendor') or read_dmi('sys_vendor')
        mobo_name = read_dmi('board_name') or read_dmi('product_name')
        _CACHED_MOBO = f"{mobo_vendor} {mobo_name}".strip()

    if _CACHED_BIOS is None:
        bios_version = read_dmi('bios_version')
        bios_date = read_dmi('bios_date')
        _CACHED_BIOS = f"{bios_version} ({bios_date})" if bios_date != 'N/A' else bios_version

    external_hdmi_connected = False
    connected_external_port = None
    displays_status = []

    # 1. Fast sysfs scan across all DRM cards and connectors (<0.5ms)
    drm_paths = sorted(glob.glob('/sys/class/drm/card*-*'))
    for drm in drm_paths:
        port_name = os.path.basename(drm).split('-', 1)[-1]
        
        # EXCLUDE INTERNAL LAPTOP SCREENS (eDP, LVDS, DSI, Panel, Writeback)
        if any(internal in port_name.upper() for internal in ['EDP', 'LVDS', 'DSI', 'PANEL', 'WRITEBACK']):
            continue

        is_conn = False

        # Strategy 1: sysfs status file
        status_file = os.path.join(drm, 'status')
        if os.path.exists(status_file):
            try:
                with open(status_file, 'r', errors='ignore') as f:
                    if f.read().strip().lower() == 'connected':
                        is_conn = True
            except Exception:
                pass

        # Strategy 2: EDID binary probe (forces hardware DDC read)
        if not is_conn:
            edid_file = os.path.join(drm, 'edid')
            if os.path.exists(edid_file):
                try:
                    with open(edid_file, 'rb') as ef:
                        edid_data = ef.read()
                        if len(edid_data) >= 128 and any(b != 0 for b in edid_data):
                            is_conn = True
                except Exception:
                    pass

        # Strategy 3: Modes file presence
        if not is_conn:
            modes_file = os.path.join(drm, 'modes')
            if os.path.exists(modes_file):
                try:
                    with open(modes_file, 'r', errors='ignore') as mf:
                        if mf.read().strip():
                            is_conn = True
                except Exception:
                    pass

        # Strategy 4: sysfs enabled file
        if not is_conn:
            enabled_file = os.path.join(drm, 'enabled')
            if os.path.exists(enabled_file):
                try:
                    with open(enabled_file, 'r', errors='ignore') as ef:
                        if ef.read().strip().lower() == 'enabled':
                            is_conn = True
                except Exception:
                    pass

        friendly_name = _get_friendly_port_name(port_name)

        displays_status.append({
            'port': friendly_name,
            'raw_port': port_name,
            'connected': is_conn
        })

        if is_conn:
            external_hdmi_connected = True
            if not connected_external_port:
                connected_external_port = friendly_name

    # 2. X11 xrandr hardware query (forces KMS driver to probe LSPCON / DP PHY)
    x_env = os.environ.copy()
    if 'DISPLAY' not in x_env or not x_env['DISPLAY']:
        x_env['DISPLAY'] = ':0'
    if 'XAUTHORITY' not in x_env or not x_env['XAUTHORITY']:
        x_env['XAUTHORITY'] = '/root/.Xauthority'

    try:
        res = subprocess.run(['xrandr', '-q'], capture_output=True, text=True, timeout=1.5, env=x_env)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if ' connected' in line and not ' disconnected' in line:
                    tokens = line.split()
                    if len(tokens) >= 2:
                        pname = tokens[0]
                        if not any(x in pname.upper() for x in ['EDP', 'LVDS', 'DSI', 'PANEL', 'WRITEBACK']):
                            external_hdmi_connected = True
                            friendly_name = _get_friendly_port_name(pname)
                            if not connected_external_port:
                                connected_external_port = friendly_name
                            
                            # Update or add to displays_status list
                            existing = next((d for d in displays_status if d['raw_port'] == pname), None)
                            if existing:
                                existing['connected'] = True
                            else:
                                displays_status.append({
                                    'port': friendly_name,
                                    'raw_port': pname,
                                    'connected': True
                                })
    except Exception:
        pass

    return {
        'motherboard': _CACHED_MOBO,
        'bios_version': _CACHED_BIOS,
        'hdmi_connected': external_hdmi_connected,
        'hdmi_port': connected_external_port or "HDMI-1 / DisplayPort",
        'external_displays': displays_status
    }

if __name__ == '__main__':
    import json
    print(json.dumps(get_display_and_mobo(), indent=2))
