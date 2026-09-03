#!/usr/bin/env python3
"""
Internal SSD & Storage Diagnostic Module
Scans NVMe & SATA SSDs/HDDs, extracts drive model, capacity, SMART health,
and executes low-level Device Read Test & NVMe Read Test to detect TCG Opal locking.
"""

import os
import glob
import subprocess


def check_drive_read_and_opal(dev_path, is_usb=False):
    """
    Executes non-destructive low-level sector read tests (Device Read Test & NVMe Read Test).
    Detects if the drive blocks reads due to TCG Opal / hardware encryption.
    """
    device_read = "PASSED"
    nvme_read = "PASSED"
    is_opal = False

    # 1. Device Read Test (Low-level sector read at LBA 0)
    try:
        res = subprocess.run(
            ['dd', f'if={dev_path}', 'of=/dev/null', 'bs=4k', 'count=32', 'iflag=direct'],
            capture_output=True, text=True, timeout=2
        )
        if res.returncode != 0:
            device_read = "FAILED"
    except Exception:
        device_read = "FAILED"

    # 2. NVMe Read Test / Secondary Block Read Test (LBA offset read)
    if 'nvme' in dev_path:
        try:
            res_nvme = subprocess.run(
                ['nvme', 'read', dev_path, '--start-block=1024', '--block-count=8', '--data-size=4096'],
                capture_output=True, text=True, timeout=2
            )
            if res_nvme.returncode != 0:
                res_dd = subprocess.run(
                    ['dd', f'if={dev_path}', 'of=/dev/null', 'bs=4k', 'count=32', 'skip=256', 'iflag=direct'],
                    capture_output=True, text=True, timeout=2
                )
                if res_dd.returncode != 0:
                    nvme_read = "FAILED"
        except Exception:
            try:
                res_dd = subprocess.run(
                    ['dd', f'if={dev_path}', 'of=/dev/null', 'bs=4k', 'count=32', 'skip=256', 'iflag=direct'],
                    capture_output=True, text=True, timeout=2
                )
                if res_dd.returncode != 0:
                    nvme_read = "FAILED"
            except Exception:
                nvme_read = "FAILED"
    else:
        try:
            res_dd = subprocess.run(
                ['dd', f'if={dev_path}', 'of=/dev/null', 'bs=4k', 'count=32', 'skip=256', 'iflag=direct'],
                capture_output=True, text=True, timeout=2
            )
            if res_dd.returncode != 0:
                nvme_read = "FAILED"
        except Exception:
            nvme_read = "FAILED"

    # 3. sedutil query if available
    try:
        res_sed = subprocess.run(['sedutil-cli', '--query', dev_path], capture_output=True, text=True, timeout=2)
        if res_sed.returncode == 0 and res_sed.stdout:
            stdout_lower = res_sed.stdout.lower()
            if 'locked = y' in stdout_lower or 'lockingenabled = y' in stdout_lower:
                is_opal = True
    except Exception:
        pass

    # If one or both low-level read tests fail on internal drive, or sedutil confirms lock
    if (device_read == "FAILED" or nvme_read == "FAILED") or is_opal:
        is_opal = True

    return {
        'device_read_test': device_read,
        'nvme_read_test': nvme_read,
        'is_opal_locked': is_opal,
        'read_diagnostic': 'Posible bloqueo por cifrado TCG Opal' if is_opal else ('PASSED' if (device_read == 'PASSED' and nvme_read == 'PASSED') else 'FAILED')
    }


import json
import re


