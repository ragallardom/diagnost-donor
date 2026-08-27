# 🔒 DIAGNOST-DONOR - Linux Live Hardware QA Diagnostic Suite
### Suite de Control de Calidad y Diagnóstico Integral de Hardware en Vivo
Optimizada para Laptops **Lenovo ThinkPad** (T14, X1 Carbon, X13, P-Series, L-Series), **HP EliteBook / ZBook** (845 G8/G9/G10, 840 Aero, Firefly), **Dell Latitude / Precision**, **ASUS** y equipos corporativos x86_64.

---

## 📥 Descarga Directa de la ISO

Si solo necesitas la imagen lista para grabar en un pendrive USB sin compilar desde el código fuente, puedes descargar la última versión estable directamente desde Google Drive:

[![Descargar ISO en Google Drive](https://img.shields.io/badge/Google%20Drive-Descargar%20ISO%20Live-4285F4?style=for-the-badge&logo=googledrive&logoColor=white)](https://drive.google.com/drive/folders/1OyvIwNIlQrwrBk6csGnisaWAhYtO8NJI?usp=sharing)

> 🔗 **Enlace de descarga:** [Carpeta Oficial de ISOs en Google Drive](https://drive.google.com/drive/folders/1OyvIwNIlQrwrBk6csGnisaWAhYtO8NJI?usp=sharing)  
> *Incluye la versión `diagnost-donor_1.1.6_linux-live.iso` y versiones posteriores listas para flashear.*

---

## 🚀 Descripción General

**DIAGNOST-DONOR** es una suite de diagnóstico de hardware autónoma basada en un sistema operativo Linux Live optimizado (**Ubuntu Noble 24.04 LTS**). Su interfaz gráfica web se ejecuta localmente en modo **Kiosk** sin distracciones, conectada a un servidor backend REST en Python que interactúa directamente con los sensores de bajo nivel del kernel (`/sys/class`, `/proc`, `hwmon`, `DMI`, `sedutil-cli`).

Está diseñada para técnicos de QA, laboratorios de reacondicionamiento y talleres de servicio que requieren **validar en pocos minutos el 100% de los componentes de una laptop** antes de su entrega o despacho.

---

## ⚠️ Requisito Fundamental para Compilación: Google Chrome en `Aplicaciones/`

> [!IMPORTANT]
> **Si vas a compilar la ISO tú mismo**: La suite requiere el paquete oficial de **Google Chrome** (`.deb`) dentro de la carpeta `Aplicaciones/` antes de ejecutar el script de compilación.
>
> Debido a que los archivos `.deb` y binarios pesados están ignorados en Git (`.gitignore`), tras clonar el repositorio en una máquina nueva debes descargar o copiar el paquete `.deb` de Chrome.

### ¿Por qué es necesario Google Chrome?
1. **Modo Kiosk Puro**: Chrome se ejecuta en pantalla completa sin barra de direcciones, sin advertencias de permisos y con arranque instantáneo sobre Openbox.
2. **Políticas de Hardware Automatizadas**: Concede acceso directo al micrófono, cámara web y aceleración gráfica por WebGL sin diálogos molestos de confirmación.
3. **Rendimiento Gráfico para Pruebas de GPU**: Permite ejecutar pruebas de estrés 3D y renderizado WebGL con máxima fidelidad y bajo consumo de recursos.

### ¿Cómo descargarlo en el proyecto?
Ejecuta el siguiente comando desde la raíz del proyecto para descargar el paquete oficial en el directorio correspondiente:

```bash
# Crear la carpeta si no existe y descargar Google Chrome .deb
mkdir -p Aplicaciones
wget -O Aplicaciones/google-chrome-stable_current_amd64.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
```

> [!TIP]
> **Instalación de paquetes adicionales**: Cualquier paquete `.deb` extra que coloques dentro de la carpeta `Aplicaciones/` (por ejemplo, utilidades de red, herramientas propietarias o scripts de desbloqueo) será integrado e instalado automáticamente dentro de la imagen Live durante la compilación.

---

## ⚡ Arranque Directo sin Ventoy (UEFI Direct Boot)

La imagen generada es un formato **Híbrido UEFI (ISO-Hybrid)** con partición EFI firmada:
* **No requiere Ventoy ni gestores de arranque intermedios**.
* Se graba directamente al pendrive USB y arranca de inmediato en la laptop.
* Presiona la tecla de booteo al encender (**`F12` en Lenovo / Dell**, **`F9` en HP**, **`Esc`/`F8` en ASUS**) y el equipo entrará directamente al panel de diagnóstico.

---

## ⛔ Requisito Bloqueante de Arranque (Strict Secure Boot & TPM 2.0)

Para asegurar los estándares de seguridad corporativos:
1. Al iniciar, el sistema comprueba que **Secure Boot** y **TPM 2.0** estén **ACTIVADOS** en la BIOS.
2. Si alguno de los dos está desactivado, el sistema muestra una advertencia de seguridad en pantalla indicando el estado de cada uno.
3. **Reinicia la laptop automáticamente tras 10 segundos** para forzar al técnico a habilitarlos en el Setup de la BIOS.
4. La interfaz solo carga cuando ambos requisitos son validados con éxito.

---

## 🛠️ Módulos y Funciones de la Suite

### 1. 🖥️ Resumen de Hardware e Identificación del Equipo
* **Identificación DMI**: Detección automática del Fabricante (`Vendor`), Modelo comercial exacto y **Número de Serie (S/N)** en tarjeta destacada.
* **⚡ Test Rápido de CPU Automático**: Benchmark multihilo paralelo (~0.5s) que somete todos los núcleos/hilos a cálculos matemáticos intensivos comprobando la estabilidad de ALU/FPU y tiempo de respuesta sin congelar la interfaz.
* **🖥️ Prueba de Pantalla Completa (Píxeles Muertos / Quemados / Uniformidad)**:
  * Modo interactivo a pantalla completa con 9 colores sólidos y patrones:
    1. 🔴 **Rojo puro** (`#FF0000` - subpíxeles rojos)
    2. 🟢 **Verde puro** (`#00FF00` - subpíxeles verdes y quemaduras)
    3. 🔵 **Azul puro** (`#0000FF` - subpíxeles azules)
    4. ⚪ **Blanco puro** (`#FFFFFF` - manchas, uniformidad y suciedad)
    5. ⚫ **Negro puro** (`#000000` - fugas de luz / *backlight bleed* y píxeles atascados)
    6. 🟡 **Amarillo** (`#FFFF00` - mezcla rojo-verde)
    7. 🟣 **Magenta** (`#FF00FF` - mezcla rojo-azul)
    8. 🔷 **Cian** (`#00FFFF` - mezcla verde-azul)
    9. 🏁 **Escala de Grises / Gradiente** (contraste y *banding*)
  * **Navegación**: Clic o `Espacio` / `Flechas` para avanzar, `ESC` para salir y registrar aprobación en el checklist QA.
* **Memoria RAM & Benchmark en Vivo**:
  * Capacidad total instalada vs. memoria en uso con barra gráfica de porcentaje.
  * **Test de Integridad y Rendimiento RAM (256 MB)**: Escribe patrones de bits (`0xAA`, `0x55`), comprueba paridad en busca de celdas corruptas y calcula la velocidad real de transferencia en **GB/s**.
* **Placa Base & BIOS**: Nombre de la placa madre, versión de BIOS instalada y fecha de lanzamiento.
* **Detección de Pantallas Externas (HDMI / DisplayPort)**: Monitoreo en tiempo real de puertos externos conectados, filtrando de manera inteligente la pantalla interna de la laptop (`eDP`/`LVDS`).

---

### 2. 🔋 Diagnóstico Avanzado de Batería y Puerto de Carga
* **Salud Real de la Batería**: Porcentaje de vida útil real calculado a partir de la capacidad de diseño original vs. capacidad máxima actual (`(Full Wh / Design Wh) * 100`).
* **Contador de Ciclos**: Lectura directa del contador de ciclos de carga registrados por el controlador de la batería.
* **Métricas Energéticas**: Capacidad de diseño de fábrica (`Wh`), capacidad máxima retenida (`Wh`), nivel de carga actual (`%`) y voltaje en tiempo real (`V`).
* **Detección de Fallas en Puerto de Carga y Cargador**: Alerta visual inmediata si el cargador está enchufado pero la batería **no está recibiendo corriente** (diagnóstico de pines dañados, cargadores de bajo vataje o celdas degradadas).

---

### 3. ❄️ Monitoreo Térmico y Ventiladores
* **Sensores de Temperatura Multi-fuente**: Lectura precisa de sensores CPU y zonas térmicas (`hwmon`, `thermal_zone`, `coretemp`, `k10temp`) con clasificación de estado (*Normal*, *Caliente*, *Crítico*).
* **Control y RPM de Ventiladores**: Lectura de revoluciones por minuto (RPM) con soporte para módulos específicos de **Lenovo ThinkPad ACPI** (`/proc/acpi/ibm/fan`) y **HP WMI**.

---

### 4. 💽 Almacenamiento Interno y Externo
* **Detección de Discos**: Identificación de unidades internas **M.2 NVMe SSD**, **SATA SSD / HDD** y unidades **USB externas**.
* **Capacidad y Salud SMART**: Lectura de tamaño real (`GB`), modelo del fabricante y estado de salud SMART.
* **Separación de Unidades**: Clasificación clara entre almacenamiento de sistema y pendrives USB conectados.

---

### 5. 🔓 Desbloqueo TCG Opal / McAfee (PSID Revert)
Herramienta integrada para restaurar y reutilizar discos SSD corporativos bloqueados por cifrado de hardware:
* **Escáner QR por Cámara Web**: Utiliza la webcam integrada para escanear directamente el código QR/código de barras del código **PSID** impreso en la etiqueta física del disco SSD (librería `jsQR`).
* **Entrada Manual**: Campo para ingresar o editar el código PSID de 32 caracteres.
* **Doble Estrategia de Desbloqueo**:
  1. Ejecución de `sedutil-cli --PSIDrevert` para unidades TCG Opal compatibles.
  2. Borrado criptográfico seguro de bajo nivel para NVMe (`nvme format -s 2`).
* Retorna el disco a su estado de fábrica eliminando contraseñas y cifrados corporativos previos.

---

### 6. ⌨️ Prueba Interactiva de Teclado
* **Matriz Visual de 78 Teclas**: Soporte completo para distribuciones ANSI e ISO (con tecla `Enter` en forma de L, `Ñ`, `<>`, etc.).
* **Ciclo de 5 Colores**: Cada pulsación sobre la misma tecla alterna progresivamente de color (**Verde → Violeta → Naranjo → Azul → Amarillo**) con efectos de iluminación y sombra *glow*.
* **Detección en Tiempo Real**: Iluminación y conteo progresivo de teclas presionadas (`0 / 78`).
* **Captura Total de Teclas**: Intercepción de atajos nativos del sistema/navegador para permitir probar teclas críticas (`Tab`, `Alt`, `F1-F12`, `Super/Win`, `Espacio`) sin cerrar la aplicación.
* **Muestra de Última Tecla**: Muestra el código de evento y nombre de tecla capturado.

---

### 7. 🖱️ Prueba de Touchpad y Gestos Multitáctiles
* **Lienzo de Trazo Continuo**: Permite dibujar libremente sobre el canvas para comprobar zonas muertas, precisión y continuidad del sensor táctil.
* **Verificación de Clics**: Indicadores visuales independientes para **Clic Izquierdo** y **Clic Derecho / Toque con 2 Dedos**.
* **Ciclo Cromático Sincronizado**: Al hacer clic en los recuadros, estos cambian de color en el mismo orden que el teclado (**Verde → Violeta → Naranjo → Azul → Amarillo**) y cuentan de 1 en 1 con protección anti-rebote (*debounce*).

---

### 8. 📷 🔊 🎙️ Pruebas Multimedia (Cámara, Parlantes y Micrófono)
* **Cámara Web**:
  * Vista previa fluida de video en tiempo real.
  * Detección y despliegue de la resolución nativa máxima soportada (ej. `1280x720`, `1920x1080`).
* **Parlantes y Separación Estéreo**:
  * **Barrido de Frecuencias**: Generador de tono senoidal progresivo mediante Web Audio API en 3 pasos: *Canal Izquierdo*, *Canal Derecho* y *Ambos Canales*.
  * **Control de Volumen del Sistema**: Deslizador que ajusta directamente el volumen maestro del sistema operativo vía `pactl` / `amixer`.
* **Micrófono Integrado**:
  * **Vúmetro Calibrado (VU Meter)**: Análisis espectral (`getByteFrequencyData`) con filtro de piso de ruido (*noise gate*) y decaimiento suave para medir con precisión la voz sin saturarse con el soplido de los ventiladores.
  * **Grabación y Escucha (Loopback 3s)**: Graba 3 segundos de audio con el micrófono y lo reproduce inmediatamente para verificar claridad, ruido estático o fallos físicos.

---

### 9. 📶 🔵 Redes Wi-Fi y Bluetooth
* **Conectividad Wi-Fi**:
  * Detección de chip de red inalámbrico (con soporte para drivers modernos Intel Wi-Fi 6E/7 BE200/AX211, Qualcomm ath11k/12k, Realtek rtw89 y MediaTek mt7921/7925).
  * Escaneo automático de redes inalámbricas cercanas mostrando **Nombre de Red (SSID)** y **Nivel de Señal (%)**.
  * Prueba de latencia / ping a internet hacia DNS público (`1.1.1.1`).
* **Adaptador Bluetooth**:
  * Verificación de presencia del controlador y alimentación del radio.
  * Extracción de la **Dirección MAC física** del adaptador Bluetooth.

---

### 10. ⚡ Pruebas de Estrés y Estabilidad (Stress Test)
Módulo multihilo para someter los componentes a máxima carga térmica y de cómputo:
* **Componentes Seleccionables**:
  * **CPU**: Cálculo matricial multihilo intensivo y verificación de estabilidad bajo carga máxima.
  * **RAM**: Pruebas de inversión de bits (*bit-flip*) y patrones de memoria (DDR3, DDR4, DDR5, LPDDR4/5).
  * **SSD**: Pruebas de lectura/escritura en ráfagas temporales seguras de I/O.
  * **GPU / iGPU**: Renderizado de shaders 3D en tiempo real sobre WebGL con monitor de FPS en vivo.
* **Niveles de Intensidad**:
  * 🟢 **Rápida**: ~2.5 minutos.
  * 🟡 **Media**: ~6 minutos.
  * 🔴 **Profunda**: ~15 minutos.
* **Seguridad Térmica Inteligente**:
  * Telemetría de temperatura en tiempo real y registro de temperatura máxima alcanzada.
  * **Aborto Automático de Emergencia a 95°C** para proteger el procesador contra sobrecalentamiento.
  * Opción de abortar manualmente en cualquier momento.
* **Reporte Final de Resultados**: Resumen detallado con estado de aprobación (`PASSED` / `FAILED`) por componente.

---

### 11. 📋 Checklist QA Flotante y Control de Energía
* **Checklist QA Sticky**: Barra superior permanente que actualiza dinámicamente el estado de validación de cada prueba (*CPU, Pantalla, RAM, SSD, HDMI, Bluetooth, Teclado, Touchpad, Cámara, Parlantes, Micrófono, Wi-Fi*).
* **Botón de Actualizar Inteligente**: Al hacer clic en el botón de refresco en la cabecera, se reinician todos los tests manuales y se ejecutan de nuevo automáticamente las pruebas de CPU, RAM, cámara y micrófono.
* **Control de Energía Seguro**: Botones de **Reiniciar** y **Apagar** en la cabecera con diálogo modal de confirmación para apagar o reiniciar el equipo de forma limpia.

---

## 🏗️ Estructura del Proyecto

```plaintext
diagnost-donor/
├── Aplicaciones/                 # Paquetes .deb y binarios offline (Chrome obligatorio para compilar)
│   └── google-chrome-stable_current_amd64.deb
├── app/                          # Aplicación de Diagnóstico (Backend & Frontend)
│   ├── modules/                  # Módulos Python de Telemetría y Hardware
│   │   ├── battery.py            # Salud, ciclos y fallas de carga
│   │   ├── bluetooth_diag.py     # Controlador y MAC de Bluetooth
│   │   ├── cpu_benchmark.py      # Benchmark rápido multihilo de CPU
│   │   ├── display_hdmi_diag.py  # Detección HDMI/DP y BIOS
│   │   ├── opal_diag.py          # TCG Opal / PSID Revert / NVMe Crypto Format
│   │   ├── ram_benchmark.py      # Test de integridad y velocidad de RAM
│   │   ├── storage_diag.py       # Escaneo de SSD/NVMe/SATA/USB y SMART
│   │   ├── stress_diag.py        # Motor multihilo de pruebas de estrés
│   │   ├── system_info.py        # S/N, Modelo DMI, CPU y TPM 2.0
│   │   ├── thermal.py            # Sensores térmicos y RPM de ventiladores
│   │   └── wifi_diag.py          # Escaneo Wi-Fi y latencia ping
│   ├── server.py                 # Servidor HTTP REST (localhost:8080)
│   └── static/                   # Interfaz Web Frontend (HTML5 / Vanilla JS / CSS)
│       ├── index.html            # Estructura Single-Page Kiosk
│       ├── style.css             # Tema Stealth Purple & estilos responsivos
│       ├── vendor/               # Librerías offline (jsQR, etc.)
│       └── js/                   # Lógica modular frontend
│           ├── api.js            # Cliente de comunicación con backend REST
│           ├── keyboard.js       # Matriz interactiva de 78 teclas
│           ├── media.js          # Cámara, barrido de audio, micrófono VU y test de pantalla
│           ├── opal.js           # Escáner QR de PSID y desbloqueo
│           ├── stress.js         # Controlador de pruebas de estrés y WebGL
│           ├── touchpad.js       # Lienzo de trazo y detección de clics
│           ├── ui.js             # Renderizado de componentes y métricas
│           └── main.js           # Inicialización y polling de telemetría
├── builder/                      # Scripts de Construcción y Autoarranque
│   ├── bin/                      # Herramientas binarias (sedutil-cli)
│   ├── build_live_iso.sh         # Lanzador Docker / contenedor
│   ├── build_inside_container.sh # Script live-build en Ubuntu 24.04 (Noble)
│   ├── start_qa.sh               # Script de inicio y chequeo Secure Boot/TPM
│   └── VERSION                   # Versión actual de la suite (autoincrementable)
├── ISOs/                         # Directorio de almacenamiento de imágenes ISO compiladas
│   └── diagnost-donor_1.1.6_linux-live.iso
├── .gitignore                    # Reglas de exclusión para Git
└── README.md                     # Documentación general de la suite
```

---

## 🚀 Comandos Rápidos de Uso

Estando ubicado en la raíz del proyecto:

### 1. 🖥️ Levantar la aplicación localmente en tu sistema
Para probar o desarrollar la interfaz y los módulos sin compilar la ISO:
```bash
# Opción 1: Servidor HTTP directo
cd /home/modonor/Proyectos/diagnost-donor
python3 app/server.py
# Luego abre en tu navegador: http://localhost:8080

# Opción 2: Lanzador completo con entorno QA
bash /home/modonor/Proyectos/diagnost-donor/builder/start_qa.sh
```

### 2. 💿 Compilar una nueva ISO Live (con versionado automático)
Para generar una nueva imagen ISO en Docker:
```bash
cd /home/modonor/Proyectos/diagnost-donor/builder
sudo ./build_live_iso.sh
```
* El script detectará la última versión generada (ej. `1.1.6`), incrementará el número a `1.1.7`, actualizará el código en `index.html` y `builder/VERSION`, y guardará la imagen final exclusivamente en la carpeta `ISOs/`.

---

## 🔌 Cómo Grabar la ISO al Pendrive USB

### Opción A: Desde Linux (Línea de Comandos con `dd`)
1. Conecta tu pendrive y localiza su identificador con `lsblk` (ejemplo: `/dev/sdb` o `/dev/sdc`).
2. Graba la ISO directamente al pendrive:
   ```bash
   sudo dd if=/home/modonor/Proyectos/diagnost-donor/ISOs/diagnost-donor_1.1.6_linux-live.iso of=/dev/sdX bs=4M status=progress conv=fsync
   ```
   *(Reemplaza `/dev/sdX` por la unidad correspondiente a tu pendrive USB).*

### Opción B: Desde Windows (Rufus o BalenaEtcher)
1. Descarga e inicia **Rufus** o **BalenaEtcher**.
2. Selecciona la imagen ISO `diagnost-donor_1.1.6_linux-live.iso` desde la carpeta `ISOs/` o la descargada desde Google Drive.
3. Selecciona tu unidad USB.
4. Haz clic en **Empezar / Flash!** (si Rufus solicita el modo de grabación, selecciona **Modo Imagen DD**).

---

## 💻 Inicio Rápido en Laptops

1. Conecta el pendrive USB grabado en la laptop a diagnosticar.
2. Enciende el equipo y presiona repetidamente la tecla del menú de arranque:
   * **Lenovo ThinkPad**: `F12`
   * **HP EliteBook / ZBook**: `F9`
   * **Dell Latitude / Precision**: `F12`
   * **ASUS / Otros**: `Esc` o `F8`
3. Selecciona tu unidad USB en el menú.
4. El sistema verificará Secure Boot y TPM 2.0, iniciará los controladores de hardware y abrirá automáticamente la suite de diagnóstico en pantalla completa.