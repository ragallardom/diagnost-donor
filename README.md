# Diagnost-Donor

Suite de diagnóstico y control de calidad de hardware para laptops basada en una distribución Linux Live (Ubuntu 24.04 LTS).

El sistema arranca de forma autónoma desde un pendrive USB directamente a una interfaz web en modo Kiosk, comunicada con un backend local en Python que interactúa con los sensores del kernel (`/sys`, `/proc`, `hwmon`, `DMI`, `sedutil-cli`, `nvme-cli`, `bluez-obexd`).

Está orientado a pruebas rápidas de hardware en equipos corporativos (Lenovo ThinkPad, HP EliteBook/ZBook, Dell Latitude/Precision, ASUS, entre otros).

---

## Descarga de la ISO

Si no deseas compilar la imagen desde el código fuente, puedes descargar la ISO lista para grabar:

* **Descargar imagen ISO:** [Carpeta en Google Drive](https://drive.google.com/drive/folders/1OyvIwNIlQrwrBk6csGnisaWAhYtO8NJI?usp=sharing)
* Versión de referencia: `diagnost-donor_1.1.24_linux-live.iso`

---

## Requisitos y características de arranque

* **Menú de booteo dual:**
  * **Arranque rápido directo USB (Predeterminado):** Carga el sistema en ~15 segundos montando el sistema de archivos directamente desde el pendrive USB.
  * **Carga 100% en RAM (`toram`):** Copia íntegramente la imagen a la memoria RAM durante el inicio, permitiendo desconectar el pendrive USB una vez que la interfaz principal haya cargado.
* **Arranque UEFI y BIOS nativo:** La ISO es de tipo híbrida (ISO-Hybrid) con partición EFI firmada. No requiere Ventoy ni gestores intermedios; se graba directamente al pendrive.
* **Secure Boot y TPM 2.0 activos:** Por política de seguridad, el sistema verifica al iniciar que tanto Secure Boot como TPM 2.0 estén habilitados en la BIOS. Si alguno está desactivado, el script de inicio mostrará una advertencia y reiniciará el equipo tras 30 segundos.

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
* Lectura DMI: fabricante, modelo exacto y número de serie (S/N). En Lenovo el part number (`20S0S1EJ00`) no se muestra: el modelo sale del nombre comercial (`ThinkPad T14 Gen 1`) y el part number queda solo como dato interno.
* Barra superior: marca + modelo corto, p. ej. `Lenovo T14 Gen 5`, `Lenovo P15 Gen 2`, `Lenovo X1 Carbon Gen 11` (también los nombres antiguos «6th»/«7th»), `HP EliteBook 845 G8`, `HP EliteBook 840 Aero G8`, `HP ZBook Firefly 14 G8`. Cubierto por `tests/test_model_names.py` (requiere `node`). Los valores de relleno del fabricante (`Default string`, `To be filled by O.E.M.`, `None`…) se descartan: si el S/N del sistema no es válido se usa el de la placa y, si tampoco, se muestra `N/A`.
* TPM: solo se da por 2.0 si el kernel lo confirma (`tpm_version_major` o `/dev/tpmrm0`); un `/dev/tpm0` sin versión se muestra como «versión no confirmada».
* Placa base, versión y fecha de BIOS.
* Detección de pantallas externas conectadas por HDMI o DisplayPort (filtrando el panel interno eDP). Si el kernel informa `connected` / `disconnected` esa respuesta es definitiva; solo se recurre a EDID, modos o `enabled` cuando el estado es desconocido.
* Benchmark rápido de CPU (~0.5 s): un proceso por CPU lógica ejecuta el mismo cálculo de coma flotante y todos deben devolver el resultado idéntico bit a bit; un núcleo que difiere, no responde o devuelve NaN se cuenta como error.
* Prueba de integridad y velocidad de memoria RAM (256 MB, ~1-3 s): 5 patrones (`AA`, `55`, `00`, `FF` y aleatorio) escritos y verificados byte a byte, con velocidad en GB/s. Cualquier byte distinto marca la prueba como fallida.

### Pantalla (Dead Pixel Test)
* Modo interactivo a pantalla completa con 9 patrones y colores sólidos (rojo, verde, azul, blanco, negro para backlight bleed, amarillo, magenta, cian y gradiente de grises).
* **Brillo:** al iniciar se fija en 90 % y hay una barra para subirlo o bajarlo (mínimo 5 %). Solo aparece si el equipo tiene control de brillo (`/sys/class/backlight`).
* Navegación con clic, flechas o barra espaciadora; salida con `Esc`. Salir con `Esc` solo aprueba la prueba si se llegó al último de los 9 patrones (un píxel muerto puede estar en cualquier color).

### Batería y alimentación
* Salud real de la batería (`Full Capacity / Design Capacity`). Si la batería no informa ambas capacidades se muestra `N/D`, nunca un 100 % inventado.
* Contador de ciclos de carga con cuadro de referencia industrial (0-300: Excelente, 300-500: Normal / Buen estado, 500-800: Desgaste moderado, >800: Desgaste alto).
* Capacidad de diseño vs actual (Wh), porcentaje de carga y voltaje en tiempo real.
* Estado del cargador en la barra superior: «Conectado cargando» o «Conectado, sin carga» (en rojo, si está enchufado pero la batería no carga).
* Detección precisa de anomalías de carga con eliminación de falsos positivos:
  * Reconocimiento de batería al 100% o carga completa sin emitir falsas alertas de carga detenida.
  * Soporte para umbrales de conservación en BIOS (ASUS, Lenovo, Dell a 60% u 80%).
  * Periodo de gracia para la negociación eléctrica de controladores EC/PMIC al enchufar el cargador.
* `upower` se consulta como máximo cada 5 s (no en cada refresco de 1 s).

### Temperaturas, ventilación y salud térmica
* Sensores térmicos dedicados de silicio (`coretemp` para Intel, `k10temp`/`zenpower` para AMD, prefiriendo `Tdie` sobre `Tctl`), filtrando sensores periféricos.
* Lectura de RPM de ventiladores (soporte para Lenovo ThinkPad ACPI, ASUS y HP WMI). Si la BIOS no expone un valor, se indica "Sin lectura"; nunca se muestran valores inventados. El ventilador de ThinkPad no se lista dos veces (hwmon + `/proc/acpi/ibm/fan`). Si no hay RPM (habitual en HP EliteBook, cuyo EC no lo expone), se muestra el estado del ventilador ACPI (activo / apagado) cuando existe; se cargan además `hp_wmi`, `dell_smm_hwmon` y `asus_nb_wmi`.
* **Detección de throttling térmico** (equivalente a *Core/Package Thermal Throttling* de HWiNFO64):
  * Intel: contadores del kernel `/sys/devices/system/cpu/cpuN/thermal_throttle/` (eventos y tiempo acumulado desde el arranque) y, si está disponible, los MSR de estado térmico para detectar throttling y PROCHOT en este momento (lectura permitida con Secure Boot).
  * El límite por potencia (PL1/PL2) no se considera un problema: es el comportamiento normal de una laptop y no se corrige con limpieza.
  * AMD: el kernel no expone contadores de throttling; la evaluación se hace por temperatura.
* **Recomendación de mantenimiento (limpieza y cambio de pasta térmica):**
  * *Vista general:* recuadro "Térmica" con título y una línea (TjMax y umbrales al pasar el cursor). Avisa si la CPU se mantiene en ≥95 °C durante 60 s, está sobre 70 °C en reposo durante 60 s (polvo o pasta seca) o reduce su rendimiento en ese momento. El throttling acumulado desde el arranque ya no se muestra ahí: solo cuenta durante la prueba de estrés.
  * *Prueba de estrés (fase CPU):* se descartan los primeros 30 s de Turbo/PL2, donde los picos altos son normales. Se recomienda limpieza y cambio de pasta si la CPU se mantiene en **≥95 °C durante al menos la mitad de la carga sostenida**, si hay throttling térmico significativo (≥3 s o ≥10 % del tiempo), si la prueba se aborta por temperatura o si el ventilador marca 0 RPM con la CPU sobre 80 °C. Para confirmar un diagnóstico dudoso conviene usar el nivel Media o Profunda.

### Almacenamiento, diagnóstico LBA, vida útil y desbloqueo SSD
* **Salud SMART real:** el estado sale de los datos SMART, en una línea corta: «SMART correcto», «SMART: revisar» (advertencia) o «SMART: riesgo de fallo» (grave: estado global, aviso crítico NVMe, reserva baja). Unos pocos sectores reasignados o errores de integridad (< 10 / < 20) se ignoran; el detalle sale al pasar el cursor. Sin SMART: «SMART no disponible».
* **Evaluación de vida útil y desgaste (Endurance):**
  * Total Escrito acumulado (**TBW - Terabytes Written**) a partir de registros SMART (`data_units_written` en NVMe o `Total_LBAs_Written` en SATA).
  * Ciclos de programación y borrado (**Ciclos P/E**) con cuadro informativo de referencia industrial (0-100: Excelente, 100-300: Muy bueno, 300-600: Uso moderado, >800: Desgaste alto).
  * Detección automática de discos mecánicos HDD, marcando los ciclos P/E como no aplicables.
* **Pruebas de lectura de bajo nivel (Device Read & NVMe Read Test):**
  * Ejecuta pruebas no destructivas en LBA 0 y bloques secundarios similares a las de Lenovo UEFI Diagnostics.
  * Si cualquiera de las dos pruebas de lectura (o ambas) falla, el sistema alerta automáticamente con `Posible bloqueo por cifrado TCG Opal` y orienta al técnico hacia el proceso de desbloqueo.
* **Desbloqueo TCG Opal / PSID Revert:**
  * Solo se aplica a SSD: NVMe o SATA SSD internos y SSD externos por USB. Los pendrives, discos duros (HDD) y tarjetas SD/eMMC no se consultan ni se ofrecen para desbloqueo; en un HDD, un fallo de lectura se informa como error de lectura y no como bloqueo Opal.
  * Escáner QR optimizado para pantallas de teléfonos móviles y cámaras web de baja resolución.
  * **Receptor Bluetooth Android nativo (OBEX):** Permite emparejar el celular y compartir el código PSID directamente por Bluetooth sin instalar aplicaciones ni usar redes locales.
  * Reversión de discos bloqueados con `sedutil-cli` y reseteo integral de particiones (`wipefs` + `parted`).
  * Compatibilidad con borrado criptográfico NVMe Sanitize / SES-2. Si el controlador rechaza todos los comandos de borrado, **no se toca** la tabla de particiones ni las firmas y el disco se informa como no borrado (un disco legible no cuenta como borrado). El estado «bloqueado por Opal» se lee del `Locked = Y` real de `sedutil-cli --query`.

### Teclado y Touchpad
* **Teclado:** Matriz visual interactiva de 78 teclas (distribuciones ANSI e ISO). Cada pulsación cambia de color progresivamente (verde, violeta, naranja, azul, amarillo) y contabiliza teclas presionadas sin que el navegador capture los atajos del sistema (`Tab`, `Alt`, `F1-F12`, `Super`). Mantener una tecla pulsada cuenta como una sola pulsación. Hacer clic en la matriz solo valida `Fn`, `Win` y `Super` (teclas que el navegador no recibe); el resto debe pulsarse físicamente, de modo que el test no se puede aprobar solo con el mouse.
* **Touchpad:** Lienzo para verificar continuidad del cursor y zonas muertas, además de contadores para clic izquierdo y clic derecho / gesto de 2 dedos. El trazo solo cuenta tras recorrer al menos 150 px (un simple clic en el lienzo no basta).

### Multimedia y conectividad
* **Cámara web:** vista previa y resolución. Se aprueba solo con la pista activa y una imagen que no sea negra (obturador tapado o sensor muerto se indican).
* **Audio:** Barrido senoidal estéreo (canal izquierdo, derecho y ambos) con control de volumen del sistema. Si suena mal, se marca con la ✗ del chip del checklist.
* **Micrófono:** medidor de nivel y grabación de 3 s con comprobación de amplitud. Conectado no basta: se aprueba solo al detectar señal real; sin señal en 6 s avisa.
* **Conectividad de red (Wi-Fi y Ethernet):**
  * **Wi-Fi:** Escaneo de redes inalámbricas cercanas (SSID y nivel de señal). El equipo nunca se conecta a ninguna red: la prueba valida la antena y el adaptador mediante el escaneo, sin conexión ni ping. Se muestran las 10 redes más fuertes (un AP por SSID) y se interpretan bien los SSID con `:`.
  * **Ethernet RJ-45:** Solo aparece (chip y tarjeta) si hay puerto: integrado o adaptador externo conectado. Ignora interfaces virtuales. Valida el enlace por cable. Una vez probado con éxito, la aprobación en el checklist se mantiene fija de forma persistente aunque el técnico desconecte el cable para continuar con otras pruebas.
  * **Diagnóstico automático de Loopback (TX/RX):** Comprobación inmediata de conectores loopback RJ-45 (pines 1-3 y 2-6 puenteados) mediante tramas de prueba capa 2 (EtherType `0x88B5`) sin necesidad de switch o infraestructura de red externa.
* **Bluetooth:** Detección del adaptador de radio y su dirección MAC, con su estado real: operativo, apagado, bloqueado por software o bloqueado por hardware (`rfkill`). Un radio bloqueado no aprueba el checklist.

### Prueba de estrés
* Carga configurable para CPU, memoria RAM, lectura de SSD y renderizado 3D WebGL. Cada fase **verifica sus resultados**; una fase que no puede verificarse se marca «SIN VERIFICAR» en lugar de aprobarse.
  * **CPU:** todos los hilos lógicos con `stress-ng` (`--cpu-method all` + `--matrix` + `--vecmath`, con `--verify`); si no está disponible, un proceso Python por CPU que repite cálculos FP, enteros y SHA-256 y compara con su valor de referencia. Un resultado distinto o una carga que termina antes de tiempo cuentan como fallo.
  * **RAM:** cada byte del buffer (hasta el 50 % / 65 % / 80 % de la memoria disponible según el nivel) se escribe y se relee con patrones sólidos (`00/FF/55/AA/0F/F0/33/CC`), *walking ones/zeros* y datos pseudoaleatorios distintos en bloques vecinos (detecta fallos de líneas de dirección). Se informa el número real de bytes con error y su posición.
  * **SSD:** lecturas directas (`O_DIRECT`) **de solo lectura** sobre los discos internos (nunca el USB de arranque): barrido secuencial de 1 MiB + lecturas aleatorias de 4 KiB con 8 hilos + relectura de zonas fijas comparando su contenido. Informa MB/s, IOPS, latencia máxima y caída de rendimiento (posible throttling del SSD). No se escribe nada: el sistema corre desde RAM (`toram`), por lo que un archivo temporal probaría la memoria y no el disco.
  * **GPU:** el navegador renderiza un shader de *raymarching* a 1280×720 con 4 pasadas por fotograma y reporta fotogramas, FPS medio/mínimo, pérdida de contexto WebGL y errores de shader; el veredicto sale de esas métricas.
* Duraciones: Rápida (~3.5 min), Media (~9 min) o Profunda (~26 min). La fase de CPU de la prueba rápida dura 75 s: 30 s de Turbo (descartados) y 45 s de carga sostenida.
* La temperatura máxima se muestra en ámbar desde 85 °C y en rojo desde 95 °C. El informe final es una línea por componente (OK / FALLÓ / SIN VERIFICAR) más el veredicto térmico corto.
* Protección térmica con tolerancia a picos normales de Turbo Boost (PL2) y parada automática de emergencia si la CPU sostiene >=100°C por más de 4 segundos o supera los 104°C.
* Informe final con la evaluación del sistema de enfriamiento y la recomendación de limpieza / cambio de pasta térmica (ver *Temperaturas, ventilación y salud térmica*).

### Adaptación a la pantalla
* La interfaz se escala sola según la resolución (diseñada para ~1600×900): en pantallas pequeñas se reduce (1366×768 → 85 %, 1280×720 → 80 %, mínimo 72 %), hasta Full HD se ve al 100 % y en 2K/4K se amplía (máx. 150 %). Las capas a pantalla completa (prueba de pantalla, ventanas) siguen ocupando toda la pantalla.

### Seguridad y blindaje corporativo (Modo Kiosk)
El objetivo es que el equipo solo pueda usarse para el diagnóstico: sin red, sin navegar fuera de la app y sin acceso a una terminal.

* **Sin conexión a red:**
  * Firewall `nftables` activo desde el arranque que descarta todo el tráfico IP (IPv4/IPv6) que no sea loopback. IPv6 deshabilitado por `sysctl`.
  * NetworkManager sin perfiles ni conexiones automáticas (`no-auto-default=*`) y sin chequeo de conectividad: al enchufar un cable no se pide DHCP.
  * El escaneo Wi-Fi, la detección de enlace Ethernet y el test de loopback RJ-45 (tramas capa 2) siguen funcionando porque no usan IP.
  * El backend escucha exclusivamente en `127.0.0.1:8080`.
* **Operación 100% local (Air-Gap):** Sin dependencias externas de internet; tipografía nativa del sistema operativo (`system-ui` / `ui-monospace`) y una `Content-Security-Policy` que impide a la interfaz cargar o contactar cualquier recurso fuera del servidor local.
* **Chrome bloqueado en la app:**
  * Directivas gestionadas con lista blanca de URL: solo se puede abrir `http://127.0.0.1:8080` (ni sitios web, ni `file://`, ni `chrome://`).
  * Sin diálogos de archivo, descargas, impresión, DevTools, extensiones, perfiles invitados ni modo incógnito.
  * La interfaz además bloquea arrastrar y soltar enlaces/archivos, el menú contextual del navegador y los atajos de navegación (`Ctrl + O/P/S/U/N/T`, `Alt + ←/→`, `F5`, etc.).
  * Watchdog que relanza Chrome si se cierra y reinicia el backend si se detiene.
* **Sin acceso a terminal:**
  * La ISO no incluye emulador de terminal (se elimina `xterm`, que el metapaquete `xorg` instala como dependencia) y el lanzador corre en segundo plano, sin ventana de consola.
  * Openbox sin atajos de teclado (`Alt + F4`, `Alt + Tab`…) y con el menú de escritorio vacío (el menú por defecto permite abrir una terminal).
  * Sin consolas virtuales: directivas X11 `DontVTSwitch` y `DontZap`, sin gettys en `tty2..tty6`, `Ctrl + Alt + Supr` y SysRq deshabilitados. Si la sesión gráfica termina, vuelve a iniciarse en lugar de caer a una shell.
  * GRUB protegido: las entradas arrancan sin contraseña, pero editar los parámetros del kernel (`e`) o abrir la consola (`c`) requiere la contraseña de administrador. isolinux (BIOS) no permite editar parámetros.
* **API local protegida:** Todas las acciones (PSID revert, borrado criptográfico, apagado, estrés, volumen, Bluetooth) exigen un token de sesión que el servidor inyecta en la página. Se rechazan las peticiones con `Host` u `Origin` ajenos y los dispositivos objetivo se validan (solo discos completos; nunca el pendrive de arranque).
* **Control de arranque:** Validación obligatoria de UEFI Secure Boot activo y módulo TPM 2.0 funcional al iniciar.

### Informe por Bluetooth
* Botón **Informe** (barra superior): genera un HTML de ~4 KB, sin recursos externos y legible en el celular, con datos del equipo, resultado del checklist (con detalle por prueba), la prueba de estrés si se ejecutó (por componente) y un campo de comentarios. En la prueba de estrés muestra temperatura máxima y promedio y, si ocurrió, el throttling térmico; el veredicto térmico es breve («Temperaturas altas» / «Sobrecalentamiento») con una precaución corta, y **sin** recomendación de mantenimiento.
* Formato **PDF** o **HTML** (selector junto al botón de envío). El PDF se genera con el Chrome de la imagen en modo sin pantalla (perfil aparte, unos 100 KB); solo se guarda y envía el formato elegido.
* **Enviar por Bluetooth** busca celulares cercanos (8 s), se elige uno y se envía por OBEX Object Push con `bluez-obexd` (vía `gdbus`). En el celular solo hay que tener Bluetooth visible y pulsar *Aceptar*. Si el envío vía `obexd` falla, se empareja una vez (un toque, sin códigos) y se envía con un cliente OBEX propio por RFCOMM (la cola de errores muestra ambos motivos). **Ver** muestra una vista previa.
* El informe se guarda en `/tmp/diagnost_reports/` (RAM en el Live: no queda nada en el equipo).

### Checklist y control de energía
* Barra superior fija con el estado de aprobación en mayúsculas de cada test.
* Cada chip del checklist tiene una **✗** para marcar la prueba como fallida a mano (p. ej. un HDMI que no se detecta): queda en rojo aunque la app la dé por buena, otro clic la quita y **Reiniciar** borra las marcas. El teclado tiene además un botón «Marcar fallo». Las marcas se reflejan como «Falló» en el informe.
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
│   └── static/                   # Frontend web (HTML, CSS y JS modular, sin build)
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
├── tests/                        # Tests unitarios (unittest, sin dependencias): estrés, diagnósticos, servidor, térmica, rendimiento
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

> Fuera de la ISO (sin `boot=live` en la línea de comandos del kernel), `start_qa.sh` omite el firewall y la verificación de Secure Boot/TPM, para no bloquear la red ni reiniciar el equipo de desarrollo.

### Ejecutar los tests
```bash
python3 -m unittest discover -s tests -v
```

### Compilar una nueva imagen ISO
El proceso de compilación se ejecuta dentro de un contenedor Docker con Ubuntu 24.04:

```bash
cd builder
sudo ./build_live_iso.sh
```

* **Versionado inteligente:** Si la versión definida en el código es mayor a la última ISO existente en `ISOs/`, se compila directamente con esa versión. Si es menor o igual, suma automáticamente `+1` a la última ISO creada.
* **Seguridad y compatibilidad:** Incluye montaje automático de certificados CA del host para descargas seguras por repositorios HTTPS.
* **Contraseña de GRUB:** Para poder editar parámetros de arranque en el menú de GRUB (usuario `admin`), define la contraseña al compilar:
  ```bash
  sudo GRUB_ADMIN_PASSWORD='tu-contraseña' ./build_live_iso.sh
  ```
  Si no se define, se usa una contraseña aleatoria que no se guarda y la edición queda deshabilitada de forma permanente en esa ISO.

---

## Grabación en pendrive USB

### Linux (`dd`)
```bash
sudo dd if=ISOs/diagnost-donor_1.1.23_linux-live.iso of=/dev/sdX bs=4M status=progress conv=fsync
```
*(Reemplaza `/dev/sdX` por la unidad correspondiente a tu pendrive).*

### Windows (Rufus / BalenaEtcher)
1. Abre **Rufus** o **BalenaEtcher**.
2. Selecciona la imagen ISO.
3. Selecciona la unidad USB de destino.
4. Graba la imagen (en Rufus, si pregunta el modo de escritura, selecciona **Modo Imagen DD**).