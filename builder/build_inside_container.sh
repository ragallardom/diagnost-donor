#!/bin/bash
# ==============================================================================
# build_inside_container.sh
# Compilacion de ISO Linux Live dentro del contenedor Ubuntu 24.04
# DEBIAN_FRONTEND=noninteractive para evitar pausas o preguntas interactivas
# ==============================================================================
set -e

export DEBIAN_FRONTEND=noninteractive
export TZ=UTC

WORK_DIR="$(pwd)"

# ── 0. Detección dinámica y auto-incremento de versión ───────────────
get_latest_iso_version() {
  local iso_versions=()
  
  if [ -d "$WORK_DIR/ISOs" ]; then
    for f in "$WORK_DIR/ISOs"/*.iso; do
      [ -f "$f" ] || continue
      ver=$(echo "$(basename "$f")" | grep -oP '\d+\.\d+\.\d+' || true)
      [ -n "$ver" ] && iso_versions+=("$ver")
    done
  fi

  if [ ${#iso_versions[@]} -eq 0 ]; then
    echo ""
    return
  fi

  printf '%s\n' "${iso_versions[@]}" | sort -V | tail -n 1
}

get_app_version() {
  local ver=""
  if [ -f "$WORK_DIR/builder/VERSION" ]; then
    ver=$(cat "$WORK_DIR/builder/VERSION" | tr -d ' \n\r' | grep -oP '\d+\.\d+\.\d+' || true)
  elif [ -f "$WORK_DIR/VERSION" ]; then
    ver=$(cat "$WORK_DIR/VERSION" | tr -d ' \n\r' | grep -oP '\d+\.\d+\.\d+' || true)
  fi

  if [ -z "$ver" ] && [ -f "$WORK_DIR/app/static/index.html" ]; then
    ver=$(grep -oP 'v\K\d+\.\d+\.\d+' "$WORK_DIR/app/static/index.html" | head -n 1 || true)
  fi

  [ -z "$ver" ] && ver="1.0.0"
  echo "$ver"
}

increment_version() {
  local current_ver="$1"
  local major minor patch
  IFS='.' read -r major minor patch <<< "$current_ver"
  patch=$((patch + 1))
  echo "${major}.${minor}.${patch}"
}

version_gt() {
  [ -z "$1" ] && return 1
  [ -z "$2" ] && return 0
  [ "$1" = "$2" ] && return 1
  local higher
  higher=$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -n 1)
  [ "$higher" = "$1" ]
}

LATEST_ISO_VERSION=$(get_latest_iso_version)
CURRENT_APP_VERSION=$(get_app_version)

if [ -n "$LATEST_ISO_VERSION" ]; then
  # Si la versión actual del código ya es mayor que la última ISO en ISOs/, no sumar y usarla directamente
  if version_gt "$CURRENT_APP_VERSION" "$LATEST_ISO_VERSION"; then
    NEW_VERSION="$CURRENT_APP_VERSION"
  else
    # Si no es mayor, la nueva versión es +1 respecto a la última ISO creada
    NEW_VERSION=$(increment_version "$LATEST_ISO_VERSION")
  fi
else
  # Si aún no existe ninguna ISO en ISOs/, usar la versión del programa o 1.0.0
  NEW_VERSION="$CURRENT_APP_VERSION"
fi

ISO_NAME="diagnost-donor_${NEW_VERSION}_linux-live.iso"
VOL_ID="diagnost-donor_${NEW_VERSION}_linux-live"
# Asegurar limite maximo de 32 caracteres para Volume ID estandar ISO9660
[ ${#VOL_ID} -gt 32 ] && VOL_ID="${VOL_ID:0:32}"

# Guardar versión actualizada en archivo builder/VERSION
echo "$NEW_VERSION" > "$WORK_DIR/builder/VERSION"

# Actualizar versión en index.html de la app
if [ -f "$WORK_DIR/app/static/index.html" ]; then
  sed -i -E "s/>v[0-9]+\.[0-9]+\.[0-9]+</>v${NEW_VERSION}</g" "$WORK_DIR/app/static/index.html"
  sed -i -E "s/\(v[0-9]+\.[0-9]+\.[0-9]+\)/\(v${NEW_VERSION}\)/g" "$WORK_DIR/app/static/index.html"
fi

BUILD_DIR="/tmp/live-iso-build"
mkdir -p "$WORK_DIR/builder" "$WORK_DIR/ISOs"
LOG_FILE="$WORK_DIR/builder/build_output.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "================================================================="
echo "  🔒 COMPILANDO ISO LINUX LIVE"
if [ -n "$LATEST_ISO_VERSION" ]; then
  echo "  🏷️ ÚLTIMA ISO EN ISOs/ : v$LATEST_ISO_VERSION"
else
  echo "  🏷️ ÚLTIMA ISO EN ISOs/ : (ninguna)"
fi
echo "  📦 VERSIÓN DEL PROGRAMA: v$CURRENT_APP_VERSION"
echo "  🚀 VERSIÓN A COMPILAR  : v$NEW_VERSION ($ISO_NAME)"
echo "  📋 REGISTRO (LOG)      : $LOG_FILE"
echo "================================================================="


# ── 0. Configurar certificados SSL y repositorios HTTPS ───────────────
if [ -f /tmp/host-ca-bundle.crt ]; then
  mkdir -p /etc/ssl/certs
  cp /tmp/host-ca-bundle.crt /etc/ssl/certs/ca-certificates.crt
fi

if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
  sed -i "s|http://|https://|g" /etc/apt/sources.list.d/ubuntu.sources
elif [ -f /etc/apt/sources.list ]; then
  sed -i "s|http://|https://|g" /etc/apt/sources.list
fi

# ── 1. Instalar herramientas de compilacion ──────────────────────────
apt-get update -q
apt-get install -y --no-install-recommends \
  live-build debootstrap xorriso squashfs-tools binutils dpkg-dev \
  mtools syslinux-utils isolinux syslinux-common \
  syslinux shim-signed grub-efi-amd64-signed grub-common dosfstools ca-certificates zstd pigz xz-utils

# isohybrid fix: asegurarse que isohybrid este disponible en todos los PATHs del sistema y chroot
if [ -f /usr/bin/isohybrid ]; then
  ln -sf /usr/bin/isohybrid /bin/isohybrid 2>/dev/null || true
  ln -sf /usr/bin/isohybrid /usr/local/bin/isohybrid 2>/dev/null || true
elif [ -f /usr/lib/syslinux/isohybrid ]; then
  ln -sf /usr/lib/syslinux/isohybrid /usr/bin/isohybrid
  ln -sf /usr/lib/syslinux/isohybrid /bin/isohybrid 2>/dev/null || true
  ln -sf /usr/lib/syslinux/isohybrid /usr/local/bin/isohybrid 2>/dev/null || true
fi

# ── 2. Limpieza TOTAL de cache viejo ─────────────────────────────────
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

lb clean --purge 2>/dev/null || true

# ── 3. Configurar live-build (GRUB EFI + isolinux manual para ISO-Hybrid universal) ──
# Nota: --bootloader grub-efi evita el error de paquetes syslinux-themes-ubuntu
# obsoletos en Noble. El arranque BIOS/MBR via isolinux se configura manualmente.
lb config \
  --architectures amd64 \
  --distribution noble \
  --mode ubuntu \
  --archive-areas "main restricted universe multiverse" \
  --parent-mirror-bootstrap "https://archive.ubuntu.com/ubuntu" \
  --parent-mirror-chroot "https://archive.ubuntu.com/ubuntu" \
  --parent-mirror-binary "https://archive.ubuntu.com/ubuntu" \
  --mirror-bootstrap "https://archive.ubuntu.com/ubuntu" \
  --mirror-chroot "https://archive.ubuntu.com/ubuntu" \
  --mirror-binary "https://archive.ubuntu.com/ubuntu" \
  --parent-mirror-chroot-security "https://security.ubuntu.com/ubuntu" \
  --parent-mirror-binary-security "https://security.ubuntu.com/ubuntu" \
  --mirror-chroot-security "https://security.ubuntu.com/ubuntu" \
  --mirror-binary-security "https://security.ubuntu.com/ubuntu" \
  --binary-images iso \
  --bootloader grub-efi \
  --iso-volume "$VOL_ID" \
  --memtest none \
  --initramfs initramfs-tools \
  --bootappend-live "boot=live live-media-path=/live scan-delay=1 rootdelay=1 username=root quiet splash loglevel=3 modprobe.blacklist=nvidia_gpu drm.kms_helper.poll=1 xe.force_probe=* i915.force_probe=*" \
  --apt-secure false \
  --apt-options "--yes --no-install-recommends -o Dpkg::Options::=--force-confnew"

# ── 4. Lista de paquetes del chroot ──────────────────────────────────
# Paquetes optimizados: openbox mínimo en lugar de XFCE completo
# para arranque ultra-rápido tipo WinPE (~15-20s)
mkdir -p config/package-lists
cat > config/package-lists/qa-suite.list.chroot << 'PKGEOF'
# Boot/arranque con soporte de hardware completo (Kernel OEM + Generic + Drivers)
linux-oem-24.04d
linux-image-oem-24.04d
linux-generic
linux-image-generic
live-boot
live-config
live-config-systemd
# Gráficos mínimos (openbox en vez de XFCE)
xorg
openbox
dbus-x11
x11-xserver-utils
gnupg
ca-certificates
# Firewall: bloquea todo el tráfico IP salvo loopback (kiosk sin red)
nftables
# Dependencias completas para Google Chrome (Ubuntu 24.04 noble)
fonts-liberation
fonts-dejavu-core
libnss3
libnspr4
libgbm1
libvulkan1
xdg-utils
libgtk-3-0t64
libatk1.0-0t64
libatk-bridge2.0-0t64
libcups2t64
libasound2t64
libasound2-plugins
libxcomposite1
libxdamage1
libxrandr2
libxfixes3
libxext6
libx11-6
libxcb1
libxkbcommon0
libdrm2
libexpat1
# Red y Wi-Fi (auto-configuración sin GUI)
network-manager
wpasupplicant
wireless-regdb
iw
rfkill
# Firmware y microcódigos de procesador (Intel Core Ultra / AMD Ryzen / Wi-Fi 7)
linux-firmware
firmware-sof-signed
intel-microcode
amd64-microcode
# Audio completo (PipeWire + ALSA UCM para chips Intel SOF / AMD ACP)
alsa-utils
alsa-ucm-conf
pipewire
pipewire-pulse
wireplumber
pulseaudio-utils
# Hardware testing & disk unlock tools
xinput
tpm2-tools
mokutil
nvme-cli
smartmontools
parted
util-linux
zenity
python3
lm-sensors
upower
evtest
acpi
pciutils
usbutils
lshw
hwinfo
dmidecode
v4l-utils
psmisc
# Benchmark & Stress tools
stress-ng
memtester
fio
# Bluetooth & Wireless OBEX Sharing
bluez
bluez-obexd
PKGEOF

# ── 4b. Instalar Google Chrome y paquetes desde Aplicaciones/ ──
# 1) Desempaquetar binarios directamente en includes.chroot/ (garantiza presencia de Chrome en ISO)
# 2) Registrar paquete con dpkg en el hook de chroot para corregir dependencias
CHROME_DEB=""
for p in \
  "$WORK_DIR/Aplicaciones/google-chrome-stable_current_amd64.deb" \
  "/work/Aplicaciones/google-chrome-stable_current_amd64.deb" \
  "$WORK_DIR/google-chrome-stable_current_amd64.deb" \
  "/work/google-chrome-stable_current_amd64.deb" \
  "$(pwd)/Aplicaciones/google-chrome-stable_current_amd64.deb" \
  "$(pwd)/google-chrome-stable_current_amd64.deb"; do
  if [ -n "$p" ] && [ -f "$p" ]; then
    CHROME_DEB="$p"
    break
  fi
done

if [ -n "$CHROME_DEB" ]; then
  echo "✅ Encontrado Google Chrome .deb en: $CHROME_DEB"
  echo "📦 Desempaquetando binarios de Chrome directamente en config/includes.chroot..."
  mkdir -p config/includes.chroot/usr/bin config/includes.chroot/tmp config/includes.chroot/tmp/extra_debs

  if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb -x "$CHROME_DEB" config/includes.chroot/
  elif command -v ar >/dev/null 2>&1; then
    ar p "$CHROME_DEB" data.tar.xz | tar -xJ -C config/includes.chroot/
  else
    python3 -c "
import tarfile, io
with open('$CHROME_DEB', 'rb') as f: data = f.read()
offset = 8
while offset < len(data):
    header = data[offset:offset+60]
    if len(header) < 60: break
    name = header[:16].strip().decode('ascii', 'ignore')
    size = int(header[48:58].strip())
    content = data[offset+60:offset+60+size]
    offset += 60 + size + (size % 2)
    if 'data.tar' in name:
        with tarfile.open(fileobj=io.BytesIO(content)) as tar:
            tar.extractall('config/includes.chroot')
        break
"
  fi

  cp "$CHROME_DEB" config/includes.chroot/tmp/chrome.deb
  
  # Garantizar enlaces simbólicos en /usr/bin/
  ln -sf /opt/google/chrome/google-chrome config/includes.chroot/usr/bin/google-chrome
  ln -sf /opt/google/chrome/google-chrome config/includes.chroot/usr/bin/google-chrome-stable

  if [ -f config/includes.chroot/opt/google/chrome/google-chrome ]; then
    echo "✅ Binario /opt/google/chrome/google-chrome verificado exitosamente en includes.chroot!"
  else
    echo "❌ ERROR CRÍTICO: Falló la extracción de los binarios de Chrome."
    exit 1
  fi
else
  echo "❌ ERROR CRÍTICO: No se encontró google-chrome-stable_current_amd64.deb"
  echo "   Buscado en: $WORK_DIR/Aplicaciones/, $WORK_DIR y /work"
  exit 1
fi

# Copiar certificados SSL a includes.chroot para que las descargas HTTPS dentro del chroot funcionen
mkdir -p config/includes.chroot/etc/ssl/certs
if [ -f /etc/ssl/certs/ca-certificates.crt ]; then
  cp /etc/ssl/certs/ca-certificates.crt config/includes.chroot/etc/ssl/certs/ca-certificates.crt
fi

# Copiar cualquier otro archivo .deb adicional colocado en Aplicaciones/
if [ -d "$WORK_DIR/Aplicaciones" ]; then
  for extra_deb in "$WORK_DIR/Aplicaciones"/*.deb; do
    if [ -f "$extra_deb" ] && [ "$(basename "$extra_deb")" != "google-chrome-stable_current_amd64.deb" ]; then
      echo "📦 Agregando paquete adicional desde Aplicaciones/: $(basename "$extra_deb")"
      cp "$extra_deb" config/includes.chroot/tmp/extra_debs/
    fi
  done

  # Instalar psid-unlocker CLI utility en /usr/local/bin si está disponible
  PSID_SCRIPT=""
  for s in "$WORK_DIR/Aplicaciones/psid-unlocker_/bin/psid-unlocker" "$WORK_DIR/Aplicaciones/psid-unlocker"; do
    if [ -f "$s" ]; then
      PSID_SCRIPT="$s"
      break
    fi
  done

  if [ -n "$PSID_SCRIPT" ]; then
    echo "📦 Instalando herramienta CLI psid-unlocker en /usr/local/bin/..."
    mkdir -p config/includes.chroot/usr/local/bin config/includes.chroot/usr/share/applications config/includes.chroot/etc/sudoers.d
    cp "$PSID_SCRIPT" config/includes.chroot/usr/local/bin/psid-unlocker
    chmod +x config/includes.chroot/usr/local/bin/psid-unlocker
    cat << 'DESKTOPEOF' > config/includes.chroot/usr/share/applications/psid-unlocker.desktop
[Desktop Entry]
Version=1.0
Type=Application
Name=PSID Unlocker & Eraser
Comment=Desbloquear y resetear de fábrica SSDs con cifrado SED/Opal
Exec=sudo /usr/local/bin/psid-unlocker
Icon=drive-harddisk-system
Terminal=true
Categories=System;Utility;
Keywords=psid;sedutil;ssd;erase;unlock;opal;
DESKTOPEOF
    echo "%sudo ALL=(ALL) NOPASSWD: /usr/local/bin/psid-unlocker" > config/includes.chroot/etc/sudoers.d/psid-unlocker
  fi
fi

# ── 4c. Instalar binario sedutil-cli para soporte TCG Opal / PSID ──
SEDUTIL_BIN=""
for b in \
  "$WORK_DIR/builder/bin/sedutil-cli" \
  "/work/builder/bin/sedutil-cli" \
  "$WORK_DIR/bin/sedutil-cli" \
  "/work/bin/sedutil-cli" \
  "$(pwd)/bin/sedutil-cli" \
  "/tmp/build_sedutil/sedutil/sedutil-cli"; do
  if [ -f "$b" ]; then
    SEDUTIL_BIN="$b"
    break
  fi
done

if [ -n "$SEDUTIL_BIN" ]; then
  echo "📦 Instalando binario sedutil-cli desde: $SEDUTIL_BIN"
  mkdir -p config/includes.chroot/usr/local/bin config/includes.chroot/usr/bin
  cp "$SEDUTIL_BIN" config/includes.chroot/usr/local/bin/sedutil-cli
  chmod +x config/includes.chroot/usr/local/bin/sedutil-cli
  ln -sf /usr/local/bin/sedutil-cli config/includes.chroot/usr/bin/sedutil-cli
else
  echo "⚠️ sedutil-cli no encontrado localmente. Compilando desde código fuente..."
  mkdir -p /tmp/sedutil_src
  if git clone --depth 1 https://github.com/Drive-Trust-Alliance/sedutil.git /tmp/sedutil_src/sedutil 2>/dev/null; then
    (cd /tmp/sedutil_src/sedutil && autoreconf -i -f && ./configure && make && strip sedutil-cli) || true
    if [ -f /tmp/sedutil_src/sedutil/sedutil-cli ]; then
      mkdir -p config/includes.chroot/usr/local/bin config/includes.chroot/usr/bin
      cp /tmp/sedutil_src/sedutil/sedutil-cli config/includes.chroot/usr/local/bin/sedutil-cli
      chmod +x config/includes.chroot/usr/local/bin/sedutil-cli
      ln -sf /usr/local/bin/sedutil-cli config/includes.chroot/usr/bin/sedutil-cli
      echo "✅ sedutil-cli compilado e instalado con éxito."
    fi
    rm -rf /tmp/sedutil_src
  fi
fi

# Hook de chroot (directorio correcto config/hooks/chroot/)
mkdir -p config/hooks/chroot config/hooks/normal config/hooks
cat > config/hooks/chroot/0050-install-chrome.hook.chroot << 'HOOKEOF'
#!/bin/sh
set -e
echo "========================================================"
echo "🌐 VERIFICANDO E INSTALANDO GOOGLE CHROME EN CHROOT..."
echo "========================================================"
if [ -f /tmp/chrome.deb ]; then
  apt-get update -q || true
  dpkg -i /tmp/chrome.deb || apt-get install -y --fix-broken || true
  rm -f /tmp/chrome.deb
fi

# Instalar cualquier paquete adicional colocado en Aplicaciones/
if [ -d /tmp/extra_debs ] && ls /tmp/extra_debs/*.deb >/dev/null 2>&1; then
  echo "📦 Instalando paquetes adicionales desde /tmp/extra_debs/..."
  dpkg -i /tmp/extra_debs/*.deb || apt-get install -y --fix-broken || true
  rm -rf /tmp/extra_debs
fi

if command -v google-chrome >/dev/null 2>&1 || [ -f /usr/bin/google-chrome ] || [ -f /opt/google/chrome/google-chrome ]; then
  echo "✅ Google Chrome verificado e instalado con éxito en el chroot."
else
  echo "❌ ERROR CRÍTICO: Falló la instalación de Google Chrome."
  exit 1
fi
HOOKEOF

chmod +x config/hooks/chroot/0050-install-chrome.hook.chroot
cp config/hooks/chroot/0050-install-chrome.hook.chroot config/hooks/chroot/0050-install-chrome.chroot 2>/dev/null || true
cp config/hooks/chroot/0050-install-chrome.hook.chroot config/hooks/normal/0050-install-chrome.hook.chroot 2>/dev/null || true


# ── 5. Configurar COMPRESS=gzip en initramfs para evitar error cpio con zstd ──
mkdir -p config/includes.chroot/etc/initramfs-tools
cat > config/includes.chroot/etc/initramfs-tools/initramfs.conf << 'INITEof'
MODULES=most
BUSYBOX=auto
KEYMAP=n
COMPRESS=gzip
INITEof

# ── 6. Chromium / Chrome: políticas de kiosk ──────────────────────────
# - Auto-otorgar cámara, micrófono y audio solo a la app local.
# - Lista blanca de URL: solo se puede cargar http://127.0.0.1:8080 (ni webs,
#   ni file://, ni chrome://), sin diálogos de archivo, descargas, impresión,
#   DevTools, extensiones, perfiles ni modo incógnito.
# Chromium-browser usa /etc/chromium-browser/policies/managed/
# Google Chrome usa /etc/opt/chrome/policies/managed/
POLICY_JSON='{
  "URLBlocklist": ["*", "chrome://*", "chrome-untrusted://*", "chrome-extension://*", "devtools://*", "file://*", "view-source:*"],
  "URLAllowlist": ["http://127.0.0.1:8080", "http://localhost:8080"],
  "AllowFileSelectionDialogs": false,
  "DownloadRestrictions": 3,
  "PrintingEnabled": false,
  "IncognitoModeAvailability": 1,
  "BrowserGuestModeEnabled": false,
  "BrowserAddPersonEnabled": false,
  "BookmarkBarEnabled": false,
  "EditBookmarksEnabled": false,
  "ExtensionInstallBlocklist": ["*"],
  "TaskManagerEndProcessEnabled": false,
  "DefaultPopupsSetting": 2,
  "DefaultWebBluetoothGuardSetting": 2,
  "DefaultWebUsbGuardSetting": 2,
  "DefaultSerialGuardSetting": 2,
  "DefaultWebHidGuardSetting": 2,
  "AutofillAddressEnabled": false,
  "AutofillCreditCardEnabled": false,
  "SpellcheckEnabled": false,
  "SearchSuggestEnabled": false,
  "BrowserNetworkTimeQueriesEnabled": false,
  "PromotionalTabsEnabled": false,
  "BackgroundModeEnabled": false,
  "CommandLineFlagSecurityWarningsEnabled": false,
  "VideoCaptureAllowedUrls": ["http://localhost:8080", "http://127.0.0.1:8080"],
  "AudioCaptureAllowedUrls":  ["http://localhost:8080", "http://127.0.0.1:8080"],
  "DefaultGeolocationSetting": 2,
  "AutoplayAllowed": true,
  "AutoplayAllowlist": ["http://localhost:8080", "http://127.0.0.1:8080"],
  "TranslateEnabled": false,
  "DefaultCookiesSetting": 1,
  "DefaultNotificationsSetting": 2,
  "BrowserSignin": 0,
  "SyncDisabled": true,
  "MetricsReportingEnabled": false,
  "SafeBrowsingEnabled": false,
  "PasswordManagerEnabled": false,
  "DefaultSearchProviderEnabled": false,
  "DeveloperToolsAvailability": 2
}'

mkdir -p config/includes.chroot/etc/chromium-browser/policies/managed
echo "$POLICY_JSON" > config/includes.chroot/etc/chromium-browser/policies/managed/qa_policy.json

mkdir -p config/includes.chroot/etc/opt/chrome/policies/managed
echo "$POLICY_JSON" > config/includes.chroot/etc/opt/chrome/policies/managed/qa_policy.json

mkdir -p config/includes.chroot/etc/opt/chromium/policies/managed
echo "$POLICY_JSON" > config/includes.chroot/etc/opt/chromium/policies/managed/qa_policy.json

# ── 7. Auto-login + Auto-inicio directo (sin display manager) ────────
# Estrategia: systemd auto-login → .bash_profile → startx → openbox → app

# 7a. Auto-login como root en tty1 via systemd getty override
mkdir -p config/includes.chroot/etc/systemd/system/getty@tty1.service.d
cat > config/includes.chroot/etc/systemd/system/getty@tty1.service.d/autologin.conf << 'GEOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
GEOF

# 7b. .bash_profile de root y /etc/skel (para usuario live)
mkdir -p config/includes.chroot/root config/includes.chroot/etc/skel
cat > config/includes.chroot/root/.bash_profile << 'BPEOF'
#!/bin/bash
# Kiosk: esta sesión nunca debe quedar en una shell interactiva.
# Ignorar Ctrl+C / Ctrl+Z / Ctrl+\ para que no se pueda interrumpir el perfil.
trap '' INT QUIT TSTP
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  # Si X termina o falla, volver a iniciarlo en lugar de caer a la shell.
  # (Las señales se restauran para la sesión gráfica: el bloqueo solo aplica al perfil.)
  while true; do
    ( trap - INT QUIT TSTP; exec startx /root/.xinitrc > /tmp/startx.log 2>&1 )
    sleep 1
  done
fi
# Cualquier otro login (no debería existir): cerrar sin shell.
exit 0
BPEOF
cp config/includes.chroot/root/.bash_profile config/includes.chroot/etc/skel/.bash_profile

# 7c. .xinitrc: configura openbox como WM y lanza la app QA
cat > config/includes.chroot/root/.xinitrc << 'XIEOF'
#!/bin/bash
# Iniciar dbus session bus (necesario para Chrome)
if command -v dbus-launch >/dev/null 2>&1; then
  eval $(dbus-launch --sh-syntax)
fi

# Desactivar screensaver y power management
xset s off 2>/dev/null || true
xset -dpms 2>/dev/null || true
xset s noblank 2>/dev/null || true

# Ejecutar openbox como window manager
exec openbox-session
XIEOF
chmod +x config/includes.chroot/root/.xinitrc
cp config/includes.chroot/root/.xinitrc config/includes.chroot/etc/skel/.xinitrc

# 7c-2. Configuración Xorg de Touchpad: Desplazamiento Natural (Natural Scrolling)
mkdir -p config/includes.chroot/etc/X11/xorg.conf.d
cat > config/includes.chroot/etc/X11/xorg.conf.d/40-libinput.conf << 'XORGEOF'
Section "InputClass"
    Identifier "touchpad catchall"
    Driver "libinput"
    MatchIsTouchpad "on"
    MatchDevicePath "/dev/input/event*"
    Option "NaturalScrolling" "true"
    Option "Tapping" "on"
    Option "ClickMethod" "clickfinger"
    Option "MiddleEmulation" "true"
EndSection
XORGEOF

# 7c-3. Blindaje Xorg Kiosk: Deshabilitar cambio de terminales TTY (Ctrl+Alt+F1..F6) y cierre con Ctrl+Alt+Backspace
cat > config/includes.chroot/etc/X11/xorg.conf.d/10-kiosk-security.conf << 'XORGEOF'
Section "ServerFlags"
    Option "DontVTSwitch" "true"
    Option "DontZap" "true"
EndSection
XORGEOF

# 7d. Openbox autostart: desmutear audio, preparar radios y lanzar start_qa.sh (sin terminal visible)
mkdir -p config/includes.chroot/etc/xdg/openbox
cat > config/includes.chroot/etc/xdg/openbox/autostart << 'OBEOF'
#!/bin/bash
# Establecer fondo azul oscuro para evitar pantalla negra vacía
xsetroot -solid "#1e1e2e" 2>/dev/null || true
xset s off 2>/dev/null || true
xset -dpms 2>/dev/null || true

# 1. Desbloquear radio Wi-Fi e iniciar NetworkManager si es necesario
rfkill unblock all 2>/dev/null || true
systemctl start NetworkManager 2>/dev/null || NetworkManager 2>/dev/null || true

# 2. Configurar Touchpad con Desplazamiento Natural y Tap
for dev in $(xinput list --name-only 2>/dev/null | grep -iE 'touchpad|synaptics|trackpad|glidepoint|elan'); do
  xinput set-prop "$dev" "libinput Natural Scrolling Enabled" 1 2>/dev/null || true
  xinput set-prop "$dev" "libinput Tapping Enabled" 1 2>/dev/null || true
done

# 3. Desmutear todos los canales ALSA (Parlantes, Audífonos, Micrófonos)
amixer sset Master unmute 100% 2>/dev/null || true
amixer sset Speaker unmute 100% 2>/dev/null || true
amixer sset Headphone unmute 100% 2>/dev/null || true
amixer sset PCM unmute 100% 2>/dev/null || true
amixer sset Capture unmute 100% 2>/dev/null || true
amixer sset Mic unmute 100% 2>/dev/null || true
amixer sset 'Internal Mic' unmute 100% 2>/dev/null || true

# 4. Iniciar demonios de audio PipeWire / WirePlumber
pipewire >/tmp/pipewire.log 2>&1 &
pipewire-pulse >/tmp/pipewire-pulse.log 2>&1 &
wireplumber >/tmp/wireplumber.log 2>&1 &

# Esperar a que los servicios estén listos
sleep 0.4

# Lanzar el iniciador de diagnóstico en segundo plano (sin terminal: el kiosk no expone shell)
/opt/qa_suite/start_qa.sh > /tmp/qa_launcher.log 2>&1 &
OBEOF
chmod +x config/includes.chroot/etc/xdg/openbox/autostart

# 7e. Configuración de openbox: sin decoraciones innecesarias ni atajos que capturen teclas F1-F12
cat > config/includes.chroot/etc/xdg/openbox/rc.xml << 'RCEOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <resistance><strength>10</strength><screen_edge_strength>20</screen_edge_strength></resistance>
  <focus><followMouse>no</followMouse></focus>
  <theme><name>Clearlooks</name>
    <titleLayout>NLIMC</titleLayout>
    <keepBorder>no</keepBorder>
  </theme>
  <desktops><number>1</number></desktops>
  <!-- Kiosk: sin atajos de teclado (Alt+F4, Alt+Tab, etc. deshabilitados) -->
  <keyboard>
  </keyboard>
  <!-- Kiosk: solo enfocar/levantar ventanas con clic. Sin menú de escritorio
       (el menú por defecto de openbox permite abrir una terminal), sin
       mover/redimensionar/cerrar ventanas con el mouse. -->
  <mouse>
    <context name="Client">
      <mousebind button="Left" action="Press"><action name="Focus"/><action name="Raise"/></mousebind>
      <mousebind button="Middle" action="Press"><action name="Focus"/><action name="Raise"/></mousebind>
      <mousebind button="Right" action="Press"><action name="Focus"/><action name="Raise"/></mousebind>
    </context>
  </mouse>
  <menu>
    <file>/etc/xdg/openbox/menu.xml</file>
  </menu>
</openbox_config>
RCEOF

# Menú de openbox vacío (reemplaza el que trae "Terminal emulator")
cat > config/includes.chroot/etc/xdg/openbox/menu.xml << 'MENUEOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_menu xmlns="http://openbox.org/3.4/menu">
  <menu id="root-menu" label="DIAGNOSTDONOR">
  </menu>
</openbox_menu>
MENUEOF

# 7f. Configuración de NetworkManager: gestionar adaptadores Wi-Fi para permitir
#     el escaneo, pero sin crear conexiones automáticas (el kiosk no se conecta a
#     ninguna red; no se generan perfiles DHCP para Ethernet ni chequeos de conectividad).
mkdir -p config/includes.chroot/etc/NetworkManager/conf.d
cat > config/includes.chroot/etc/NetworkManager/conf.d/10-qa-wifi.conf << 'NMEOF'
[main]
no-auto-default=*

[connectivity]
enabled=false

[device]
wifi.scan-rand-mac-address=no

[keyfile]
unmanaged-devices=none
NMEOF

# 7g. Firewall nftables: descartar todo el tráfico IP que no sea loopback.
#     La UI (127.0.0.1:8080) sigue funcionando; el escaneo Wi-Fi, la detección de
#     enlace Ethernet y el test de loopback RJ-45 (tramas capa 2) no usan IP.
cat > config/includes.chroot/etc/nftables.conf << 'NFTEOF'
#!/usr/sbin/nft -f
flush ruleset

table inet diagnost_kiosk {
  chain input {
    type filter hook input priority filter; policy drop;
    iif "lo" accept
  }
  chain forward {
    type filter hook forward priority filter; policy drop;
  }
  chain output {
    type filter hook output priority filter; policy drop;
    oif "lo" accept
  }
}
NFTEOF
mkdir -p config/includes.chroot/etc/systemd/system/sysinit.target.wants
ln -sf /lib/systemd/system/nftables.service config/includes.chroot/etc/systemd/system/sysinit.target.wants/nftables.service

# 7h. Endurecimiento del sistema: sin IPv6, sin SysRq, sin forwarding
mkdir -p config/includes.chroot/etc/sysctl.d
cat > config/includes.chroot/etc/sysctl.d/99-diagnost-kiosk.conf << 'SYSCTLEOF'
kernel.sysrq = 0
net.ipv4.ip_forward = 0
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
SYSCTLEOF

# 7i. Sin consolas de texto adicionales: no se crean gettys en tty2..tty6,
#     Ctrl+Alt+Supr no reinicia y la shell de depuración queda deshabilitada.
mkdir -p config/includes.chroot/etc/systemd/logind.conf.d
cat > config/includes.chroot/etc/systemd/logind.conf.d/10-diagnost-kiosk.conf << 'LOGINDEOF'
[Login]
NAutoVTs=0
ReserveVT=0
LOGINDEOF
for unit in ctrl-alt-del.target debug-shell.service autovt@.service serial-getty@.service; do
  ln -sf /dev/null "config/includes.chroot/etc/systemd/system/$unit"
done

# 7j. Hook: eliminar emuladores de terminal que arrastran las dependencias de Xorg
#     (el metapaquete xorg depende de xterm) y asegurar el firewall activo.
cat > config/hooks/chroot/0060-kiosk-lockdown.hook.chroot << 'LOCKEOF'
#!/bin/sh
set -e
for term in xterm uxterm lxterm koi8rxterm x-terminal-emulator; do
  rm -f "/usr/bin/$term" "/etc/alternatives/$term"
done
rm -f /usr/share/applications/debian-xterm.desktop /usr/share/applications/debian-uxterm.desktop
systemctl enable nftables.service 2>/dev/null || true
LOCKEOF
chmod +x config/hooks/chroot/0060-kiosk-lockdown.hook.chroot
mkdir -p config/hooks/normal
cp config/hooks/chroot/0060-kiosk-lockdown.hook.chroot config/hooks/chroot/0060-kiosk-lockdown.chroot 2>/dev/null || true
cp config/hooks/chroot/0060-kiosk-lockdown.hook.chroot config/hooks/normal/0060-kiosk-lockdown.hook.chroot 2>/dev/null || true

# ── 8. Copiar código de la app ────────────────────────────────────────
mkdir -p config/includes.chroot/opt/qa_suite

START_QA_SRC=""
for sqa in "$WORK_DIR/builder/start_qa.sh" "$WORK_DIR/start_qa.sh" "$SCRIPT_DIR/start_qa.sh" "/work/builder/start_qa.sh"; do
  if [ -f "$sqa" ]; then
    START_QA_SRC="$sqa"
    break
  fi
done

if [ -z "$START_QA_SRC" ]; then
  echo "❌ ERROR CRÍTICO: No se encontró start_qa.sh (buscado en $WORK_DIR/builder/ y $WORK_DIR/)"
  exit 1
fi

echo "📦 Copiando aplicación y start_qa.sh ($START_QA_SRC)..."
cp -r "$WORK_DIR/app" config/includes.chroot/opt/qa_suite/
find config/includes.chroot/opt/qa_suite/app -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find config/includes.chroot/opt/qa_suite/app -name "*.pyc" -delete 2>/dev/null || true
cp "$START_QA_SRC" config/includes.chroot/opt/qa_suite/start_qa.sh
chmod +x config/includes.chroot/opt/qa_suite/start_qa.sh

# ── 9. Compilar la ISO base con live-build ────────────────────────────
# Con --binary-images iso, lb build NO ejecuta isohybrid internamente,
# evitando el error "could not find boot record" y el rollback de binary/.
# Nosotros creamos la ISO híbrida (USB-bootable) con xorriso después.
echo "🔨 Compilando la estructura de la ISO Live..."
lb build

# ── 10. Configurar arranque completo y crear ISO híbrida ─────────────
echo "🔧 Preparando ISO híbrida con arranque BIOS + UEFI + Secure Boot..."

BINARY_DIR="$BUILD_DIR/binary"
if [ ! -d "$BINARY_DIR" ]; then
  BINARY_DIR="binary"
fi

if [ ! -d "$BINARY_DIR" ]; then
  echo "❌ Error: No se generó el directorio binary/."
  ls -lah "$BUILD_DIR" 2>/dev/null || true
  exit 1
fi

CHROOT_DIR="$BUILD_DIR/chroot"

# ── 10a. Verificar que el sistema live se generó correctamente ───────
echo "🔍 Verificando sistema live generado..."
VMLINUZ=$(find "$BINARY_DIR" -name "vmlinuz*" -type f 2>/dev/null | sort -V | tail -n 1)
INITRD=$(find "$BINARY_DIR" \( -name "initrd*" -o -name "initramfs*" \) -type f 2>/dev/null | sort -V | tail -n 1)
SQUASHFS=$(find "$BINARY_DIR" -name "filesystem.squashfs" -type f 2>/dev/null | head -n 1)

if [ -z "$VMLINUZ" ]; then
  echo "❌ No se encontró vmlinuz en binary/"
  find "$BINARY_DIR" -type f 2>/dev/null | head -20
  exit 1
fi
if [ -z "$INITRD" ]; then
  echo "❌ No se encontró initrd en binary/"
  exit 1
fi

# Garantizar la presencia de /live y /casper con filesystem.squashfs
mkdir -p "$BINARY_DIR/live" "$BINARY_DIR/casper"
if [ -n "$SQUASHFS" ]; then
  if [ "$SQUASHFS" != "$BINARY_DIR/live/filesystem.squashfs" ]; then
    echo "  📦 Copiando filesystem.squashfs a /live/..."
    cp -f "$SQUASHFS" "$BINARY_DIR/live/filesystem.squashfs"
  fi
  if [ "$SQUASHFS" != "$BINARY_DIR/casper/filesystem.squashfs" ]; then
    echo "  📦 Copiando filesystem.squashfs a /casper/..."
    cp -f "$SQUASHFS" "$BINARY_DIR/casper/filesystem.squashfs"
  fi
fi

# Calcular rutas relativas al root del ISO
VMLINUZ_REL="/$(realpath --relative-to="$BINARY_DIR" "$VMLINUZ")"
INITRD_REL="/$(realpath --relative-to="$BINARY_DIR" "$INITRD")"
echo "  ✔ Kernel:   $VMLINUZ_REL"
echo "  ✔ Initrd:   $INITRD_REL"
echo "  ✔ SquashFS: /live/filesystem.squashfs"

# ── 10b. Configurar ISOLINUX (arranque BIOS / Legacy) ────────────────
echo "⚡ Configurando isolinux para arranque BIOS legacy..."
mkdir -p "$BINARY_DIR/isolinux"

# Copiar módulos de isolinux/syslinux desde el host
for mod in isolinux.bin ldlinux.c32 libutil.c32 libcom32.c32 vesamenu.c32 menu.c32; do
  src=""
  for dir in /usr/lib/ISOLINUX /usr/lib/syslinux/modules/bios /usr/share/syslinux; do
    [ -f "$dir/$mod" ] && { src="$dir/$mod"; break; }
  done
  [ -z "$src" ] && src=$(find /usr -name "$mod" 2>/dev/null | head -n 1)
  [ -n "$src" ] && cp "$src" "$BINARY_DIR/isolinux/"
done

# Crear isolinux.cfg con paths dinámicos descubiertos
cat > "$BINARY_DIR/isolinux/isolinux.cfg" << SYSEOF
DEFAULT live
TIMEOUT 5
PROMPT 0
# Kiosk: no permitir editar parámetros del kernel ni abrir la línea de comandos
NOESCAPE 1
ALLOWOPTIONS 0

LABEL live
  MENU LABEL Start Diagnost-Donor Live (Fast USB Boot)
  KERNEL $VMLINUZ_REL
  APPEND initrd=$INITRD_REL boot=live live-media-path=/live scan-delay=1 rootdelay=1 username=root quiet splash loglevel=3 modprobe.blacklist=nvidia_gpu drm.kms_helper.poll=1 xe.force_probe=* i915.force_probe=*

LABEL toram
  MENU LABEL Start Diagnost-Donor Live (Load to RAM - toram)
  KERNEL $VMLINUZ_REL
  APPEND initrd=$INITRD_REL boot=live toram live-media-path=/live scan-delay=1 rootdelay=1 username=root quiet splash loglevel=3 modprobe.blacklist=nvidia_gpu drm.kms_helper.poll=1 xe.force_probe=* i915.force_probe=*
SYSEOF

if [ -f "$BINARY_DIR/isolinux/isolinux.bin" ]; then
  echo "  ✔ isolinux configurado correctamente"
else
  echo "  ⚠ No se encontró isolinux.bin — sin arranque BIOS"
fi

# ── 10c. Configurar GRUB EFI + Secure Boot ───────────────────────────
echo "⚡ Configurando GRUB EFI con Secure Boot..."

mkdir -p "$BINARY_DIR/EFI/BOOT"
mkdir -p "$BINARY_DIR/boot/grub"

# Buscar shimx64.efi y grubx64.efi firmados (necesarios para Secure Boot)
SHIMX64=""
GRUBX64=""
MMX64=""

for search_dir in "$CHROOT_DIR/usr" "$BINARY_DIR" "/usr"; do
  [ ! -d "$search_dir" ] && continue
  [ -z "$SHIMX64" ] && SHIMX64=$(find "$search_dir" -name "shimx64.efi.signed" 2>/dev/null | head -n 1)
  [ -z "$SHIMX64" ] && SHIMX64=$(find "$search_dir" -name "shimx64.efi" 2>/dev/null | head -n 1)
  [ -z "$GRUBX64" ] && GRUBX64=$(find "$search_dir" -name "grubx64.efi.signed" 2>/dev/null | head -n 1)
  [ -z "$GRUBX64" ] && GRUBX64=$(find "$search_dir" -name "grubx64.efi" 2>/dev/null | head -n 1)
  [ -z "$MMX64" ] && MMX64=$(find "$search_dir" -name "mmx64.efi" -o -name "mmx64.efi.signed" 2>/dev/null | head -n 1)
done

if [ -n "$SHIMX64" ]; then
  cp "$SHIMX64" "$BINARY_DIR/EFI/BOOT/BOOTx64.EFI"
  echo "  ✔ Shim Secure Boot: $(basename "$SHIMX64")"
else
  echo "  ⚠ shimx64.efi no encontrado — Secure Boot no disponible"
fi

if [ -n "$GRUBX64" ]; then
  cp "$GRUBX64" "$BINARY_DIR/EFI/BOOT/grubx64.efi"
  echo "  ✔ GRUB EFI firmado: $(basename "$GRUBX64")"
  # Si no hay shim, usar GRUB directamente como bootloader EFI primario
  [ -z "$SHIMX64" ] && cp "$GRUBX64" "$BINARY_DIR/EFI/BOOT/BOOTx64.EFI"
else
  echo "  ⚠ grubx64.efi no encontrado"
fi

[ -n "$MMX64" ] && cp "$MMX64" "$BINARY_DIR/EFI/BOOT/mmx64.efi"

# Bloqueo de GRUB: las entradas arrancan sin contraseña (--unrestricted), pero editar
# parámetros ('e') o abrir la consola ('c') requiere el superusuario. Si no se define
# GRUB_ADMIN_PASSWORD al compilar, se usa una contraseña aleatoria que no se guarda
# (edición deshabilitada de forma permanente para esa ISO).
GRUB_LOCK=""
GRUB_ENTRY_FLAGS=""
GRUB_PW="${GRUB_ADMIN_PASSWORD:-$(head -c 32 /dev/urandom | base64 | tr -d '\n')}"
GRUB_PW_HASH=$(printf '%s\n%s\n' "$GRUB_PW" "$GRUB_PW" | grub-mkpasswd-pbkdf2 2>/dev/null | grep -o 'grub\.pbkdf2\.sha512\.[^ ]*' || true)
unset GRUB_PW
if [ -n "$GRUB_PW_HASH" ]; then
  GRUB_LOCK="set superusers=\"admin\"
password_pbkdf2 admin $GRUB_PW_HASH"
  GRUB_ENTRY_FLAGS="--unrestricted"
  echo "  ✔ GRUB bloqueado: edición de parámetros y consola protegidas por contraseña"
else
  echo "  ⚠ grub-mkpasswd-pbkdf2 no disponible: GRUB queda sin bloqueo de edición"
fi

# Crear grub.cfg principal del ISO (en /boot/grub/)
cat > "$BINARY_DIR/boot/grub/grub.cfg" << GRUBEOF
set timeout=2
set default=0
$GRUB_LOCK

insmod all_video
insmod gfxterm

menuentry "Diagnost-Donor Live (v$NEW_VERSION) [Arranque rapido USB]" $GRUB_ENTRY_FLAGS {
    linux $VMLINUZ_REL boot=live live-media-path=/live scan-delay=1 rootdelay=1 username=root quiet splash loglevel=3 modprobe.blacklist=nvidia_gpu drm.kms_helper.poll=1 xe.force_probe=* i915.force_probe=*
    initrd $INITRD_REL
}

menuentry "Diagnost-Donor Live (v$NEW_VERSION) [Cargar en memoria RAM - toram]" $GRUB_ENTRY_FLAGS {
    linux $VMLINUZ_REL boot=live toram live-media-path=/live scan-delay=1 rootdelay=1 username=root quiet splash loglevel=3 modprobe.blacklist=nvidia_gpu drm.kms_helper.poll=1 xe.force_probe=* i915.force_probe=*
    initrd $INITRD_REL
}

GRUBEOF

# Crear grub.cfg de redirección para el ESP (GRUB busca en múltiples paths)
# Este mini-config busca el ISO y carga el grub.cfg principal desde ahí
GRUB_REDIRECT='search.file /boot/grub/grub.cfg root
set prefix=($root)/boot/grub
configfile $prefix/grub.cfg'

echo "$GRUB_REDIRECT" > "$BINARY_DIR/EFI/BOOT/grub.cfg"

# grubx64.efi de Ubuntu busca en /EFI/ubuntu/ — poner redirect ahí también
mkdir -p "$BINARY_DIR/EFI/ubuntu"
echo "$GRUB_REDIRECT" > "$BINARY_DIR/EFI/ubuntu/grub.cfg"

echo "  ✔ grub.cfg configurado en /boot/grub/, /EFI/BOOT/ y /EFI/ubuntu/"

# ── 10d. Crear imagen EFI FAT32 para El Torito ───────────────────────
echo "⚡ Creando imagen EFI FAT32 para arranque UEFI..."
EFI_IMG="$BINARY_DIR/boot/grub/efi.img"

# Calcular tamaño necesario (contenido EFI + grub.cfg + margen)
EFI_SIZE_KB=$(du -sk "$BINARY_DIR/EFI" 2>/dev/null | cut -f1)
EFI_SIZE_MB=$(( (EFI_SIZE_KB / 1024) + 4 ))
[ "$EFI_SIZE_MB" -lt 8 ] && EFI_SIZE_MB=8

dd if=/dev/zero of="$EFI_IMG" bs=1M count="$EFI_SIZE_MB" status=none
mkfs.vfat "$EFI_IMG" >/dev/null

# Copiar estructura EFI completa al FAT image
mcopy -i "$EFI_IMG" -s "$BINARY_DIR/EFI" ::/

# Copiar grub.cfg dentro del FAT image (para firmwares que buscan config en el ESP)
mmd -i "$EFI_IMG" ::/boot 2>/dev/null || true
mmd -i "$EFI_IMG" ::/boot/grub 2>/dev/null || true
mcopy -i "$EFI_IMG" "$BINARY_DIR/boot/grub/grub.cfg" ::/boot/grub/grub.cfg

EFI_REL_PATH=$(realpath --relative-to="$BINARY_DIR" "$EFI_IMG")
echo "  ✔ Imagen EFI: $EFI_REL_PATH (${EFI_SIZE_MB}MB)"

# ── 10e. Empaquetar ISO final con xorriso (hybrid BIOS + UEFI) ──────
echo "📦 Empaquetando ISO híbrida final con xorriso..."
ISOHDPFX=$(find /usr -name "isohdpfx.bin" 2>/dev/null | head -n 1)

XORRISO_ARGS=(-as mkisofs -r -R -V "$VOL_ID" -J -joliet-long -cache-inodes)

# Arranque BIOS via isolinux + MBR hybrid (para USB legacy)
if [ -f "$BINARY_DIR/isolinux/isolinux.bin" ] && [ -n "$ISOHDPFX" ]; then
  echo "  ✔ BIOS boot: isolinux + isohybrid MBR"
  XORRISO_ARGS+=(
    -b isolinux/isolinux.bin
    -c isolinux/boot.cat
    -boot-load-size 4
    -boot-info-table
    -no-emul-boot
    -isohybrid-mbr "$ISOHDPFX"
  )
else
  echo "  ⚠ Sin arranque BIOS (falta isolinux.bin o isohdpfx.bin)"
fi

# Arranque UEFI via EFI image + GPT hybrid (para USB UEFI / Secure Boot)
echo "  ✔ UEFI boot: EFI image + GPT partition"
XORRISO_ARGS+=(
  -eltorito-alt-boot
  -e "$EFI_REL_PATH"
  -no-emul-boot
  -isohybrid-gpt-basdat
)

mkdir -p "$WORK_DIR/ISOs"
FINAL_ISO_PATH="$WORK_DIR/ISOs/$ISO_NAME"

XORRISO_ARGS+=(-output "$FINAL_ISO_PATH" "$BINARY_DIR")

xorriso "${XORRISO_ARGS[@]}"

# ── 11. Verificación final ───────────────────────────────────────────
SIZE=$(du -sh "$FINAL_ISO_PATH" | cut -f1)

echo ""
echo "🔍 Verificando estructura de particiones MBR / GPT / UEFI:"
fdisk -l "$FINAL_ISO_PATH" || true

echo ""
echo "🔍 Verificando El Torito boot entries:"
xorriso -indev "$FINAL_ISO_PATH" -report_el_torito as_mkisofs 2>/dev/null || true

echo ""
echo "================================================================="
echo "✅ ISO HÍBRIDA CREADA CON ÉXITO: $FINAL_ISO_PATH ($SIZE)"
echo "   • Ubicación:  $FINAL_ISO_PATH"
echo "   • BIOS boot:  isolinux + MBR hybrid (compatible con Legacy BIOS)"
echo "   • UEFI boot:  GRUB + Shim + GPT (compatible con Secure Boot)"
echo "   • Flashear con: BalenaEtcher, Rufus (modo GPT/UEFI), dd"
echo "================================================================="
exit 0

