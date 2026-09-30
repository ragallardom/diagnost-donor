#!/usr/bin/env python3
"""
Battery Diagnostic Module
Detects Battery Health, Cycle Count, Charger Connection, and Charging Errors
(e.g., Charger connected but battery NOT charging / Faulty Charge Port / Defective Cell).
"""

import os
import glob
import subprocess
import time

# Module-level state tracking for AC connection debounce & energy flow
_AC_TRACKER = {
    'last_ac_online': False,
    'ac_connect_time': 0.0,
}

def get_sysfs_value(filepath, default=None, is_int=False):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                val = f.read().strip()
                return int(val) if is_int else val
    except Exception:
        pass
    return default

# The 1 s telemetry poll must not spawn `upower` every time: cycles and thresholds
# barely change and the charging state is also read from sysfs.
UPOWER_TTL_SEC = 5.0
_UPOWER_CACHE = {}


def get_upower_info(bat_name):
    hit = _UPOWER_CACHE.get(bat_name)
    now = time.monotonic()
    if hit and now - hit[0] < UPOWER_TTL_SEC:
        return hit[1]
    value = _query_upower(bat_name)
    _UPOWER_CACHE[bat_name] = (now, value)
    return value


def _query_upower(bat_name):
    cycles = None
    upower_status = None
    end_threshold = None
    try:
        dev_path = f'/org/freedesktop/UPower/devices/battery_{bat_name}'
        res = subprocess.run(['upower', '-i', dev_path], capture_output=True, text=True, timeout=2)
        if res.returncode != 0:
            # Enumerate upower devices if exact name didn't match
            enum_res = subprocess.run(['upower', '-e'], capture_output=True, text=True, timeout=2)
            if enum_res.returncode == 0:
                for d in enum_res.stdout.splitlines():
                    if 'battery' in d.lower() and (bat_name.lower() in d.lower() or not dev_path):
                        dev_path = d.strip()
                        break
                res = subprocess.run(['upower', '-i', dev_path], capture_output=True, text=True, timeout=2)

        if res.returncode == 0:
            for line in res.stdout.split('\n'):
                line_str = line.strip()
                if 'cycle-count:' in line_str:
                    try:
                        cycles = int(line_str.split(':')[1].strip())
                    except ValueError:
                        pass
                elif 'state:' in line_str:
                    upower_status = line_str.split(':')[1].strip().lower()
                elif 'charge-end-threshold:' in line_str:
                    try:
                        val = line_str.split(':')[1].strip().replace('%', '').strip()
                        end_threshold = int(val)
                    except ValueError:
                        pass
    except Exception:
        pass
    return cycles, upower_status, end_threshold

def is_ac_online_sysfs():
    """Detect if any AC / Mains / USB-C charger is connected via sysfs."""
    # 1. Standard AC/ADP paths
    for p in glob.glob('/sys/class/power_supply/AC*') + glob.glob('/sys/class/power_supply/ADP*'):
        if get_sysfs_value(os.path.join(p, 'online'), 0, is_int=True) == 1:
            return True

    # 2. Check all other non-battery power supplies (USB-C PD, Mains, etc.)
    for ps in glob.glob('/sys/class/power_supply/*'):
        ps_type = str(get_sysfs_value(os.path.join(ps, 'type'), '')).lower()
        if ps_type not in ['battery', '']:
            if get_sysfs_value(os.path.join(ps, 'online'), 0, is_int=True) == 1:
                return True

    return False

