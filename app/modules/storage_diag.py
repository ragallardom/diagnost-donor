#!/usr/bin/env python3
"""
Internal SSD & Storage Diagnostic Module
Scans NVMe & SATA SSDs/HDDs, extracts drive model, capacity, SMART health,
and executes low-level Device Read Test & NVMe Read Test to detect TCG Opal locking.

The expensive per-drive probes (dd/nvme reads, sedutil, SMART) are cached per
device and only re-run when a drive appears/changes, when the cache expires, or
after a destructive disk operation invalidates it. This keeps the 1 s telemetry
poll cheap.
"""

import os
import glob
import json
import re
import subprocess
import threading
import time
from contextlib import contextmanager

from opal_diag import classify_drive, sedutil_query, get_nvme_crypto_capabilities, invalidate_opal_cache

# Serializes destructive disk operations (PSID revert, crypto erase) among themselves.
DISK_LOCK = threading.Lock()
# Serializes drive scans; also guards _disk_op_active.
_SCAN_LOCK = threading.Lock()
_disk_op_active = False

# Seconds a drive's probe results stay valid before being refreshed.
PROBE_TTL_SEC = 60

_probe_cache = {}      # dev_name -> {'key': (...), 'time': float, 'data': dict}
_probe_cache_lock = threading.Lock()
_last_snapshot = {'internal': [], 'usb': [], 'all': []}


def invalidate_storage_cache(dev_name=None):
    """Drop cached probe results for one device (e.g. 'nvme0n1') or for all."""
    invalidate_opal_cache()
    with _probe_cache_lock:
        if dev_name is None:
            _probe_cache.clear()
        else:
            _probe_cache.pop(os.path.basename(dev_name), None)


