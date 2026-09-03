#!/bin/bash
# ==============================================================================
# Hardware Diagnostic Suite - Auto Launcher Script for Linux Live OS
# Auto-starts the local Python REST server and launches Firefox in Application Mode
# ==============================================================================

# ── 1. Strict Bios Security Check (SecureBoot + TPM 2.0) ─────────────
# ── 1. Strict Bios Security Check (SecureBoot + TPM 2.0) ─────────────
check_secureboot() {
    for sb_var in /sys/firmware/efi/efivars/SecureBoot-*; do
        [ -f "$sb_var" ] || continue
        val=$(tail -c 1 "$sb_var" 2>/dev/null | od -An -tx1 | tr -d ' \n')
        [ "$val" = "01" ] && return 0
    done

    if command -v mokutil >/dev/null 2>&1; then
        mokutil --sb-state 2>/dev/null | grep -qi "SecureBoot enabled" && return 0
    fi

    if dmesg 2>/dev/null | grep -qi "Secure boot enabled"; then
        return 0
    fi

    return 1
}

check_tpm2() {
    if [ -d /sys/class/tpm/tpm0 ] || [ -c /dev/tpm0 ] || [ -c /dev/tpmrm0 ]; then
        return 0
    fi
    if command -v tpm2_getcap >/dev/null 2>&1; then
        tpm2_getcap properties-fixed >/dev/null 2>&1 && return 0
    fi
    return 1
}

SB_OK=0
TPM_OK=0
check_secureboot && SB_OK=1
check_tpm2       && TPM_OK=1

if [ "$SB_OK" -eq 0 ] || [ "$TPM_OK" -eq 0 ]; then
    SHOW_ERR="========================================================================\n [ERROR] DIAGNOSTDONOR: CONTROL DE CALIDAD - SEGURIDAD EN BIOS\n========================================================================\n\n"
    if [ "$SB_OK" -eq 1 ]; then
        SHOW_ERR="${SHOW_ERR}   [  OK  ] UEFI SECURE BOOT : ACTIVADO\n"
    else
        SHOW_ERR="${SHOW_ERR}   [FAIL] UEFI SECURE BOOT : DESACTIVADO (Requerido)\n"
    fi

    if [ "$TPM_OK" -eq 1 ]; then
        SHOW_ERR="${SHOW_ERR}   [  OK  ] MODULO TPM 2.0   : ACTIVADO\n"
    else
        SHOW_ERR="${SHOW_ERR}   [FAIL] MODULO TPM 2.0   : DESACTIVADO (Requerido)\n"
    fi
    SHOW_ERR="${SHOW_ERR}\n------------------------------------------------------------------------\n [REQUISITO BLOQUEANTE]: El sistema de diagnostico NO cargara\n    hasta que actives SECURE BOOT y TPM 2.0 en la BIOS.\n========================================================================\n\n Reiniciando el equipo en 10 segundos..."

    clear
    printf "$SHOW_ERR\n"

    sleep 10
    reboot -f 2>/dev/null || { echo 1 > /proc/sys/kernel/sysrq && echo b > /proc/sysrq-trigger; }
    exit 1
fi

export WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$SCRIPT_DIR/app" ]; then
    APP_DIR="$SCRIPT_DIR/app"
elif [ -d "$SCRIPT_DIR/../app" ]; then
    APP_DIR="$(cd "$SCRIPT_DIR/../app" && pwd)"
else
    APP_DIR="/opt/qa_suite/app"
fi

export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-/root/.Xauthority}"

# Redimensionar /dev/shm y preparar ZRAM para evitar OOM/SIGKILL (Error code 9) en Live OS
mount -o remount,size=2G /dev/shm 2>/dev/null || true
modprobe zram 2>/dev/null || true
if command -v zramctl >/dev/null 2>&1; then
    (zramctl --find --size 2G && mkswap /dev/zram0 && swapon /dev/zram0 -p 32767) 2>/dev/null || true
fi

echo "[INICIO] Iniciando Suite de Diagnostico de Hardware (ThinkPad & EliteBook QA)..."

# Preparar módulos de drivers Wi-Fi modernos, GPU y puertos Type-C/HDMI ThinkPad T14 Gen 5/6 en paralelo
for mod in thinkpad_acpi intel_vsec ucsi_acpi typec typec_displayport thunderbolt xe i915 amdgpu drm_kms_helper iwlwifi iwlmvm ath12k_pci ath12k ath11k_pci ath11k rtw89_8852be rtw89_8852ce rtw89_8922ae rtw89_pci rtw89_core mt7921e mt7922e mt7925e rtw88_8822ce; do
  modprobe "$mod" 2>/dev/null &
done

# Despertar y forzar escaneo de conectores de pantalla X11
xrandr --auto 2>/dev/null || true