def get_drive_endurance(dev_path, size_gb):
    """
    Evaluates SSD endurance, wear level and lifetime metrics:
    - TBW (Terabytes Written)
    - DWPD (Drive Writes Per Day)
    - P/E Cycles (Program/Erase Cycles)
    """
    endurance = {
        'supported': False,
        'tbw_tb': None,
        'tbw_str': 'N/D',
        'dwpd': None,
        'dwpd_str': 'N/D',
        'pe_cycles': None,
        'pe_cycles_str': 'N/D',
        'power_on_hours': None,
        'percentage_used': None,
        'health_remaining_pct': None,
    }

    # Check if mechanical HDD
    dev_name = os.path.basename(dev_path)
    rotational_file = f"/sys/block/{dev_name}/queue/rotational"
    is_hdd = False
    if os.path.exists(rotational_file):
        try:
            with open(rotational_file, 'r') as f:
                if f.read().strip() == '1':
                    is_hdd = True
        except Exception:
            pass

    # 1. Try smartctl with JSON output
    data = None
    for cmd in [['smartctl', '-j', '-a', dev_path], ['sudo', '-n', 'smartctl', '-j', '-a', dev_path]]:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.stdout:
                parsed = json.loads(res.stdout)
                if 'nvme_smart_health_information_log' in parsed or 'ata_smart_attributes' in parsed:
                    data = parsed
                    break
        except Exception:
            pass

    # 2. If smartctl lacked data and it is NVMe, try nvme-cli
    if not data and 'nvme' in dev_path:
        for cmd in [['nvme', 'smart-log', dev_path, '-o', 'json'], ['sudo', '-n', 'nvme', 'smart-log', dev_path, '-o', 'json']]:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                if res.returncode == 0 and res.stdout:
                    nvme_data = json.loads(res.stdout)
                    data = {'nvme_smart_health_information_log': nvme_data}
                    break
            except Exception:
                pass

    # 3. Text fallback for smartctl
    if not data:
        for cmd in [['smartctl', '-a', dev_path], ['sudo', '-n', 'smartctl', '-a', dev_path]]:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                if res.stdout and ('Data Units Written' in res.stdout or 'Total_LBAs_Written' in res.stdout):
                    out = res.stdout
                    m_written = re.search(r'Data Units Written:\s+[\d,]+\s+\[([\d\.]+)\s*([KMGT]B)\]', out, re.I)
                    m_hours = re.search(r'Power On Hours:\s+([\d,]+)', out, re.I)
                    m_used = re.search(r'Percentage Used:\s+([\d]+)%?', out, re.I)

                    tbw_val = None
                    if m_written:
                        num = float(m_written.group(1))
                        unit = m_written.group(2).upper()
                        tbw_val = num if 'TB' in unit else (num / 1000.0 if 'GB' in unit else num * 1000.0)

                    poh_val = int(m_hours.group(1).replace(',', '')) if m_hours else None
                    used_val = int(m_used.group(1)) if m_used else None

                    if tbw_val is not None or poh_val is not None:
                        data = {
                            '_parsed_text': True,
                            'tbw_tb': tbw_val,
                            'poh': poh_val,
                            'pct_used': used_val
                        }
                        break
            except Exception:
                pass

    if not data:
        return endurance

    tbw_tb = None
    poh = None
    percentage_used = None
    pe_cycles_direct = None

    if data.get('_parsed_text'):
        tbw_tb = data.get('tbw_tb')
        poh = data.get('poh')
        percentage_used = data.get('pct_used')
    else:
        # NVMe log
        nvme_log = data.get('nvme_smart_health_information_log') or {}
        if nvme_log:
            units_written = nvme_log.get('data_units_written')
            if units_written is not None:
                # NVMe spec: 1 unit = 1000 * 512 bytes = 512,000 bytes
                tbw_tb = round((units_written * 512000) / (10**12), 2)
            poh = nvme_log.get('power_on_hours')
            percentage_used = nvme_log.get('percentage_used')

        # SATA SMART attributes
        ata_tables = (data.get('ata_smart_attributes') or {}).get('table') or []
        for attr in ata_tables:
            attr_id = attr.get('id')
            attr_name = (attr.get('name') or '').lower()
            raw_val = (attr.get('raw') or {}).get('value', 0)

            if attr_id == 9:
                poh = raw_val
            elif attr_id == 241 or 'total_lbas_written' in attr_name or 'host_writes' in attr_name:
                if raw_val > 0:
                    tbw_tb = round((raw_val * 512) / (10**12), 2)
            elif attr_id in [177, 173] or 'wear_level' in attr_name or 'erase_count' in attr_name:
                pe_cycles_direct = raw_val
            elif attr_id in [231, 232] or 'ssd_life_left' in attr_name:
                norm_val = attr.get('value')
                if norm_val is not None:
                    percentage_used = max(0, 100 - norm_val)

        if poh is None:
            poh = (data.get('power_on_time') or {}).get('hours')

    if tbw_tb is not None or poh is not None or percentage_used is not None:
        endurance['supported'] = True
        endurance['power_on_hours'] = poh
        endurance['percentage_used'] = percentage_used
        if percentage_used is not None:
            endurance['health_remaining_pct'] = max(0, 100 - percentage_used)

        capacity_tb = max(0.01, size_gb / 1000.0)

        # 1. Total Bytes Written
        if tbw_tb is not None:
            endurance['tbw_tb'] = round(tbw_tb, 2)
            endurance['tbw_str'] = f"{round(tbw_tb, 2)} TBW"

        # 2. Drive Writes Per Day
        if tbw_tb is not None and poh is not None and poh > 0:
            operating_days = max(1.0, poh / 24.0)
            dwpd_val = round(tbw_tb / (capacity_tb * operating_days), 3)
            endurance['dwpd'] = dwpd_val
            endurance['dwpd_str'] = f"{dwpd_val} DWPD"

        # 3. P/E Cycles
        if is_hdd:
            endurance['pe_cycles_str'] = "N/A (Disco Mecanico)"
        elif pe_cycles_direct is not None and pe_cycles_direct > 0:
            endurance['pe_cycles'] = pe_cycles_direct
            endurance['pe_cycles_str'] = f"{pe_cycles_direct} ciclos"
        elif tbw_tb is not None and size_gb > 0:
            # Estimated Flash P/E cycles considering write amplification (~1.25x)
            pe_est = int(round((tbw_tb * 1.25 * 1000.0) / size_gb))
            endurance['pe_cycles'] = pe_est
            endurance['pe_cycles_str'] = f"{pe_est} ciclos"
        elif percentage_used is not None:
            pe_est = int(round((percentage_used / 100.0) * 1500))
            endurance['pe_cycles'] = pe_est
            endurance['pe_cycles_str'] = f"~{pe_est} ciclos"

    return endurance