def check_drive_read_and_opal(dev_path, is_usb=False, opal_applicable=True):
    """
    Executes non-destructive low-level sector read tests (Device Read Test & NVMe Read Test).
    Detects if the drive blocks reads due to TCG Opal / hardware encryption.

    Opal checks (sedutil query and "read blocked -> Opal" inference) only run
    when opal_applicable (SSDs); on pen drives / HDDs a read failure is just a
    read failure.
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

    # 3. sedutil query (SSDs only; shared cache with the Opal drive listing)
    if opal_applicable:
        stdout_lower = sedutil_query(dev_path)
        if 'locked = y' in stdout_lower or 'lockingenabled = y' in stdout_lower:
            is_opal = True

        # If one or both low-level read tests fail on an SSD, or sedutil confirms lock
        if (device_read == "FAILED" or nvme_read == "FAILED") or is_opal:
            is_opal = True

    return {
        'device_read_test': device_read,
        'nvme_read_test': nvme_read,
        'is_opal_locked': is_opal,
        'read_diagnostic': 'Posible bloqueo por cifrado TCG Opal' if is_opal else ('PASSED' if (device_read == 'PASSED' and nvme_read == 'PASSED') else 'FAILED')
    }


SMART_UNKNOWN = {'level': 'unknown', 'reasons': []}

# A few reallocated sectors / media errors are normal in a used drive: not reported.
MINOR_ERRORS_IGNORED = 10
REALLOCATED_WARN = 20

# NVMe critical_warning bits (NVMe spec, SMART / Health log page).
_NVME_CRITICAL_BITS = (
    (0x01, 'reserva baja'),
    (0x02, 'temperatura fuera de rango'),
    (0x04, 'fiabilidad degradada'),
    (0x08, 'solo lectura'),
    (0x10, 'fallo del respaldo volátil'),
)


def evaluate_smart_health(data):
    """Real SMART verdict from smartctl JSON (or nvme-cli) data.

    Returns {'level': 'ok'|'warning'|'failed'|'unknown', 'reasons': [...]}.
    'unknown' means the drive exposed nothing usable: never reported as healthy.
    """
    if not data or data.get('_parsed_text'):
        return dict(SMART_UNKNOWN, reasons=[])

    failed, warnings = [], []
    seen_signal = False

    overall = (data.get('smart_status') or {}).get('passed')
    if overall is not None:
        seen_signal = True
        if overall is False:
            failed.append('SMART predice fallo')

    nvme = data.get('nvme_smart_health_information_log') or {}
    if nvme:
        seen_signal = True
        crit = nvme.get('critical_warning') or 0
        for bit, text in _NVME_CRITICAL_BITS:
            if crit & bit:
                failed.append(f'NVMe: {text}')
        media = nvme.get('media_errors') or 0
        if media >= MINOR_ERRORS_IGNORED:
            warnings.append(f'{media} errores de integridad')
        spare = nvme.get('available_spare', nvme.get('avail_spare'))
        spare_thr = nvme.get('available_spare_threshold', nvme.get('spare_thresh'))
        if spare is not None and spare_thr is not None and spare < spare_thr:
            failed.append(f'Reserva baja ({spare}%)')
        used = nvme.get('percentage_used', nvme.get('percent_used'))
        if used is not None and used >= 100:
            warnings.append(f'Vida útil al {used}%')
        elif used is not None and used >= 90:
            warnings.append(f'Vida útil al {used}%')

    # SATA: attributes whose raw value should stay at 0 on a healthy drive.
    for attr in (data.get('ata_smart_attributes') or {}).get('table') or []:
        seen_signal = True
        raw = (attr.get('raw') or {}).get('value') or 0
        attr_id = attr.get('id')
        if attr_id == 5 and raw >= REALLOCATED_WARN:
            warnings.append(f'{raw} sectores reasignados')
        elif attr_id == 197 and raw > 0:
            warnings.append(f'{raw} sectores pendientes')
        elif attr_id == 198 and raw > 0:
            warnings.append(f'{raw} sectores incorregibles')

    if not seen_signal:
        return dict(SMART_UNKNOWN, reasons=[])
    if failed:
        return {'level': 'failed', 'reasons': failed + warnings}
    if warnings:
        return {'level': 'warning', 'reasons': warnings}
    return {'level': 'ok', 'reasons': []}


def smart_status_label(health, is_usb=False):
    """Short card text. Details (reasons) go in a tooltip; only serious problems are flagged."""
    level = (health or SMART_UNKNOWN)['level']
    if level == 'failed':
        return 'SMART: riesgo de fallo'
    if level == 'warning':
        return 'SMART: revisar'
    if level == 'ok':
        return 'SMART correcto'
    return 'Conectado OK' if is_usb else 'SMART no disponible'


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
        'health': dict(SMART_UNKNOWN, reasons=[]),
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

    endurance['health'] = evaluate_smart_health(data)

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
            # smartctl calls it percentage_used, nvme-cli percent_used.
            percentage_used = nvme_log.get('percentage_used', nvme_log.get('percent_used'))

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


def _probe_drive(dev_name, dev_file_path, is_usb, size_gb):
    """Run the expensive per-drive probes (read tests, SMART, crypto caps)."""
    drive_class = classify_drive(dev_file_path)
    diag = check_drive_read_and_opal(dev_file_path, is_usb=is_usb,
                                     opal_applicable=drive_class['opal_applicable'])
    endurance = get_drive_endurance(dev_file_path, size_gb)

    # Check NVMe Sanitize / Crypto Erase capability
    crypto_supported = False
    crypto_label = "Solo Formato Estandar"
    if 'nvme' in dev_name:
        try:
            caps = get_nvme_crypto_capabilities(dev_file_path)
            crypto_supported = caps.get('crypto_supported', False)
            crypto_label = caps.get('status_label', 'Compatible con Borrado Criptografico (NVMe Sanitize / SES-2)')
        except Exception:
            crypto_supported = True
            crypto_label = "Compatible con Borrado Criptografico (NVMe Sanitize / SES-2)"

    return {
        'diag': diag,
        'drive_class': drive_class,
        'endurance': endurance,
        'crypto_supported': crypto_supported,
        'crypto_label': crypto_label,
    }


def _drive_type_label(dev_name, is_usb, media):
    if 'nvme' in dev_name:
        return 'M.2 NVMe SSD'
    if is_usb:
        return {'ssd': 'SSD externo USB', 'hdd': 'Disco duro externo USB'}.get(media, 'Unidad USB Externa')
    if dev_name.startswith('mmcblk'):
        return 'eMMC / Tarjeta SD'
    return {'ssd': 'SATA SSD', 'hdd': 'Disco duro HDD'}.get(media, 'SATA SSD / HDD')


def _get_cached_probe(dev_name, dev_file_path, is_usb, size_gb, model):
    key = (model, size_gb, is_usb)
    now = time.monotonic()
    with _probe_cache_lock:
        entry = _probe_cache.get(dev_name)
        if entry and entry['key'] == key and (now - entry['time']) < PROBE_TTL_SEC:
            return entry['data']

    data = _probe_drive(dev_name, dev_file_path, is_usb, size_gb)
    with _probe_cache_lock:
        _probe_cache[dev_name] = {'key': key, 'time': time.monotonic(), 'data': data}
    return data


@contextmanager
def exclusive_disk_access():
    """Run a destructive disk operation with no drive scan touching the disks.

    Waits for any in-flight scan to finish; while the operation runs, scans
    return the last snapshot instead of probing. Invalidates the probe cache
    afterwards so the next scan reflects the new drive state.
    """
    global _disk_op_active
    with DISK_LOCK:
        with _SCAN_LOCK:
            _disk_op_active = True
        try:
            yield
        finally:
            with _SCAN_LOCK:
                _disk_op_active = False
            invalidate_storage_cache()


_has_snapshot = False


def get_storage_snapshot():
    """Non-blocking variant for the 1 s telemetry poll.

    If a scan is already running (e.g. the slow first scan at startup), return
    the last completed snapshot instead of waiting, or None if there is none yet.
    """
    if not _SCAN_LOCK.acquire(blocking=False):
        return _last_snapshot if _has_snapshot else None
    try:
        return _scan_locked()
    finally:
        _SCAN_LOCK.release()


def get_storage_info():
    with _SCAN_LOCK:
        return _scan_locked()


def _scan_locked():
    """Scan the drives; caller holds _SCAN_LOCK."""
    global _last_snapshot, _has_snapshot
    # A destructive disk operation is in progress: don't probe the drives.
    if _disk_op_active:
        return _last_snapshot
    _last_snapshot = _scan_storage()
    _has_snapshot = True
    return _last_snapshot


def _scan_storage():
    internal_drives = []
    usb_drives = []
    present = set()

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
            present.add(dev_name)
            probe = _get_cached_probe(dev_name, dev_file_path, is_usb, size_gb, model)
            diag = probe['diag']

            smart_health = probe['endurance'].get('health')
            smart_status = smart_status_label(smart_health, is_usb)

            media = probe.get('drive_class', {}).get('media')
            drive_data = {
                'device': dev_file_path,
                'model': model,
                'is_usb': is_usb,
                'type': _drive_type_label(dev_name, is_usb, media),
                'media': media,
                'opal_applicable': probe.get('drive_class', {}).get('opal_applicable', False),
                'size_gb': size_gb,
                'smart_status': smart_status,
                'smart_health': (smart_health or SMART_UNKNOWN)['level'],
                'smart_detail': '; '.join((smart_health or SMART_UNKNOWN)['reasons'][:3]),
                'device_read_test': diag['device_read_test'],
                'nvme_read_test': diag['nvme_read_test'],
                'is_opal_locked': diag['is_opal_locked'],
                'read_diagnostic': diag['read_diagnostic'],
                'crypto_supported': probe['crypto_supported'],
                'crypto_status_label': probe['crypto_label'],
                'endurance': probe['endurance']
            }
            if is_usb:
                usb_drives.append(drive_data)
            else:
                internal_drives.append(drive_data)

    # Forget drives that were unplugged so a re-plug is probed again.
    with _probe_cache_lock:
        for gone in set(_probe_cache) - present:
            del _probe_cache[gone]

    return {
        'internal': internal_drives,
        'usb': usb_drives,
        'all': internal_drives + usb_drives
    }


if __name__ == '__main__':
    print(json.dumps(get_storage_info(), indent=2))

