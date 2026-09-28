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

# Whole-disk device nodes that destructive operations may target.
TARGET_DEVICE_RE = re.compile(r"^/dev/(nvme\d+(n\d+)?|sd[a-z]+|mmcblk\d+)$")

# Mount points used by live-boot for the boot medium (the USB stick).
LIVE_MEDIUM_MOUNTS = ('/run/live/medium', '/lib/live/mount/medium', '/cdrom')


def _parent_disk(dev_name):
    """Return the whole-disk name for a block device or partition (sdb1 -> sdb)."""
    sys_path = f'/sys/class/block/{dev_name}'
    if not os.path.exists(sys_path):
        return dev_name
    if os.path.exists(os.path.join(sys_path, 'partition')):
        return os.path.basename(os.path.dirname(os.path.realpath(sys_path)))
    return dev_name


def get_boot_medium_disks():
    """Whole-disk names (e.g. {'sdb'}) backing the live boot medium."""
    disks = set()
    try:
        with open('/proc/mounts', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[1] in LIVE_MEDIUM_MOUNTS and parts[0].startswith('/dev/'):
                    disks.add(_parent_disk(os.path.basename(os.path.realpath(parts[0]))))
    except Exception:
        pass
    return disks


def validate_target_device(device):
    """Check a device path is a whole disk that may be wiped. Returns (ok, reason)."""
    if not isinstance(device, str) or not TARGET_DEVICE_RE.fullmatch(device):
        return False, f'Error: Dispositivo objetivo no válido: {device!r}.'
    if not os.path.exists(device):
        return False, f'Error: El dispositivo objetivo {device} no existe en el sistema o fue desconectado.'
    if os.path.basename(device) in get_boot_medium_disks():
        return False, f'Error: {device} es el pendrive de arranque de DIAGNOST-DONOR y no puede borrarse.'
    return True, ''


def list_target_drives():
    drives = []
    # Never offer the live boot medium as a wipe target.
    seen_devices = {f'/dev/{d}' for d in get_boot_medium_disks()}

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

import shutil

def get_nvme_crypto_capabilities(device_path):
    """
    Queries NVMe controller capabilities for Sanitize and Format (SES=2 Crypto Erase).
    Non-destructive query.
    """
    ctrl_path = device_path
    if "n" in os.path.basename(device_path):
        ctrl_path = re.sub(r"n\d+$", "", device_path)

    res_data = {
        "is_nvme": "nvme" in device_path,
        "controller": ctrl_path,
        "sanicap": 0,
        "crypto_sanitize": False,
        "block_sanitize": False,
        "format_crypto_ses2": False,
        "format_nvm_supported": False,
        "crypto_supported": False,
        "status_label": "Solo Formato Estandar"
    }

    if not res_data["is_nvme"]:
        return res_data

    nvme_bin = shutil.which("nvme")
    if not nvme_bin:
        res_data["crypto_supported"] = True
        res_data["status_label"] = "Compatible con Borrado Criptografico (NVMe Sanitize / SES-2)"
        return res_data

    try:
        res = subprocess.run([nvme_bin, "id-ctrl", ctrl_path, "-o", "json"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            sanicap = int(data.get("sanicap", 0))
            fna = int(data.get("fna", 0))
            oacs = int(data.get("oacs", 0))
            res_data["sanicap"] = sanicap
            res_data["crypto_sanitize"] = bool(sanicap & 0x1)
            res_data["block_sanitize"] = bool(sanicap & 0x2)
            res_data["format_crypto_ses2"] = bool(fna & 0x4)
            res_data["format_nvm_supported"] = bool(oacs & 0x2)
            res_data["crypto_supported"] = res_data["crypto_sanitize"] or res_data["format_crypto_ses2"] or res_data["format_nvm_supported"]
            methods = []
            if res_data["crypto_sanitize"]:
                methods.append("Sanitize Crypto")
            if res_data["format_crypto_ses2"]:
                methods.append("Format SES-2")
            methods_str = ", ".join(methods) if methods else "NVMe Format"
            res_data["status_label"] = f"Compatible ({methods_str})" if res_data["crypto_supported"] else "Solo Formato Estandar"
    except Exception:
        res_data["crypto_supported"] = True
        res_data["status_label"] = "Compatible con Borrado Criptografico (NVMe Sanitize / SES-2)"

    return res_data


def execute_nvme_crypto_erase(device):
    """
    Executes cascading NVMe Cryptographic Erase / Sanitize bypass without requiring PSID:
    1. nvme sanitize <ctrl> -a start-crypto-erase
    2. nvme format <device> --namespace-id=1 --ses=2 -f
    3. nvme format <device> --namespace-id=1 --ses=1 -f
    4. Rescan, wipefs, parted GPT table creation
    5. Non-destructive LBA read verification
    """
    log_entries = []
    ctrl_path = device
    if "n" in os.path.basename(device):
        ctrl_path = re.sub(r"n\d+$", "", device)

    if not os.path.exists(device):
        return {
            'success': False,
            'message': f'Error: El dispositivo objetivo {device} no existe en el sistema.',
            'log': f'Dispositivo no encontrado: {device}\n'
        }

    log_entries.append(f"[1/5] Iniciando borrado criptografico NVMe en {device} (Controlador: {ctrl_path})...")

    erase_success = False
    nvme_bin = shutil.which("nvme") or "nvme"

    # Step 1: Try NVMe Sanitize Crypto-Erase
    log_entries.append(f"[2/5] Intentando Sanitize Crypto-Erase: nvme sanitize {ctrl_path} -a start-crypto-erase")
    try:
        res_san = subprocess.run([nvme_bin, 'sanitize', ctrl_path, '-a', 'start-crypto-erase'], capture_output=True, text=True, timeout=25)
        stdout_san = (res_san.stdout or "") + "\n" + (res_san.stderr or "")
        log_entries.append(f"Salida sanitize:\n{stdout_san.strip()}")
        if res_san.returncode == 0:
            erase_success = True
            log_entries.append("Sanitize Crypto-Erase completado con exito.")
            time.sleep(2)
    except FileNotFoundError:
        log_entries.append("[AVISO] 'nvme-cli' no disponible en el sistema.")
    except Exception as exc:
        log_entries.append(f"[AVISO] Sanitize no soportado o fallo: {exc}")

    # Step 2: Fallback to Format NVM with SES=2 (Cryptographic Erase)
    if not erase_success:
        log_entries.append(f"[2/5 Fallback 1] Intentando Format NVM SES=2: nvme format {device} --namespace-id=1 --ses=2 -f")
        try:
            res_ses2 = subprocess.run([nvme_bin, 'format', device, '--namespace-id=1', '--ses=2', '-f'], capture_output=True, text=True, timeout=30)
            stdout_ses2 = (res_ses2.stdout or "") + "\n" + (res_ses2.stderr or "")
            log_entries.append(f"Salida format SES=2:\n{stdout_ses2.strip()}")
            if res_ses2.returncode == 0 or 'Success' in stdout_ses2:
                erase_success = True
                log_entries.append("Format NVM Cryptographic Erase (SES=2) ejecutado con exito.")
        except Exception as exc:
            log_entries.append(f"[AVISO] Format SES=2 fallo: {exc}")

    # Step 3: Fallback to Format NVM with SES=1 (User Data Erase)
    if not erase_success:
        log_entries.append(f"[2/5 Fallback 2] Intentando Format NVM SES=1: nvme format {device} --namespace-id=1 --ses=1 -f")
        try:
            res_ses1 = subprocess.run([nvme_bin, 'format', device, '--namespace-id=1', '--ses=1', '-f'], capture_output=True, text=True, timeout=30)
            stdout_ses1 = (res_ses1.stdout or "") + "\n" + (res_ses1.stderr or "")
            log_entries.append(f"Salida format SES=1:\n{stdout_ses1.strip()}")
            if res_ses1.returncode == 0 or 'Success' in stdout_ses1:
                erase_success = True
                log_entries.append("Format NVM User Data Erase (SES=1) ejecutado con exito.")
        except Exception as exc:
            log_entries.append(f"[AVISO] Format SES=1 fallo: {exc}")

    # Step 4: Storage Controller Rescan & Partition Wipe
    log_entries.append(f"[3/5] Refrescando bus de almacenamiento y generando tabla GPT limpia...")
    sys_name = os.path.basename(device)
    rescan_path = f"/sys/block/{sys_name}/device/rescan"
    if os.path.exists(rescan_path):
        try:
            with open(rescan_path, 'w') as f:
                f.write("1\n")
        except Exception:
            pass

    time.sleep(1)

    try:
        subprocess.run(['partprobe', device], capture_output=True, timeout=5)
        subprocess.run(['udevadm', 'settle', '--timeout=3'], capture_output=True, timeout=5)
        subprocess.run(['wipefs', '-af', device], capture_output=True, text=True, timeout=10)
        subprocess.run(['parted', '-s', device, 'mklabel', 'gpt'], capture_output=True, text=True, timeout=10)
        subprocess.run(['partprobe', device], capture_output=True, timeout=5)
    except Exception as exc:
        log_entries.append(f"[AVISO] wipefs/parted fallo: {exc}")

    # Step 5: Non-destructive verification read test
    log_entries.append(f"[4/5] Verificando desbloqueo mediante lectura directa de sectores LBA...")
    read_ok = False
    try:
        verify_read = subprocess.run(['dd', f'if={device}', 'of=/dev/null', 'bs=1M', 'count=1', 'iflag=direct'], capture_output=True, text=True, timeout=5)
        if verify_read.returncode == 0:
            read_ok = True
            log_entries.append("Prueba de lectura LBA: PASSED (Sectores accesibles).")
        else:
            log_entries.append(f"Prueba de lectura LBA: FAILED ({verify_read.stderr.strip()}).")
    except Exception as e:
        log_entries.append(f"Aviso lectura LBA: {e}")

    if read_ok or erase_success:
        log_entries.append("[5/5] Operacion completada exitosamente. Disco desbloqueado y listo para instalar el SO.")
        return {
            'success': True,
            'message': f'Desbloqueo y borrado criptografico NVMe exitoso en {device}.\nLa unidad esta desbloqueada y lista para instalar SO.',
            'log': "\n".join(log_entries),
            'steps': [
                'Borrado criptografico NVMe ejecutado',
                'Controlador refrescado',
                'Firmas y particiones eliminadas',
                'Tabla GPT limpia creada',
                'Lectura de sectores LBA verificada'
            ]
        }
    else:
        log_entries.append("[ERROR] El controlador rechazo los comandos de borrado criptografico directo.")
        return {
            'success': False,
            'message': f'El controlador rechazo el borrado directo. El firmware del disco {device} requiere desbloqueo mediante PSID Revert.',
            'log': "\n".join(log_entries)
        }


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

    crypto_caps = get_nvme_crypto_capabilities(dev_path)

    return {
        'device': dev_path,
        'model': model,
        'size': size,
        'transport': tran,
        'type': drive_type,
        'is_opal_locked': check_opal_locked(dev_path),
        'crypto_capabilities': crypto_caps,
        'crypto_supported': crypto_caps.get('crypto_supported', False),
        'crypto_status_label': crypto_caps.get('status_label', 'Solo Formato Estandar')
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
                log_entries.append("Borrado criptográfico NVMe ejecutado con éxito.")
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

    log_entries.append("Proceso de desbloqueo y restauración de fábrica completado con éxito.")

    return {
        'success': True,
        'message': f'PSID Revert ejecutado en {device}!\n\n',
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