def get_battery_info():
    global _AC_TRACKER
    batteries = []
    bat_paths = sorted(glob.glob('/sys/class/power_supply/BAT*'))
    
    if not bat_paths:
        bat_paths = sorted(glob.glob('/sys/class/power_supply/*'))
        bat_paths = [p for p in bat_paths if 'BAT' in p.upper() or 'battery' in p.lower()]

    ac_online = is_ac_online_sysfs()
    now = time.time()

    # AC connection debounce / duration tracking
    if ac_online:
        if not _AC_TRACKER['last_ac_online']:
            _AC_TRACKER['last_ac_online'] = True
            _AC_TRACKER['ac_connect_time'] = now
        ac_duration = now - _AC_TRACKER['ac_connect_time']
    else:
        _AC_TRACKER['last_ac_online'] = False
        _AC_TRACKER['ac_connect_time'] = 0.0
        ac_duration = 0.0

    for bat_path in bat_paths:
        name = os.path.basename(bat_path)
        sysfs_status = str(get_sysfs_value(os.path.join(bat_path, 'status'), 'Unknown'))
        capacity = get_sysfs_value(os.path.join(bat_path, 'capacity'), 0, is_int=True)
        capacity_level = str(get_sysfs_value(os.path.join(bat_path, 'capacity_level'), '')).lower()

        # Read charge control threshold from sysfs if present
        sysfs_end_threshold = get_sysfs_value(os.path.join(bat_path, 'charge_control_end_threshold'), None, is_int=True)

        up_cycles, up_status, up_threshold = get_upower_info(name)

        end_threshold = sysfs_end_threshold if sysfs_end_threshold is not None else up_threshold
        # If sysfs threshold is 100 but upower reported e.g. 80, prefer the restricted threshold (< 100)
        if sysfs_end_threshold == 100 and up_threshold and up_threshold < 100:
            end_threshold = up_threshold

        status = sysfs_status
        status_lower = status.lower()
        up_status_lower = (up_status or '').lower()

        # If either sysfs or upower reports charging, it is definitely charging!
        is_charging = (status_lower in ['charging', 'cargando']) or (up_status_lower in ['charging', 'cargando'])
        if is_charging:
            ac_online = True  # Battery cannot charge without AC power
            status = 'Charging'
            status_lower = 'charging'

        # DETECT CHARGE MODES & ANOMALIES (False-Positive Prevention)
        has_charge_error = False
        error_msg = ""
        is_full = False
        is_conservation = False

        # 1. Full Battery check
        # Laptops stop charging when >= 95% (or >= 90% in 'Not charging' / 'Full' state)
        if capacity >= 95 or capacity_level == 'full' or status_lower in ['full', 'completa'] or up_status_lower == 'fully-charged':
            is_full = True
        elif capacity >= 90 and (status_lower in ['not charging', 'idle'] or up_status_lower in ['not-charging', 'idle']):
            is_full = True

        # 2. Conservation / Threshold check
        # When battery conservation mode (e.g. 60%, 80%) is enabled in BIOS/software
        if end_threshold and end_threshold < 100 and capacity >= (end_threshold - 3):
            is_conservation = True

        # 3. Determine status_es and errors (clean status without redundant percentage)
        if is_charging:
            status_es = "Cargando"
        elif is_full:
            if ac_online:
                status_es = "Carga Completa"
            else:
                status_es = "Batería Completa"
        elif is_conservation:
            status_es = "Cargador Conectado / Umbral Activo"
        elif ac_online:
            # AC is plugged in, not charging yet, not full, not in conservation
            if up_status_lower == 'pending-charge' or ac_duration < 10.0:
                # Negotiation / handshake grace period (first 10 seconds of plugging in)
                status_es = "Cargador Conectado (Iniciando carga...)"
            elif capacity < 90 and (status_lower in ['not charging', 'discharging'] or up_status_lower in ['not-charging', 'discharging']):
                # Sustained non-charging state after 10+ seconds
                has_charge_error = True
                error_msg = "CARGADOR CONECTADO PERO SIN CARGA (Posible fallo de puerto, cargador insuficiente o umbral BIOS)"
                status_es = "Conectado / Batería No Carga"
            else:
                status_es = "Cargador Conectado"
        else:
            # On battery power
            if status_lower in ['discharging', 'descargando'] or up_status_lower == 'discharging':
                status_es = "Descargando"
            else:
                status_es = "Uso de Batería"

        # Energy / Charge readings (in uWh or uAh)
        energy_full_design = (
            get_sysfs_value(os.path.join(bat_path, 'energy_full_design'), None, is_int=True) or
            get_sysfs_value(os.path.join(bat_path, 'charge_full_design'), None, is_int=True)
        )
        energy_full = (
            get_sysfs_value(os.path.join(bat_path, 'energy_full'), None, is_int=True) or
            get_sysfs_value(os.path.join(bat_path, 'charge_full'), None, is_int=True)
        )
        energy_now = (
            get_sysfs_value(os.path.join(bat_path, 'energy_now'), None, is_int=True) or
            get_sysfs_value(os.path.join(bat_path, 'charge_now'), None, is_int=True)
        )
        voltage_now = get_sysfs_value(os.path.join(bat_path, 'voltage_now'), 0, is_int=True) # uV
        cycle_count = get_sysfs_value(os.path.join(bat_path, 'cycle_count'), None, is_int=True)
        
        if (cycle_count is None or cycle_count == 0) and up_cycles:
            cycle_count = up_cycles

        technology = get_sysfs_value(os.path.join(bat_path, 'technology'), 'Li-ion')
        model_name = get_sysfs_value(os.path.join(bat_path, 'model_name'), 'Standard Battery')
        manufacturer = get_sysfs_value(os.path.join(bat_path, 'manufacturer'), 'OEM')

        # None (not 100) when the battery does not report both capacities: never invent a health value.
        health_percent = None
        if energy_full_design and energy_full and energy_full_design > 0:
            health_percent = round((energy_full / energy_full_design) * 100.0, 1)

        design_wh = round(energy_full_design / 1000000.0, 2) if energy_full_design else 0.0
        full_wh = round(energy_full / 1000000.0, 2) if energy_full else 0.0
        now_wh = round(energy_now / 1000000.0, 2) if energy_now else 0.0
        voltage_v = round(voltage_now / 1000000.0, 2) if voltage_now else 0.0

        batteries.append({
            'name': name,
            'status': status,
            'status_es': status_es,
            'ac_online': ac_online,
            'has_charge_error': has_charge_error,
            'error_msg': error_msg,
            'is_charging': is_charging,
            'is_full': is_full,
            'is_conservation': is_conservation,
            'charge_threshold': end_threshold,
            'capacity_percent': capacity,
            'health_percent': health_percent,
            'design_wh': design_wh,
            'full_wh': full_wh,
            'current_wh': now_wh,
            'voltage_v': voltage_v,
            'cycle_count': cycle_count if (cycle_count is not None and cycle_count > 0) else 'N/A',
            'technology': technology,
            'model_name': model_name,
            'manufacturer': manufacturer,
            'present': True
        })

    if not batteries:
        batteries.append({
            'name': 'BAT0',
            'status': 'AC Power',
            'status_es': 'Corriente Directa (Sin Bateria)',
            'ac_online': ac_online,
            'has_charge_error': False,
            'error_msg': '',
            'is_charging': False,
            'is_full': True,
            'is_conservation': False,
            'charge_threshold': None,
            'capacity_percent': 100,
            'health_percent': None,
            'design_wh': 0.0,
            'full_wh': 0.0,
            'current_wh': 0.0,
            'voltage_v': 0.0,
            'cycle_count': 'N/A',
            'technology': 'N/A',
            'model_name': 'AC Power',
            'manufacturer': 'AC',
            'present': False
        })

    return batteries

if __name__ == '__main__':
    import json
    print(json.dumps(get_battery_info(), indent=2))
