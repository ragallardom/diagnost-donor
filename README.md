# Diagnost-Donor

Suite de diagnóstico y control de calidad de hardware para laptops basada en una distribución Linux Live (Ubuntu 24.04 LTS).

El sistema arranca de forma autónoma desde un pendrive USB directamente a una interfaz web en modo Kiosk, comunicada con un backend local en Python que interactúa con los sensores del kernel (`/sys`, `/proc`, `hwmon`, `DMI`, `sedutil-cli`).

Está orientado a pruebas rápidas de hardware en equipos corporativos (Lenovo ThinkPad, HP EliteBook/ZBook, Dell Latitude/Precision, ASUS, entre otros).

---

## Descarga de la ISO

Si no deseas compilar la imagen desde el código fuente, puedes descargar la ISO lista para grabar:

* **Descargar imagen ISO:** [Carpeta en Google Drive](https://drive.google.com/drive/folders/1OyvIwNIlQrwrBk6csGnisaWAhYtO8NJI?usp=sharing)
* Versión actual disponible: `diagnost-donor_1.1.6_linux-live.iso`

---

## Requisitos de arranque del equipo

* **Arranque UEFI nativo:** La ISO es de tipo híbrida (ISO-Hybrid) con partición EFI firmada. No requiere Ventoy ni gestores intermedios; se graba directamente al pendrive.
* **Secure Boot y TPM 2.0 activos:** Por política de seguridad, el sistema verifica al iniciar que tanto Secure Boot como TPM 2.0 estén habilitados en la BIOS. Si alguno está desactivado, el script de inicio mostrará una advertencia y reiniciará el equipo tras 10 segundos.

Teclas habituales para el menú de booteo:
* **Lenovo / Dell:** `F12`
* **HP:** `F9`
* **ASUS:** `Esc` o `F8`

---

## Requisito previo para compilar la ISO

Si vas a generar la imagen ISO por tu cuenta mediante `builder/build_live_iso.sh`, necesitas colocar el paquete `.deb` de Google Chrome dentro de la carpeta `Aplicaciones/`.

Debido a que los archivos `.deb` están excluidos en `.gitignore`, no se incluyen en el repositorio.

```bash
mkdir -p Aplicaciones
wget -O Aplicaciones/google-chrome-stable_current_amd64.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
```

### ¿Por qué se utiliza Google Chrome?
* Ejecuta la interfaz en modo Kiosk real sin bordes ni barras de navegación.
* Permite omitir mediante políticas y flags las solicitudes de permisos de cámara, micrófono y audio local.
* Soporte directo de WebGL y aceleración gráfica por hardware para los tests de estrés de GPU.

> **Nota:** Cualquier paquete `.deb` adicional que se coloque en `Aplicaciones/` será instalado automáticamente en la imagen durante el proceso de compilación.

---

## Módulos y pruebas incluidas

### Información del sistema
* Lectura DMI: fabricante, modelo exacto y número de serie (S/N).
* Placa base, versión y fecha de BIOS.
* Detección de pantallas externas conectadas por HDMI o DisplayPort (filtrando el panel interno eDP).
* Benchmark rápido de CPU multihilo (~0.5s).
* Prueba de integridad y velocidad de memoria RAM (lectura/escritura de patrones de bits en GB/s).

### Pantalla (Dead Pixel Test)
* Modo interactivo a pantalla completa con 9 patrones y colores sólidos (rojo, verde, azul, blanco, negro para backlight bleed, amarillo, magenta, cian y gradiente de grises).
* Navegación con clic, flechas o barra espaciadora; salida con `Esc`.

### Batería y alimentación
* Salud real de la batería (`Full Capacity / Design Capacity`).
* Contador de ciclos de carga.
* Capacidad de diseño vs actual (Wh), porcentaje de carga y voltaje en tiempo real.
* Detección de anomalías en el cargador (alerta si el cargador está conectado pero no ingresa corriente).

### Temperaturas y ventilación
* Sensores de temperatura de CPU y zonas térmicas (`coretemp`, `k10temp`, `acpitz`).
* Lectura de RPM de ventiladores (soporte para Lenovo ThinkPad ACPI y HP WMI).

### Almacenamiento y desbloqueo SSD
* Detección de unidades NVMe, SATA y discos USB con lectura de salud SMART.
* **Desbloqueo TCG Opal / PSID Revert:**
  * Escaneo del código PSID de 32 caracteres mediante la cámara web (código QR o de barras) o ingreso manual.
  * Reversión de discos bloqueados con `sedutil-cli --PSIDrevert` y borrado criptográfico para NVMe (`nvme format -s 2`).

### Teclado y Touchpad
* **Teclado:** Matriz visual interactiva de 78 teclas (distribuciones ANSI e ISO). Cada pulsación cambia de color progresivamente (verde, violeta, naranja, azul, amarillo) y contabiliza teclas presionadas sin que el navegador capture los atajos del sistema (`Tab`, `Alt`, `F1-F12`, `Super`).
* **Touchpad:** Lienzo para verificar continuidad del cursor y zonas muertas, además de contadores para clic izquierdo y clic derecho / gesto de 2 dedos.

### Multimedia y conectividad
* **Cámara web:** Vista previa en vivo y detección de resolución máxima soportada.
* **Audio:** Barrido senoidal estéreo (canal izquierdo, derecho y ambos) con control de volumen del sistema.
* **Micrófono:** Medidor de nivel (VU meter) en tiempo real con filtro de ruido base y grabador de prueba rápida (loopback de 3 segundos).
* **Wi-Fi y Bluetooth:** Escaneo de redes inalámbricas cercanas (SSID y nivel de señal), prueba de ping a DNS público (`1.1.1.1`), detección del adaptador Bluetooth y su dirección MAC.

### Prueba de estrés
* Carga multihilo configurable para CPU, memoria RAM, lecturas/escrituras en SSD y renderizado 3D WebGL.
* Duraciones: Rápida (~2.5 min), Media (~6 min) o Profunda (~15 min).
* Monitoreo térmico continuo con parada automática de emergencia si la CPU supera los 95°C.

### Checklist y control de energía
* Barra superior fija con el estado de aprobación de cada test.
* Botón de reinicio de pruebas para reevaluar componentes rápidamente.
* Opciones de apagado y reinicio limpio del equipo.

---

## Estructura del repositorio

```plaintext
diagnost-donor/
├── Aplicaciones/                 # Paquetes .deb locales (Google Chrome necesario para compilar)
│   └── google-chrome-stable_current_amd64.deb
├── app/                          # Aplicación de diagnóstico
│   ├── modules/                  # Módulos Python (batería, CPU, RAM, discos, wifi, etc.)
│   ├── server.py                 # Servidor local HTTP REST (puerto 8080)
│   └── static/                   # Frontend web (HTML, CSS y JS modular)
│       ├── index.html
│       ├── style.css
│       ├── vendor/               # Dependencias offline (jsQR)
│       └── js/
├── builder/                      # Scripts de compilación de la ISO Live
│   ├── bin/                      # Binarios adicionales (sedutil-cli)
│   ├── build_live_iso.sh         # Script principal de compilación (ejecuta Docker)
│   ├── build_inside_container.sh # Configuración de live-build en Ubuntu 24.04
│   ├── start_qa.sh               # Script de inicio en el entorno Live
│   └── VERSION                   # Archivo de control de versión
├── ISOs/                         # Directorio donde se guardan las ISOs compiladas
└── README.md
```

---

## Uso y desarrollo local

### Ejecutar la interfaz localmente
Para probar cambios en la aplicación web o en los scripts de backend sin necesidad de compilar la ISO:

```bash
# Iniciar solo el servidor backend
python3 app/server.py
# Abrir en el navegador: http://localhost:8080

# O ejecutar el lanzador completo de pruebas
bash builder/start_qa.sh
```

### Compilar una nueva imagen ISO
El proceso de compilación se ejecuta dentro de un contenedor Docker con Ubuntu 24.04:

```bash
cd builder
sudo ./build_live_iso.sh
```

El script incrementa automáticamente el número de versión (ej. de `1.1.6` a `1.1.7`), actualiza la referencia en la interfaz y genera el archivo `.iso` dentro de la carpeta `ISOs/`.

---

## Grabación en pendrive USB

### Linux (`dd`)
```bash
sudo dd if=ISOs/diagnost-donor_1.1.6_linux-live.iso of=/dev/sdX bs=4M status=progress conv=fsync
```
*(Reemplaza `/dev/sdX` por la unidad correspondiente a tu pendrive).*

### Windows (Rufus / BalenaEtcher)
1. Abre **Rufus** o **BalenaEtcher**.
2. Selecciona la imagen ISO.
3. Selecciona la unidad USB de destino.
4. Graba la imagen (en Rufus, si pregunta el modo de escritura, selecciona **Modo Imagen DD**).