# Preparar audio, Touchpad y Wi-Fi
rfkill unblock all 2>/dev/null || true
rfkill unblock wifi 2>/dev/null || true
rfkill unblock wlan 2>/dev/null || true
for wlan_dev in /sys/class/net/wl*; do
  if [ -d "$wlan_dev" ]; then
    ip link set "$(basename "$wlan_dev")" up 2>/dev/null || true
  fi
done

systemctl start NetworkManager 2>/dev/null || NetworkManager 2>/dev/null || true
nmcli radio wifi on 2>/dev/null || true
(sleep 0.5 && nmcli dev wifi rescan >/dev/null 2>&1 &)

for dev in $(xinput list --name-only 2>/dev/null | grep -iE 'touchpad|synaptics|trackpad|glidepoint|elan'); do
  xinput set-prop "$dev" "libinput Natural Scrolling Enabled" 1 2>/dev/null || true
  xinput set-prop "$dev" "libinput Tapping Enabled" 1 2>/dev/null || true
done

amixer sset Master unmute 100% 2>/dev/null || true
amixer sset Speaker unmute 100% 2>/dev/null || true
amixer sset Headphone unmute 100% 2>/dev/null || true
amixer sset PCM unmute 100% 2>/dev/null || true
amixer sset Capture cap 100% unmute 2>/dev/null || true
amixer sset 'Capture',0 100% unmute 2>/dev/null || true
amixer sset Mic 100% unmute 2>/dev/null || true
amixer sset 'Internal Mic' 100% unmute 2>/dev/null || true
pactl set-source-mute @DEFAULT_SOURCE@ 0 2>/dev/null || true
pactl set-source-volume @DEFAULT_SOURCE@ 100% 2>/dev/null || true

# Kill any previous server instances on port 8080
fuser -k 8080/tcp >/dev/null 2>&1 || true

# Start backend HTTP server in background
python3 "$APP_DIR/server.py" > /tmp/qa_server.log 2>&1 &
SERVER_PID=$!

# Wait for server to initialize and verify readiness
for i in $(seq 1 40); do
  if curl -s http://127.0.0.1:8080/ >/dev/null 2>&1; then
    break
  fi
  sleep 0.05
done

# Chrome flags: Kiosk real + sin barras de advertencia ni scroll + estabilidad de memoria en Linux Live
rm -rf /tmp/chrome-profile
CHROME_FLAGS="
  --no-sandbox
  --disable-gpu-sandbox
  --disable-dev-shm-usage
  --test-type
  --user-data-dir=/tmp/chrome-profile
  --kiosk
  --start-fullscreen
  --use-fake-ui-for-media-stream
  --autoplay-policy=no-user-gesture-required
  --disable-gesture-requirement-for-media-playback
  --allow-insecure-localhost
  --unsafely-treat-insecure-origin-as-secure=http://127.0.0.1:8080,http://localhost:8080
  --disable-dev-tools
  --disable-features=ChromeWhatsNewUI,Translate,MediaRouter,InPrivateNotification
  --disable-translate
  --disable-infobars
  --no-first-run
  --no-default-browser-check
  --disable-background-networking
  --disable-client-side-phishing-detection
  --disable-sync
  --disable-extensions
  --disable-breakpad
  --disable-renderer-backgrounding
  --disable-backgrounding-occluded-windows
  --disk-cache-size=1
  --media-cache-size=1
"

# Detect installed browser - Google Chrome (bundled en la ISO)
CHROME_BIN=""
if command -v google-chrome >/dev/null 2>&1; then
    CHROME_BIN="google-chrome"
elif command -v google-chrome-stable >/dev/null 2>&1; then
    CHROME_BIN="google-chrome-stable"
elif [ -x /opt/google/chrome/google-chrome ]; then
    CHROME_BIN="/opt/google/chrome/google-chrome"
elif [ -x /usr/bin/google-chrome-stable ]; then
    CHROME_BIN="/usr/bin/google-chrome-stable"
elif [ -x /usr/bin/google-chrome ]; then
    CHROME_BIN="/usr/bin/google-chrome"
elif command -v chromium-browser >/dev/null 2>&1; then
    CHROME_BIN="chromium-browser"
elif command -v chromium >/dev/null 2>&1; then
    CHROME_BIN="chromium"
fi

if [ -n "$CHROME_BIN" ]; then
    echo "[INFO] Abriendo interfaz en $CHROME_BIN (Kiosk Mode)..."
    while kill -0 "$SERVER_PID" 2>/dev/null; do
        "$CHROME_BIN" $CHROME_FLAGS http://127.0.0.1:8080
        sleep 0.5
    done
else
    echo "[AVISO] No se encontro Chrome ni Chromium. Abre manualmente: http://127.0.0.1:8080"
    wait $SERVER_PID
fi
