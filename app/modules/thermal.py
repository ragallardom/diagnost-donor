#!/usr/bin/env python3
"""
Thermal & Fan Diagnostic Module - Robust Multi-source
Reads CPU temperatures from /sys/class/thermal/thermal_zone*, /sys/class/hwmon,
thinkpad_acpi, hp-wmi, and lm-sensors fallback.

Also reports CPU thermal health (throttling, sustained heat and the cleaning /
thermal paste recommendation) through thermal_health.ThermalMonitor.
Values the hardware does not expose are reported as missing, never invented.
"""

import os
import glob

from thermal_health import ThermalMonitor

_MONITOR = ThermalMonitor()

def get_thermal_and_fans():
    cpu_temps = []
    other_temps = []
    fans = []
    seen_labels = set()

    def get_status_label(temp_c):
        if temp_c < 75.0:
            return 'Normal'
        if temp_c < 92.0:
            return 'Carga / Estable'
        if temp_c < 100.0:
            return 'Caliente (Turbo)'
        return 'Límite Térmico'

    # 1. Read hwmon devices (/sys/class/hwmon/hwmon*) with driver classification
    hwmon_paths = sorted(glob.glob('/sys/class/hwmon/hwmon*'))
    for hwpath in hwmon_paths:
        name_path = os.path.join(hwpath, 'name')
        hw_name = "Hardware"
        if os.path.exists(name_path):
            try:
                with open(name_path, 'r') as f:
                    hw_name = f.read().strip()
            except Exception:
                pass

        hw_lower = hw_name.lower()
        is_cpu = any(k in hw_lower for k in ["coretemp", "k10temp", "zenpower", "cpu_thermal", "soc_dts"])
        is_gpu = any(k in hw_lower for k in ["amdgpu", "nouveau", "nvidia", "i915", "xe"])
        is_ignored = any(k in hw_lower for k in ["bat", "ac0", "ucsi"])

        if is_ignored:
            continue

        # Temperature inputs
        temp_inputs = sorted(glob.glob(os.path.join(hwpath, 'temp*_input')))
        for tinput in temp_inputs:
            label_file = tinput.replace('_input', '_label')
            tname = f"{hw_name} Temp"
            if os.path.exists(label_file):
                try:
                    with open(label_file, 'r') as f:
                        lbl_txt = f.read().strip()
                        tname = f"{hw_name} ({lbl_txt})"
                except Exception:
                    pass

            try:
                with open(tinput, 'r') as f:
                    temp_milli = int(f.read().strip())
                    temp_c = round(temp_milli / 1000.0, 1)
                    if 10.0 <= temp_c <= 120.0 and tname not in seen_labels:
                        seen_labels.add(tname)
                        item = {
                            'label': tname,
                            'temp_c': temp_c,
                            'status': get_status_label(temp_c)
                        }
                        if is_cpu or "Package" in tname or "Tctl" in tname or "Tdie" in tname:
                            cpu_temps.append(item)
                        elif is_gpu or "edge" in tname or "junction" in tname:
                            cpu_temps.append(item)
                        else:
                            other_temps.append(item)
            except Exception:
                pass

        # Fan inputs
        fan_inputs = sorted(glob.glob(os.path.join(hwpath, 'fan*_input')))
        for finput in fan_inputs:
            flabel_file = finput.replace('_input', '_label')
            fname = f"{hw_name} Fan"
            if os.path.exists(flabel_file):
                try:
                    with open(flabel_file, 'r') as f:
                        fname = f"{hw_name} ({f.read().strip()})"
                except Exception:
                    pass
            try:
                with open(finput, 'r') as f:
                    rpm = int(f.read().strip())
                    fans.append({
                        'label': fname,
                        'rpm': rpm,
                        'status': 'Girando OK' if rpm > 0 else 'Inactivo / Detenido'
                    })
            except Exception:
                pass

    # 2. Read thermal zones (/sys/class/thermal/thermal_zone*)
    tz_paths = sorted(glob.glob('/sys/class/thermal/thermal_zone*'))
    for tz in tz_paths:
        type_file = os.path.join(tz, 'type')
        temp_file = os.path.join(tz, 'temp')

        label = "Zona Térmica"
        if os.path.exists(type_file):
            try:
                with open(type_file, 'r') as f:
                    label = f.read().strip()
            except Exception:
                pass

        if any(ign in label.lower() for ign in ["bat", "wifi", "iwlwifi"]):
            continue

        if os.path.exists(temp_file):
            try:
                with open(temp_file, 'r') as f:
                    val_raw = int(f.read().strip())
                    temp_c = round(val_raw / 1000.0, 1) if val_raw > 1000 else float(val_raw)
                    disp_label = f"CPU/Sensor ({label})"
                    if 10.0 <= temp_c <= 120.0 and disp_label not in seen_labels:
                        seen_labels.add(disp_label)
                        item = {
                            'label': disp_label,
                            'temp_c': temp_c,
                            'status': get_status_label(temp_c)
                        }
                        if any(k in label.lower() for k in ["pkg", "cpu", "core", "x86"]):
                            cpu_temps.append(item)
                        else:
                            other_temps.append(item)
            except Exception:
                pass

    # 3. Special check for ThinkPad Fan via thinkpad_acpi /proc/acpi/ibm/fan
    thinkpad_fan = '/proc/acpi/ibm/fan'
    if os.path.exists(thinkpad_fan):
        try:
            with open(thinkpad_fan, 'r') as f:
                for line in f:
                    if 'speed:' in line:
                        rpm = int(line.split(':')[1].strip())
                        if not any('ThinkPad' in fn['label'] for fn in fans):
                            fans.append({
                                'label': 'Lenovo ThinkPad Fan',
                                'rpm': rpm,
                                'status': 'Girando OK' if rpm > 0 else 'Inactivo'
                            })
        except Exception:
            pass

    all_temperatures = cpu_temps + other_temps

    return {
        'temperatures': all_temperatures[:6],  # Top 6 prioritized sensors
        # Empty when the BIOS/EC does not expose fan RPM (the UI says so).
        'fans': fans,
        'health': _MONITOR.sample(),
    }


def read_fan_rpms():
    """Fan RPM readings, or None when no fan sensor is exposed. Stateless."""
    rpms = []
    for finput in glob.glob('/sys/class/hwmon/hwmon*/fan*_input'):
        try:
            with open(finput, 'r') as f:
                rpms.append(int(f.read().strip()))
        except Exception:
            pass
    try:
        with open('/proc/acpi/ibm/fan', 'r') as f:
            for line in f:
                if line.startswith('speed:'):
                    rpms.append(int(line.split(':')[1].strip()))
    except Exception:
        pass
    return rpms or None

if __name__ == '__main__':
    import json
    print(json.dumps(get_thermal_and_fans(), indent=2))
