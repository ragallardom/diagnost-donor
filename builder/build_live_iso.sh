#!/bin/bash
# ==============================================================================
# Script para Generar ISO Linux Live con BLOQUEO DE ARRANQUE SI FALTA SECURE BOOT O TPM 2.0
# Compatible con Ubuntu/Debian y CachyOS/Arch Linux (vía Docker automático)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configurar archivo de log global (se sobrescribe en cada ejecución)
LOG_FILE="$WORK_DIR/builder/build_output.log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================="
echo "  📋 REGISTRO DE COMPILACIÓN EN: $LOG_FILE"
echo "  📅 FECHA: $(date)"
echo "================================================================="

# Check root permissions
if [ "$EUID" -ne 0 ]; then
  echo "⚠️ Este script necesita ejecutarse with permisos de administrador (sudo)."
  echo "   Uso: sudo ./builder/build_live_iso.sh"
  exit 1
fi


# Detect package manager / distro (Debian/Ubuntu vs CachyOS/Arch)
if ! command -v apt-get >/dev/null 2>&1; then
  echo "================================================================="
  echo "  🐧 Sistema CachyOS / Arch Linux detectado."
  echo "  🐳 Ejecutando compilación automatizada dentro de Docker (Ubuntu 24.04)..."
  echo "================================================================="
  
  if command -v docker >/dev/null 2>&1; then
    # Auto-start docker daemon if inactive
    if ! systemctl is-active --quiet docker; then
      echo "⚡ Iniciando servicio de Docker..."
      systemctl start docker || true
    fi

    chmod +x "$SCRIPT_DIR/build_inside_container.sh"
    cd "$WORK_DIR"
    docker run --privileged --rm -e DEBIAN_FRONTEND=noninteractive -v "$WORK_DIR:/work" -w /work ubuntu:24.04 bash ./builder/build_inside_container.sh
    exit 0
  else
    echo "❌ Error: Se requiere Docker instalado para compilar ISOs de Ubuntu en CachyOS."
    echo "   Instala e inicia Docker con: sudo pacman -S docker && sudo systemctl start docker"
    exit 1
  fi
fi

# If apt-get is available (Debian/Ubuntu host), build directly
chmod +x "$SCRIPT_DIR/build_inside_container.sh"
cd "$WORK_DIR"
bash ./builder/build_inside_container.sh
