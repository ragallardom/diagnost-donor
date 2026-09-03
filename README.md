# Diagnost-Donor

Suite de diagnóstico y control de calidad de hardware para laptops basada en una distribución Linux Live (Ubuntu 24.04 LTS).

El sistema arranca de forma autónoma desde un pendrive USB directamente a una interfaz web en modo Kiosk, comunicada con un backend local en Python que interactúa con los sensores del kernel (`/sys`, `/proc`, `hwmon`, `DMI`, `sedutil-cli`, `nvme-cli`, `bluez-obexd`).

Está orientado a pruebas rápidas de hardware en equipos corporativos (Lenovo ThinkPad, HP EliteBook/ZBook, Dell Latitude/Precision, ASUS, entre otros).

---

## Descarga de la ISO

Si no deseas compilar la imagen desde el código fuente, puedes descargar la ISO lista para grabar:

* **Descargar imagen ISO:** [Carpeta en Google Drive](https://drive.google.com/drive/folders/1OyvIwNIlQrwrBk6csGnisaWAhYtO8NJI?usp=sharing)
* Versión de referencia: `diagnost-donor_1.1.15_linux-live.iso`

---

## Requisitos y características de arranque

* **Menú de booteo dual:**
  * **Arranque rápido directo USB (Predeterminado):** Carga el sistema en ~15 segundos montando el sistema de archivos directamente desde el pendrive USB.
  * **Carga 100% en RAM (`toram`):** Copia íntegramente la imagen a la memoria RAM durante el inicio, permitiendo desconectar el pendrive USB una vez que la interfaz principal haya cargado.
* **Arranque UEFI y BIOS nativo:** La ISO es de tipo híbrida (ISO-Hybrid) con partición EFI firmada. No requiere Ventoy ni gestores intermedios; se graba directamente al pendrive.
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
* Contador de ciclos de carga con cuadro de referencia industrial (0-300: Excelente, 300-500: Normal / Buen estado, 500-800: Desgaste moderado, >800: Desgaste alto).
* Capacidad de diseño vs actual (Wh), porcentaje de carga y voltaje en tiempo real.
* Detección precisa de anomalías de carga con eliminación de falsos positivos:
  * Reconocimiento de batería al 100% o carga completa sin emitir falsas alertas de carga detenida.
  * Soporte para umbrales de conservación en BIOS (ASUS, Lenovo, Dell a 60% u 80%).
  * Periodo de gracia para la negociación eléctrica de controladores EC/PMIC al enchufar el cargador.

### Temperaturas y ventilación
* Sensores térmicos dedicados de silicio (`coretemp` para Intel, `k10temp`/`zenpower` para AMD), filtrando sensores periféricos.
* Lectura de RPM de ventiladores (soporte para Lenovo ThinkPad ACPI, ASUS y HP WMI).
* Clasificación dinámica en tiempo real: Normal (<75°C), Carga / Estable (<92°C), Caliente / Turbo (<100°C) y Límite Térmico (>=100°C).

### Almacenamiento, diagnóstico LBA, vida útil y desbloqueo SSD
* **Evaluación de vida útil y desgaste (Endurance):**
  * Total Escrito acumulado (**TBW - Terabytes Written**) a partir de registros SMART (`data_units_written` en NVMe o `Total_LBAs_Written` en SATA).
  * Ciclos de programación y borrado (**Ciclos P/E**) con cuadro informativo de referencia industrial (0-100: Excelente, 100-300: Muy bueno, 300-600: Uso moderado, >800: Desgaste alto).
  * Detección automática de discos mecánicos HDD, marcando los ciclos P/E como no aplicables.
* **Pruebas de lectura de bajo nivel (Device Read & NVMe Read Test):**
  * Ejecuta pruebas no destructivas en LBA 0 y bloques secundarios similares a las de Lenovo UEFI Diagnostics.
  * Si cualquiera de las dos pruebas de lectura (o ambas) falla, el sistema alerta automáticamente con `Posible bloqueo por cifrado TCG Opal` y orienta al técnico hacia el proceso de desbloqueo.
* **Desbloqueo TCG Opal / PSID Revert:**
  * Escáner QR optimizado para pantallas de teléfonos móviles y cámaras web de baja resolución.
  * **Receptor Bluetooth Android nativo (OBEX):** Permite emparejar el celular y compartir el código PSID directamente por Bluetooth sin instalar aplicaciones ni usar redes locales.
  * Reversión de discos bloqueados con `sedutil-cli` y reseteo integral de particiones (`wipefs` + `parted`).
  * Compatibilidad con borrado criptográfico NVMe Sanitize / SES-2.

### Teclado y Touchpad
* **Teclado:** Matriz visual interactiva de 78 teclas (distribuciones ANSI e ISO). Cada pulsación cambia de color progresivamente (verde, violeta, naranja, azul, amarillo) y contabiliza teclas presionadas sin que el navegador capture los atajos del sistema (`Tab`, `Alt`, `F1-F12`, `Super`).
* **Touchpad:** Lienzo para verificar continuidad del cursor y zonas muertas, además de contadores para clic izquierdo y clic derecho / gesto de 2 dedos.

### Multimedia y conectividad
* **Cámara web:** Vista previa en vivo y detección de resolución máxima soportada.
* **Audio:** Barrido senoidal estéreo (canal izquierdo, derecho y ambos) con control de volumen del sistema.
* **Micrófono con análisis de onda PCM/RMS:** Medidor de nivel (VU meter) en tiempo real y grabador loopback de 3 segundos con comprobación de amplitud para evitar falsos positivos en entornos sin micrófono o máquinas virtuales.
* **Conectividad de red (Wi-Fi y Ethernet):**
  * **Wi-Fi:** Escaneo de redes inalámbricas cercanas (SSID y nivel de señal) y prueba de ping a DNS público (`1.1.1.1`).
  * **Ethernet RJ-45:** Detección de puerto físico y validación del enlace por cable. Una vez probado con éxito, la aprobación en el checklist se mantiene fija de forma persistente aunque el técnico desconecte el cable para continuar con otras pruebas.
  * **Diagnóstico automático de Loopback (TX/RX):** Comprobación inmediata de conectores loopback RJ-45 (pines 1-3 y 2-6 puenteados) mediante tramas de prueba capa 2 (EtherType `0x88B5`) sin necesidad de switch o infraestructura de red externa.
* **Bluetooth:** Detección del adaptador de radio y su dirección MAC.

### Prueba de estrés
* Carga multihilo configurable para CPU, memoria RAM, lecturas/escrituras en SSD y renderizado 3D WebGL.
* Duraciones: Rápida (~2.5 min), Media (~6 min) o Profunda (~15 min).
* Protección térmica con tolerancia a picos normales de Turbo Boost (PL2) y parada automática de emergencia si la CPU sostiene >=100°C por más de 4 segundos o supera los 104°C.

### Seguridad y blindaje corporativo (Modo Kiosk)
* **Aislamiento de red:** El servidor backend REST escucha exclusivamente en `127.0.0.1:8080`, impidiendo el acceso o escaneo de puertos desde la red corporativa al conectar cables de red o Wi-Fi.
* **Operación 100% local (Air-Gap):** Sin dependencias externas de internet; utiliza tipografía nativa del sistema operativo (`system-ui` / `ui-monospace`) con cero tráfico saliente.
* **Bloqueo de consolas virtuales:** Directivas X11 (`DontVTSwitch` y `DontZap`) que impiden abandonar el entorno gráfico mediante combinaciones `Ctrl + Alt + F1..F6` o `Ctrl + Alt + Backspace`.
* **Bloqueo de atajos y consola de desarrollador:** Atajo `Alt + F4` anulado en el gestor de ventanas Openbox, DevTools (`F12`, `Ctrl + Shift + I`, inspeccionar) deshabilitadas mediante directivas gestionadas de Chrome y bucle supervisor (watchdog) para relanzar la interfaz automáticamente si el proceso se interrumpe.
* **Control de arranque:** Validación obligatoria de UEFI Secure Boot activo y módulo TPM 2.0 funcional al iniciar.

### Checklist y control de energía
* Barra superior fija con el estado de aprobación en mayúsculas de cada test.
* Botón de reinicio de pruebas para reevaluar componentes rápidamente.
* Opciones de apagado y reinicio limpio del equipo con modales de confirmación con diseño nativo.

---

## Estructura del repositorio

```plaintext
diagnost-donor/
├── Aplicaciones/                 # Paquetes .deb locales (Google Chrome necesario para compilar)
│   └── google-chrome-stable_current_amd64.deb
├── app/                          # Aplicación de diagnóstico
│   ├── modules/                  # Módulos Python (batería, CPU, RAM, discos, wifi, bluetooth, stress, etc.)
│   ├── server.py                 # Servidor local HTTP REST (puerto 8080)
│   └── static/                   # Frontend web (HTML, CSS y JS modular)
│       ├── index.html
│       ├── style.css
│       ├── vendor/               # Dependencias offline (jsQR, zxing)
│       └── js/
├── builder/                      # Scripts de compilación de la ISO Live
│   ├── bin/                      # Binarios adicionales (sedutil-cli)
│   ├── build_live_iso.sh         # Script principal de compilación (ejecuta Docker)
│   ├── build_inside_container.sh # Configuración de live-build en Ubuntu 24.04 (soporte toram)
│   ├── start_qa.sh               # Script de inicio en el entorno Live con healthcheck
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
# Abrir en el navegador: http://127.0.0.1:8080

# O ejecutar el lanzador completo de pruebas
bash builder/start_qa.sh
```

### Compilar una nueva imagen ISO
El proceso de compilación se ejecuta dentro de un contenedor Docker con Ubuntu 24.04:

```bash
cd builder
sudo ./build_live_iso.sh
```

* **Versionado inteligente:** Si la versión definida en el código es mayor a la última ISO existente en `ISOs/`, se compila directamente con esa versión. Si es menor o igual, suma automáticamente `+1` a la última ISO creada.
* **Seguridad y compatibilidad:** Incluye montaje automático de certificados CA del host para descargas seguras por repositorios HTTPS.

---

## Grabación en pendrive USB

### Linux (`dd`)
```bash
sudo dd if=ISOs/diagnost-donor_1.1.12_linux-live.iso of=/dev/sdX bs=4M status=progress conv=fsync
```
*(Reemplaza `/dev/sdX` por la unidad correspondiente a tu pendrive).*

### Windows (Rufus / BalenaEtcher)
1. Abre **Rufus** o **BalenaEtcher**.
2. Selecciona la imagen ISO.
3. Selecciona la unidad USB de destino.
4. Graba la imagen (en Rufus, si pregunta el modo de escritura, selecciona **Modo Imagen DD**).