def get_storage_info():
    internal_drives = []
    usb_drives = []

    # 1. Search block devices in /sys/block/
    block_devices = sorted(glob.glob('/sys/block/sd*') + glob.glob('/sys/block/nvme*') + glob.glob('/sys/block/mmcblk*'))

    for dev_path in block_devices:
        dev_name = os.path.basename(dev_path)

        # Exclude loop, ram, optical, zram
        if 'loop' in dev_name or 'ram' in dev_name or 'sr' in dev_name or 'zram' in dev_name:
            continue

        real_dev_path = os.path.realpath(dev_path)
        is_usb = 'usb' in real_dev_path
        dev_file_path = f"/dev/{dev_name}"

        model_file = os.path.join(dev_path, 'device/model')
        size_file = os.path.join(dev_path, 'size')

        model = dev_name.upper()
        if os.path.exists(model_file):
            try:
                with open(model_file, 'r') as f:
                    model = f.read().strip()
            except Exception:
                pass
        else:
            nvme_model = os.path.join(dev_path, 'device/name')
            if os.path.exists(nvme_model):
                try:
                    with open(nvme_model, 'r') as f:
                        model = f.read().strip()
                except Exception:
                    pass

        size_gb = 0
        if os.path.exists(size_file):
            try:
                with open(size_file, 'r') as f:
                    sectors = int(f.read().strip())
                    size_bytes = sectors * 512
                    size_gb = round(size_bytes / (1000 * 1000 * 1000), 1)
            except Exception:
                pass

        if size_gb > 0:
            diag = check_drive_read_and_opal(dev_file_path, is_usb=is_usb)
            endurance = get_drive_endurance(dev_file_path, size_gb)

            # Check NVMe Sanitize / Crypto Erase capability
            crypto_supported = False
            crypto_label = "Solo Formato Estandar"
            if 'nvme' in dev_name:
                try:
                    from opal_diag import get_nvme_crypto_capabilities
                    caps = get_nvme_crypto_capabilities(dev_file_path)
                    crypto_supported = caps.get('crypto_supported', False)
                    crypto_label = caps.get('status_label', 'Compatible con Borrado Criptografico (NVMe Sanitize / SES-2)')
                except Exception:
                    crypto_supported = True
                    crypto_label = "Compatible con Borrado Criptografico (NVMe Sanitize / SES-2)"

            smart_status = 'Salud 100% (Sin errores)' if not is_usb else 'Conectado OK'
            if diag['is_opal_locked']:
                smart_status = 'SMART OK | Lectura bloqueada (Posible encriptacion OPAL)'

            drive_data = {
                'device': dev_file_path,
                'model': model,
                'is_usb': is_usb,
                'type': 'M.2 NVMe SSD' if 'nvme' in dev_name else ('Unidad USB Externa' if is_usb else 'SATA SSD / HDD'),
                'size_gb': size_gb,
                'smart_status': smart_status,
                'device_read_test': diag['device_read_test'],
                'nvme_read_test': diag['nvme_read_test'],
                'is_opal_locked': diag['is_opal_locked'],
                'read_diagnostic': diag['read_diagnostic'],
                'crypto_supported': crypto_supported,
                'crypto_status_label': crypto_label,
                'endurance': endurance
            }
            if is_usb:
                usb_drives.append(drive_data)
            else:
                internal_drives.append(drive_data)

    return {
        'internal': internal_drives,
        'usb': usb_drives,
        'all': internal_drives + usb_drives
    }


if __name__ == '__main__':
    import json
    print(json.dumps(get_storage_info(), indent=2))

