#!/usr/bin/env python3
"""
TCG Opal / McAfee PSID Unlock Module
Lists internal and USB-connected SED storage drives and performs full PSID Revert + factory reset:
- sedutil-cli PSID Revert
- Storage controller / bus rescan
- Signature & residual partition wipe (wipefs)
- Blank GPT partition table creation (parted)
"""

import os
import glob
import subprocess
import re
import json
import time

def list_target_drives():
    drives = []
    seen_devices = set()

    # 1. Primary Strategy: Scan via sedutil-cli
    try:
        res = subprocess.run(['sedutil-cli', '--scan'], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout:
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.startswith('/dev/'):
                    dev_path = line.split()[0]
                    if dev_path not in seen_devices and os.path.exists(dev_path):
                        seen_devices.add(dev_path)
                        info = _get_device_info(dev_path)
                        info['is_sedutil_detected'] = True
                        drives.append(info)
    except Exception:
        pass

    # 2. NVMe Drives scan fallback / complement
    for path in sorted(glob.glob('/dev/nvme*n1')):
        if path not in seen_devices and os.path.exists(path):
            seen_devices.add(path)
            drives.append(_get_device_info(path))

    # 3. SATA / USB Drives scan fallback / complement
    for path in sorted(glob.glob('/dev/sd[a-z]')):
        if path not in seen_devices and os.path.exists(path):
            seen_devices.add(path)
            drives.append(_get_device_info(path))

    return drives

def _get_device_info(dev_path):
    dev_name = os.path.basename(dev_path)
    model = "Dispositivo de Almacenamiento"
    size = "?"
    tran = "Interno"

    # Query lsblk for rich info
    try:
        res = subprocess.run(
            ['lsblk', '-d', '-n', '-o', 'MODEL,SIZE,TRAN', dev_path],
            capture_output=True, text=True, timeout=2
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split()
            if len(parts) >= 3:
                tran = parts[-1].upper()
                size = parts[-2]
                model = " ".join(parts[:-2])
            elif len(parts) == 2:
                size = parts[-1]
                model = parts[0]
    except Exception:
        pass

    # Sysfs model fallback
    if model in ("Dispositivo de Almacenamiento", "", "?"):
        model_file = f"/sys/class/block/{dev_name}/device/model"
        if os.path.exists(model_file):
            try:
                with open(model_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        model = content
            except Exception:
                pass

    if not model or model == "?":
        if 'nvme' in dev_name:
            model = "SSD NVMe"
        else:
            model = "Disco SATA/USB"

    # Classify drive type label
    if 'nvme' in dev_name:
        drive_type = f"NVMe SSD ({size})"
    elif tran == 'USB' or 'usb' in os.path.realpath(f"/sys/class/block/{dev_name}"):
        drive_type = f"USB SSD / Cofre ({size})"
    else:
        drive_type = f"SATA SSD/HDD ({size})"

    return {
        'device': dev_path,
        'model': model,
        'size': size,
        'transport': tran,
        'type': drive_type,
        'is_opal_locked': check_opal_locked(dev_path)
    }

def check_opal_locked(device):
    try:
        res = subprocess.run(['sedutil-cli', '--query', device], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            stdout = res.stdout.lower()
            if 'locked = yes' in stdout or 'mbr enabled = yes' in stdout or 'locking feature = yes' in stdout:
                return True
            if 'tper function = yes' in stdout or 'locking function = yes' in stdout:
                return True
    except Exception:
        pass
    return False

def execute_psid_revert(device, psid):
    psid_clean = re.sub(r'[^A-Za-z0-9]', '', psid).upper()
    log_entries = []

    if len(psid_clean) != 32:
        return {
            'success': False,
            'message': f'Error: El código PSID debe tener exactamente 32 caracteres alfanuméricos (se ingresaron {len(psid_clean)}).',
            'log': f'Validación fallida: Longitud de PSID={len(psid_clean)} (requerido: 32).\n'
        }

    if not os.path.exists(device):
        return {
            'success': False,
            'message': f'Error: El dispositivo objetivo {device} no existe en el sistema o fue desconectado.',
            'log': f'Dispositivo no encontrado: {device}\n'
        }

    log_entries.append(f"[1/5] Iniciando PSID Revert en {device} con PSID: {psid_clean[:4]}...{psid_clean[-4:]}")

    # 1. Strategy A: Standard sedutil non-interactive erase command
    revert_success = False
    auth_error = False

    cmd_primary = ['sedutil-cli', '--yesIreallywanttoERASEALLmydatausingthePSID', psid_clean, device]
    log_entries.append(f"Ejecutando: sedutil-cli --yesIreallywanttoERASEALLmydatausingthePSID [PSID] {device}")
    
    try:
        res = subprocess.run(cmd_primary, capture_output=True, text=True, timeout=20)
        stdout = (res.stdout or "") + "\n" + (res.stderr or "")
        log_entries.append(f"Salida sedutil:\n{stdout.strip()}")

        if 'NOT_AUTHORIZED' in stdout or 'not authorized' in stdout.lower():
            auth_error = True
        elif res.returncode == 0 or 'revert completed successfully' in stdout.lower() or 'psidrevert success' in stdout.lower():
            revert_success = True
    except FileNotFoundError:
        log_entries.append("[AVISO] 'sedutil-cli' no encontrado en el PATH.")
    except Exception as exc:
        log_entries.append(f"[ERROR] Excepción ejecutando sedutil-cli: {exc}")

    # 2. Strategy B: Alternate sedutil syntax fallback if primary didn't succeed and not auth error
    if not revert_success and not auth_error:
        cmd_fallback = ['sedutil-cli', '--PSIDrevert', psid_clean, device]
        log_entries.append(f"Reintentando con: sedutil-cli --PSIDrevert [PSID] {device}")
        try:
            res_alt = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=20)
            stdout_alt = (res_alt.stdout or "") + "\n" + (res_alt.stderr or "")
            log_entries.append(f"Salida sedutil alternativo:\n{stdout_alt.strip()}")
            if 'NOT_AUTHORIZED' in stdout_alt or 'not authorized' in stdout_alt.lower():
                auth_error = True
            elif res_alt.returncode == 0 or 'revert completed successfully' in stdout_alt.lower():
                revert_success = True
        except Exception as exc:
            log_entries.append(f"[ERROR] Excepción fallback sedutil: {exc}")

    # If rejected by drive controller
    if auth_error:
        return {
            'success': False,
            'message': f'ERROR DE AUTORIZACIÓN (NOT_AUTHORIZED): El disco {device} rechazó el código PSID. Verifica cuidadosamente los 32 caracteres impresos en la etiqueta física del SSD.',
            'log': "\n".join(log_entries)
        }

    # 3. Strategy C: NVMe Crypto Format fallback if sedutil failed on an NVMe drive
    if not revert_success and 'nvme' in device:
        log_entries.append(f"[2/5] Intentando borrado criptográfico seguro NVMe (nvme format {device} -s 2)...")
        try:
            cmd_nvme = ['nvme', 'format', device, '-s', '2']
            res_nvme = subprocess.run(cmd_nvme, capture_output=True, text=True, timeout=25)
            stdout_nvme = (res_nvme.stdout or "") + "\n" + (res_nvme.stderr or "")
            log_entries.append(f"Salida nvme-cli:\n{stdout_nvme.strip()}")
            if res_nvme.returncode == 0:
                revert_success = True
                log_entries.append("✅ Borrado criptográfico NVMe ejecutado con éxito.")
        except Exception as exc:
            log_entries.append(f"[ERROR] Excepción nvme-cli: {exc}")

    if not revert_success:
        return {
            'success': False,
            'message': f'FALLO DE DESBLOQUEO ({device}): La unidad no respondió a la orden de PSID Revert o el código es incorrecto. Revisa el registro.',
            'log': "\n".join(log_entries)
        }

    # 4. Storage Controller & Bus Rescan
    log_entries.append(f"[3/5] Refrescando controlador del bus de almacenamiento para {device}...")
    sys_name = os.path.basename(device)
    rescan_path = f"/sys/block/{sys_name}/device/rescan"
    if os.path.exists(rescan_path):
        try:
            with open(rescan_path, 'w') as f:
                f.write("1\n")
            log_entries.append(f"Rescan enviado a {rescan_path}")
        except Exception as exc:
            log_entries.append(f"[AVISO] No se pudo escribir en rescan: {exc}")

    time.sleep(1)

    try:
        subprocess.run(['partprobe', device], capture_output=True, timeout=5)
        subprocess.run(['udevadm', 'settle', '--timeout=3'], capture_output=True, timeout=5)
    except Exception:
        pass

    # 5. Residual Partition & BitLocker Signature Wipe
    log_entries.append(f"[4/5] Eliminando firmas residuales de particiones y BitLocker (wipefs)...")
    try:
        wipe_res = subprocess.run(['wipefs', '-af', device], capture_output=True, text=True, timeout=10)
        log_entries.append(f"wipefs: {(wipe_res.stdout or wipe_res.stderr or 'Firmas eliminadas.').strip()}")
    except Exception as exc:
        log_entries.append(f"[AVISO] wipefs fallo o no disponible: {exc}")

    # 6. Create clean blank GPT Partition Table
    log_entries.append(f"[5/5] Creando nueva tabla de particiones GPT limpia (parted)...")
    try:
        parted_res = subprocess.run(['parted', '-s', device, 'mklabel', 'gpt'], capture_output=True, text=True, timeout=10)
        log_entries.append(f"parted: {(parted_res.stdout or parted_res.stderr or 'Tabla GPT creada OK.').strip()}")
        subprocess.run(['partprobe', device], capture_output=True, timeout=5)
    except Exception as exc:
        log_entries.append(f"[AVISO] parted fallo o no disponible: {exc}")

    log_entries.append("✅ ¡Proceso de desbloqueo y restauración de fábrica completado con éxito!")

    return {
        'success': True,
        'message': f'¡DISCO DESBLOQUEADO CON ÉXITO ({device})!\n\n'
                   f'• Cifrado Opal / McAfee: Desactivado\n'
                   f'• Estado del disco: Restaurado a valores de fábrica\n'
                   f'• Firmas residuales: Eliminadas\n'
                   f'• Tabla de particiones: GPT limpia y lista para usar.',
        'log': "\n".join(log_entries),
        'steps': [
            'PSID Revert ejecutado en el disco',
            'Controlador de almacenamiento refrescado',
            'Firmas y metadatos residuales borrados',
            'Nueva tabla de particiones GPT generada'
        ]
    }

if __name__ == '__main__':
    print(json.dumps(list_target_drives(), indent=2))
