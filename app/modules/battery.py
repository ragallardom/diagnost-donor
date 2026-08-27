#!/usr/bin/env python3
"""
Battery Diagnostic Module
Detects Battery Health, Cycle Count, Charger Connection, and Charging Errors
(e.g., Charger connected but battery NOT charging / Faulty Charge Port / Defective Cell).
"""

import os
import glob
import subprocess

def get_sysfs_value(filepath, default=None, is_int=False):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                val = f.read().strip()
                return int(val) if is_int else val
    except Exception:
        pass
    return default

def get_upower_cycle_and_status(bat_name):
    cycles = None
    upower_status = None
    try:
        res = subprocess.run(['upower', '-i', f'/org/freedesktop/UPower/devices/battery_{bat_name}'], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            for line in res.stdout.split('\n'):
                if 'cycle-count:' in line:
                    try:
                        cycles = int(line.split(':')[1].strip())
                    except ValueError:
                        pass
                elif 'state:' in line:
                    upower_status = line.split(':')[1].strip()
    except Exception:
        pass
    return cycles, upower_status

def get_battery_info():
    batteries = []
    bat_paths = sorted(glob.glob('/sys/class/power_supply/BAT*'))
    
    if not bat_paths:
        bat_paths = sorted(glob.glob('/sys/class/power_supply/*'))
        bat_paths = [p for p in bat_paths if 'BAT' in p.upper() or 'battery' in p.lower()]

    ac_paths = sorted(glob.glob('/sys/class/power_supply/AC*') + glob.glob('/sys/class/power_supply/ADP*'))
    ac_online = False
    for ac in ac_paths:
        if get_sysfs_value(os.path.join(ac, 'online'), 0, is_int=True) == 1:
            ac_online = True

    for bat_path in bat_paths:
        name = os.path.basename(bat_path)
        sysfs_status = get_sysfs_value(os.path.join(bat_path, 'status'), 'Unknown')
        capacity = get_sysfs_value(os.path.join(bat_path, 'capacity'), 0, is_int=True)
        
        up_cycles, up_status = get_upower_cycle_and_status(name)

        status = sysfs_status
        if status == 'Unknown' and up_status:
            status = up_status.capitalize()

        # DETECT CHARGER / BATTERY ANOMALIES & CHARGE PORT ERRORS
        has_charge_error = False
        error_msg = ""
        status_es = "Descargando"

        status_lower = status.lower()
        if status_lower in ['charging', 'cargando']:
            status_es = "Cargando"
        elif status_lower in ['full', 'completa']:
            status_es = "Carga Completa (100%)"
        elif status_lower == 'not charging':
            has_charge_error = True
            error_msg = "CARGADOR CONECTADO PERO BATERIA NO CARGA (Posible fallo de puerto, cargador o umbral BIOS)"
            status_es = "NO CARGANDO (Cargador Conectado)"
        elif ac_online and capacity < 95 and status_lower != 'charging':
            has_charge_error = True
            error_msg = "ALERTA: Cargador detectado en puerto pero la bateria no recibe carga."
            status_es = "Puerto AC Conectado / Sin Carga"
        elif ac_online:
            status_es = "Cargador Conectado"

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

        health_percent = 100.0
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
            'capacity_percent': 100,
            'health_percent': 100.0,
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
