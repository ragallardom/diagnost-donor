#!/usr/bin/env python3
"""
System Info Diagnostic Module
Extracts Laptop Vendor, Model, Serial Number, CPU details (with Cores/Architecture), RAM, and TPM 2.0 Status.
Reads directly from /sys/class/dmi/id/ and /proc/cpuinfo to work reliably without root.
"""

import os
import re
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

# Values firmware vendors leave in DMI when nobody filled the field in.
_DMI_PLACEHOLDERS = {
    '', 'none', 'n/a', 'default string', 'system serial number', 'system product name',
    'to be filled by o.e.m.', 'to be filled by oem', 'not specified', 'not applicable',
    'chassis serial number', 'base board serial number', '0', '123456789', '0123456789',
    'unknown', 'o.e.m.', 'oem',
}


def clean_dmi_value(value):
    """None for empty / placeholder DMI strings, otherwise the stripped value."""
    if value is None:
        return None
    value = value.strip()
    return None if value.lower() in _DMI_PLACEHOLDERS else value


def check_tpm_status():
    tpm_paths = sorted(glob.glob('/sys/class/tpm/tpm*'))
    if not tpm_paths:
        if os.path.exists('/dev/tpmrm0'):
            return {
                'present': True,
                'version': 'TPM 2.0 (Activo por Kernel /dev/tpmrm0)',
                'is_tpm2': True,
                'status': 'OK'
            }
        if os.path.exists('/dev/tpm0'):
            return {
                'present': True,
                'version': 'TPM presente (versión no confirmada)',
                'is_tpm2': False,
                'status': 'Warning'
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

    # /dev/tpmrm0 (kernel resource manager) only exists for TPM 2.0. A bare /dev/tpm0
    # with no version file is not enough to claim 2.0.
    if os.path.exists('/dev/tpmrm0'):
        return {
            'present': True,
            'version': 'TPM 2.0 (Detectado)',
            'is_tpm2': True,
            'status': 'OK'
        }
    if os.path.exists('/dev/tpm0'):
        return {
            'present': True,
            'version': 'TPM presente (versión no confirmada)',
            'is_tpm2': False,
            'status': 'Warning'
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

# Lenovo stores the machine type / part number (20S0S1EJ00, 21HDCTO1WW...) in product_name and
# the marketing name ("ThinkPad T14 Gen 1") in product_version / product_family.
_MACHINE_TYPE_RE = re.compile(r'^[0-9][0-9A-Z]{6,11}$')


def resolve_model_names(product_name, version, family):
    """(model, sku): use the friendly name as the model when product_name is only a part number.

    sku is the part number to show in parentheses, or the untouched version string otherwise.
    """
    product_name = (product_name or '').strip()
    version = (version or '').strip()
    family = (family or '').strip()
    if _MACHINE_TYPE_RE.match(product_name):
        for cand in (version, family):
            if (clean_dmi_value(cand) and re.search(r'[A-Za-z]{3,}', cand)
                    and not _MACHINE_TYPE_RE.match(cand)):
                return cand, product_name
    return product_name or family, version


def get_system_summary():
    vendor = (read_dmi_field('sys_vendor') or read_dmi_field('board_vendor') or 'Generico').strip()
    model, version = resolve_model_names(read_dmi_field('product_name'), read_dmi_field('product_version'),
                                         read_dmi_field('product_family'))
    model = (model or read_dmi_field('board_name') or 'Laptop / PC').strip()
    # A placeholder serial ("Default string", "To be filled by O.E.M."...) would be recorded as if it
    # were real: fall back to the board serial, then to N/A.
    serial = (clean_dmi_value(read_dmi_field('product_serial'))
              or clean_dmi_value(read_dmi_field('board_serial'))
              or 'N/A')
    
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
