#!/usr/bin/env python3
"""
System Info Diagnostic Module
Extracts Laptop Vendor, Model, Serial Number, CPU details (with Cores/Architecture), RAM, and TPM 2.0 Status.
Reads directly from /sys/class/dmi/id/ and /proc/cpuinfo to work reliably without root.
"""

import os
import glob
import platform
import subprocess

def read_dmi_field(filename):
    path = os.path.join('/sys/class/dmi/id', filename)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return f.read().strip()
        except Exception:
            pass
    return None

def check_tpm_status():
    tpm_paths = sorted(glob.glob('/sys/class/tpm/tpm*'))
    if not tpm_paths:
        if os.path.exists('/dev/tpm0') or os.path.exists('/dev/tpmrm0'):
            return {
                'present': True,
                'version': 'TPM 2.0 (Activo por Kernel /dev/tpm0)',
                'is_tpm2': True,
                'status': 'OK'
            }
        return {
            'present': False,
            'version': 'Desactivado o Ausente en BIOS',
            'is_tpm2': False,
            'status': 'Error'
        }

    for path in tpm_paths:
        ver_file = os.path.join(path, 'tpm_version_major')
        if os.path.exists(ver_file):
            try:
                with open(ver_file, 'r') as f:
                    major = f.read().strip()
                    if major == '2':
                        return {
                            'present': True,
                            'version': 'TPM 2.0 Activado (OK)',
                            'is_tpm2': True,
                            'status': 'OK'
                        }
                    elif major == '1':
                        return {
                            'present': True,
                            'version': 'TPM 1.2 (Versión Antigua)',
                            'is_tpm2': False,
                            'status': 'Warning'
                        }
            except Exception:
                pass

    if os.path.exists('/dev/tpm0'):
        return {
            'present': True,
            'version': 'TPM 2.0 (Detectado)',
            'is_tpm2': True,
            'status': 'OK'
        }

    return {
        'present': False,
        'version': 'Desactivado en BIOS',
        'is_tpm2': False,
        'status': 'Error'
    }

def get_cpu_and_arch():
    model_name = "CPU Intel / AMD"
    cores = os.cpu_count() or 4
    arch_machine = platform.machine() or "x86_64"

    # Precise architecture description
    if arch_machine in ['x86_64', 'AMD64']:
        arch_desc = f"x86_64 (64-bits) - {cores} Hilos/Núcleos"
    elif arch_machine in ['aarch64', 'arm64']:
        arch_desc = f"ARM64 (64-bits) - {cores} Cores"
    else:
        arch_desc = f"{arch_machine} (32-bits) - {cores} Cores"

    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if 'model name' in line:
                    model_name = line.split(':')[1].strip()
                    break
    except Exception:
        pass

    return model_name, arch_desc

def get_ram_info():
    try:
        with open('/proc/meminfo', 'r') as f:
            lines = f.readlines()
            total_kb = 0
            avail_kb = 0
            for line in lines:
                if 'MemTotal:' in line:
                    total_kb = int(line.split()[1])
                elif 'MemAvailable:' in line:
                    avail_kb = int(line.split()[1])
            total_gb = round(total_kb / (1024 * 1024), 2)
            avail_gb = round(avail_kb / (1024 * 1024), 2)
            used_gb = round(total_gb - avail_gb, 2)
            return {
                'total_gb': total_gb,
                'used_gb': used_gb,
                'avail_gb': avail_gb,
                'percent_used': round((used_gb / total_gb) * 100, 1) if total_gb > 0 else 0
            }
    except Exception:
        pass
    return {'total_gb': 0, 'used_gb': 0, 'avail_gb': 0, 'percent_used': 0}

def get_system_summary():
    import re
    vendor = (read_dmi_field('sys_vendor') or read_dmi_field('board_vendor') or 'Generico').strip()
    model = (read_dmi_field('product_name') or read_dmi_field('product_family') or read_dmi_field('board_name') or 'Laptop / PC').strip()
    version = (read_dmi_field('product_version') or '').strip()
    serial = read_dmi_field('product_serial') or 'N/A'
    
    # Prevent duplicating vendor if model already starts with vendor name (e.g. "HP" and "HP EliteBook...")
    v_first = vendor.split()[0] if vendor else ""
    if v_first and model.lower().startswith(v_first.lower()):
        full_model_str = model
    else:
        full_model_str = f"{vendor} {model}".strip()

    # Deduplicate repeated brand names if any (e.g. "HP HP ...")
    full_model_str = re.sub(r'\b(HP|LENOVO|DELL|ASUS|ACER)\s+\1\b', r'\1', full_model_str, flags=re.IGNORECASE)

    # Keep part number / SKU version in parentheses for technical card reference (e.g. "(SBKPFV3)")
    if version and version.lower() not in full_model_str.lower():
        if not re.match(r'^(None|Default string|To be filled by O\.E\.M\.|System Version)$', version, re.IGNORECASE):
            full_model_str = f"{full_model_str} ({version})"

    cpu_model, cpu_arch = get_cpu_and_arch()

    return {
        'model': full_model_str,
        'vendor': vendor,
        'serial': serial,
        'cpu': cpu_model,
        'architecture': cpu_arch,
        'ram': get_ram_info(),
        'tpm': check_tpm_status(),
        'os': f"{platform.system()} {platform.release()}"
    }

if __name__ == '__main__':
    import json
    print(json.dumps(get_system_summary(), indent=2))
