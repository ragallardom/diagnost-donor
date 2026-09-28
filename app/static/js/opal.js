/* ==============================================================================
   DIAGNOSTDONOR - TCG OPAL / MCAFEE PSID REVERT MODULE (js/opal.js)
   Hardware disk crypto-erase via sedutil and integrated high-speed QR Scanner.
   Optimized for laptop webcams scanning mobile phone screens & physical labels.
   ============================================================================== */

let qrStream = null;
let qrAnimId = null;
let isProcessingQrFrame = false;
let zxingReaderInstance = null;
let nativeBarcodeDetector = null;

// Initialize native BarcodeDetector if available in browser
if (typeof window !== "undefined" && "BarcodeDetector" in window) {
  try {
    nativeBarcodeDetector = new window.BarcodeDetector({
      formats: ["qr_code", "data_matrix", "code_128", "code_39"]
    });
  } catch (e) {
    console.warn("BarcodeDetector init warning:", e);
  }
}

// Lazy ZXing Reader factory
function getZxingReader() {
  if (!zxingReaderInstance && typeof window !== "undefined" && window.ZXing) {
    try {
      const hints = new Map();
      hints.set(window.ZXing.DecodeHintType.POSSIBLE_FORMATS, [
        window.ZXing.BarcodeFormat.QR_CODE,
        window.ZXing.BarcodeFormat.DATA_MATRIX,
        window.ZXing.BarcodeFormat.CODE_128,
        window.ZXing.BarcodeFormat.CODE_39
      ]);
      hints.set(window.ZXing.DecodeHintType.TRY_HARDER, true);

      zxingReaderInstance = new window.ZXing.MultiFormatReader();
      zxingReaderInstance.setHints(hints);
    } catch (e) {
      console.warn("ZXing init warning:", e);
    }
  }
  return zxingReaderInstance;
}

// Audio chime for immediate tactile scan feedback
function playQrSuccessChime() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();
    const now = ctx.currentTime;

    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(880, now);
    osc1.frequency.exponentialRampToValueAtTime(1760, now + 0.12);
    gain1.gain.setValueAtTime(0.2, now);
    gain1.gain.exponentialRampToValueAtTime(0.01, now + 0.15);

    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.15);
  } catch (e) {
    // Audio feedback is purely non-critical enhancement
  }
}

// ─────────────────────────────────────────────────────────────────
// 1. MODAL OPEN / CLOSE & INITIALIZATION
// ─────────────────────────────────────────────────────────────────
async function openOpalModal() {
  const modal = document.getElementById("opal-modal");
  if (modal) modal.style.display = "flex";

  // 1. Release main dashboard camera stream to avoid hardware exclusive lock
  if (typeof stopCamera === "function") {
    try {
      stopCamera();
    } catch (e) {
      console.warn("stopCamera warning:", e);
    }
  }

  // 2. Reset PSID input & visual validation state
  const psidInput = document.getElementById("opal-psid-input");
  if (psidInput) {
    psidInput.value = "";
    psidInput.style.borderColor = "";
  }
  updatePsidCounter();

  // 3. Clear results banner & execution logs
  const resultBanner = document.getElementById("opal-result-banner");
  if (resultBanner) resultBanner.innerHTML = "";

  const logContainer = document.getElementById("opal-log-container");
  if (logContainer) logContainer.style.display = "none";
  const logPre = document.getElementById("opal-log-output");
  if (logPre) logPre.innerText = "";

  // 4. Reset reticle state
  const reticle = document.getElementById("qr-target-reticle");
  if (reticle) reticle.classList.remove("detected");

  // 5. Fetch target drives list
  await fetchOpalDrives();

  // 6. Automatically start high-speed QR Scanner
  await startQrScanner();

  // 7. Automatically start Bluetooth PSID receiver for direct phone sharing
  await startBluetoothReceiver();

  // 8. Autofocus on PSID input for keyboard convenience
  setTimeout(() => {
    if (psidInput) psidInput.focus();
  }, 200);
}

function closeOpalModal() {
  stopQrScanner();
  stopBluetoothReceiver();
  const confirmModal = document.getElementById("opal-confirm-modal");
  if (confirmModal) confirmModal.style.display = "none";
  const modal = document.getElementById("opal-modal");
  if (modal) modal.style.display = "none";
}

// ─────────────────────────────────────────────────────────────────
let cachedOpalDrives = [];

async function fetchOpalDrives() {
  const select = document.getElementById("opal-drive-select");
  if (!select) return;

  const currentSelected = select.value;
  select.innerHTML = `<option value="">Cargando unidades de disco...</option>`;

  try {
    const res = await fetch("/api/drives");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const drives = await res.json();
    cachedOpalDrives = Array.isArray(drives) ? drives : [];

    if (!Array.isArray(drives) || drives.length === 0) {
      select.innerHTML = `<option value="">No se detectaron unidades SSD / SED</option>`;
      handleDriveSelectionChange();
      return;
    }

    select.innerHTML = drives.map(d => {
      const dev = d.device || d.name || "";
      const model = d.model || "Disco SSD";
      const type = d.type || (d.transport ? `${d.transport} SSD` : "SSD");
      const lockedBadge = d.is_opal_locked ? " [BLOQUEADO OPAL/SED]" : "";
      return `<option value="${dev}">${dev} - ${model} (${type})${lockedBadge}</option>`;
    }).join("");

    if (currentSelected && Array.from(select.options).some(o => o.value === currentSelected)) {
      select.value = currentSelected;
    }
    handleDriveSelectionChange();
  } catch (err) {
    console.error("Error cargando unidades:", err);
    select.innerHTML = `
      <option value="/dev/nvme0n1">/dev/nvme0n1 (SSD NVMe Principal)</option>
      <option value="/dev/sda">/dev/sda (SSD/HDD SATA)</option>
    `;
    handleDriveSelectionChange();
  }
}

function handleDriveSelectionChange() {
  // Target drive changed in select dropdown
}

function openOpalModalWithDrive(targetDevice) {
  if (typeof openOpalModal === "function") openOpalModal();
  if (targetDevice) {
    setTimeout(() => {
      const select = document.getElementById("opal-drive-select");
      if (select) {
        select.value = targetDevice;
        handleDriveSelectionChange();
      }
    }, 200);
  }
}

// ─────────────────────────────────────────────────────────────────
// 3. HIGH-SPEED QR SCANNER PIPELINE (PHONE SCREENS & WEBCAMS)
// ─────────────────────────────────────────────────────────────────
async function startQrScanner() {
  const video = document.getElementById("qr-scanner-video");
  const overlay = document.getElementById("qr-scan-status-overlay");
  const reticle = document.getElementById("qr-target-reticle");
  if (!video) return;

  if (reticle) reticle.classList.remove("detected");

  try {
    if (qrStream) {
      qrStream.getTracks().forEach(t => t.stop());
      qrStream = null;
    }
    if (qrAnimId) {
      cancelAnimationFrame(qrAnimId);
      qrAnimId = null;
    }

    if (overlay) {
      overlay.style.display = "flex";
      overlay.innerText = "Iniciando cámara web para escáner...";
      overlay.style.color = "var(--text-main)";
    }

    // Step 1: Request optimal resolution for laptop front webcam (User-facing)
    try {
      qrStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "user" },
          width: { ideal: 1920, min: 1280 },
          height: { ideal: 1080, min: 720 },
          frameRate: { ideal: 30, min: 15 }
        },
        audio: false
      });
    } catch (e1) {
      console.warn("Intento con resolución alta falló, reintentando estándar:", e1);
      qrStream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 1280, min: 640 },
          height: { ideal: 720, min: 480 }
        },
        audio: false
      });
    }

    // Step 2: Apply advanced continuous autofocus & exposure if hardware supports it
    try {
      const track = qrStream.getVideoTracks()[0];
      if (track && track.getCapabilities) {
        const caps = track.getCapabilities();
        const advancedConstraints = [];
        if (caps.focusMode && caps.focusMode.includes("continuous")) {
          advancedConstraints.push({ focusMode: "continuous" });
        }
        if (caps.exposureMode && caps.exposureMode.includes("continuous")) {
          advancedConstraints.push({ exposureMode: "continuous" });
        }
        if (advancedConstraints.length > 0) {
          await track.applyConstraints({ advanced: advancedConstraints });
        }
      }
    } catch (eTrack) {
      console.warn("Ajuste de capacidades de cámara no soportado:", eTrack);
    }

    video.srcObject = qrStream;
    await video.play().catch(e => console.warn("Video QR play() diferido:", e));

    if (overlay) {
      overlay.style.display = "none";
    }

    isProcessingQrFrame = false;
    scanQrLoop();
  } catch (err) {
    console.error("Error accediendo a cámara para escaneo QR:", err);
    if (overlay) {
      overlay.style.display = "flex";
      overlay.style.color = "#fca5a5";
      if (err.name === "NotReadableError" || err.name === "TrackStartError") {
        overlay.innerText = "La cámara está en uso por otro proceso. Puedes escribir el PSID abajo.";
      } else if (err.name === "NotFoundError" || err.name === "DevicesNotFoundError") {
        overlay.innerText = "No se detectó cámara web. Ingresa el código PSID manualmente.";
      } else {
        overlay.innerText = `Cámara no disponible (${err.message || "Error"}). Escribe el PSID manualmente.`;
      }
    }
  }
}

function stopQrScanner() {
  if (qrAnimId) {
    cancelAnimationFrame(qrAnimId);
    qrAnimId = null;
  }
  if (qrStream) {
    qrStream.getTracks().forEach(t => t.stop());
    qrStream = null;
  }
  const video = document.getElementById("qr-scanner-video");
  if (video) video.srcObject = null;

  const overlay = document.getElementById("qr-scan-status-overlay");
  if (overlay) {
    overlay.style.display = "flex";
    overlay.innerText = "Cámara de escaneo inactiva";
    overlay.style.color = "var(--text-muted)";
  }
}

// ─────────────────────────────────────────────────────────────────
// 4. MULTI-ENGINE FRAME PROCESSING & PHONE SCREEN ADAPTIVE FILTERS
// ─────────────────────────────────────────────────────────────────
let cropCanvas = null;

async function scanQrLoop() {
  if (!qrStream) return;
  const video = document.getElementById("qr-scanner-video");
  const canvas = document.getElementById("qr-canvas");

  if (!video || !canvas || video.readyState < video.HAVE_CURRENT_DATA || video.videoWidth === 0) {
    qrAnimId = requestAnimationFrame(scanQrLoop);
    return;
  }

  if (isProcessingQrFrame) {
    qrAnimId = requestAnimationFrame(scanQrLoop);
    return;
  }

  isProcessingQrFrame = true;

  try {
    const vW = video.videoWidth;
    const vH = video.videoHeight;

    canvas.width = vW;
    canvas.height = vH;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(video, 0, 0, vW, vH);

    // Setup Center Crop (ROI Zoom) where user points their phone
    if (!cropCanvas) {
      cropCanvas = document.createElement("canvas");
    }
    const cropSize = Math.floor(Math.min(vW, vH) * 0.65);
    const cropX = Math.floor((vW - cropSize) / 2);
    const cropY = Math.floor((vH - cropSize) / 2);

    cropCanvas.width = cropSize;
    cropCanvas.height = cropSize;
    const cropCtx = cropCanvas.getContext("2d", { willReadFrequently: true });
    cropCtx.drawImage(canvas, cropX, cropY, cropSize, cropSize, 0, 0, cropSize, cropSize);

    let detectedText = null;

    // ── STAGE 1: NATIVE CHROMIUM BARCODE DETECTOR (Fastest & GPU Accelerated) ──
    if (nativeBarcodeDetector) {
      try {
        const barcodes = await nativeBarcodeDetector.detect(video);
        if (barcodes && barcodes.length > 0 && barcodes[0].rawValue) {
          detectedText = barcodes[0].rawValue;
        }
      } catch (e) {
        // Fallthrough
      }

      if (!detectedText) {
        try {
          const cropBarcodes = await nativeBarcodeDetector.detect(cropCanvas);
          if (cropBarcodes && cropBarcodes.length > 0 && cropBarcodes[0].rawValue) {
            detectedText = cropBarcodes[0].rawValue;
          }
        } catch (e) {
          // Fallthrough
        }
      }
    }

    // ── STAGE 2: ZXING MULTI-FORMAT READER (Hybrid & Histogram Binarizers) ──
    if (!detectedText && typeof window !== "undefined" && window.ZXing) {
      const zReader = getZxingReader();
      if (zReader) {
        // Try on crop ROI first
        detectedText = decodeWithZxing(cropCtx, cropSize, cropSize, zReader);
        // If not found, try full frame
        if (!detectedText) {
          detectedText = decodeWithZxing(ctx, vW, vH, zReader);
        }
      }
    }

    // ── STAGE 3: MULTI-PASS PREPROCESSED JSQR (Phone Screen Glare & Inversion) ──
    if (!detectedText && (typeof jsQR !== "undefined" || window.jsQR)) {
      const decoder = typeof jsQR !== "undefined" ? jsQR : window.jsQR;

      // Pass 3A: Center Crop direct
      const cropImgData = cropCtx.getImageData(0, 0, cropSize, cropSize);
      let qrCode = decoder(cropImgData.data, cropSize, cropSize, { inversionAttempts: "attemptBoth" });

      // Pass 3B: Phone Screen Dynamic Contrast Normalization (Fixes white screen blowout)
      if (!qrCode) {
        const stretchedData = applyContrastStretch(cropImgData.data);
        if (stretchedData) {
          qrCode = decoder(stretchedData, cropSize, cropSize, { inversionAttempts: "attemptBoth" });
        }
      }

      // Pass 3C: Adaptive Local Thresholding (Sauvola/Bradley integral binarizer for screen glare)
      if (!qrCode) {
        const adaptiveData = applyAdaptiveLocalThreshold(cropImgData.data, cropSize, cropSize);
        if (adaptiveData) {
          qrCode = decoder(adaptiveData, cropSize, cropSize, { inversionAttempts: "dontInvert" });
        }
      }

      // Pass 3D: Full frame direct fallback
      if (!qrCode) {
        const fullImgData = ctx.getImageData(0, 0, vW, vH);
        qrCode = decoder(fullImgData.data, vW, vH, { inversionAttempts: "attemptBoth" });
      }

      if (qrCode && qrCode.data) {
        detectedText = qrCode.data;
      }
    }

    // Handle successfully detected QR code
    if (detectedText) {
      handleQrDetectionSuccess(detectedText);
      return;
    }
  } catch (err) {
    console.warn("Error en ciclo de escaneo QR:", err);
  } finally {
    isProcessingQrFrame = false;
  }

  qrAnimId = requestAnimationFrame(scanQrLoop);
}

// ZXing Decoder Helper with Hybrid and Inverted Fallbacks
function decodeWithZxing(ctx, width, height, reader) {
  try {
    const imgData = ctx.getImageData(0, 0, width, height);
    const len = width * height;
    const rgb32 = new Int32Array(len);
    const data = imgData.data;

    for (let i = 0; i < len; i++) {
      const off = i * 4;
      rgb32[i] = (data[off + 3] << 24) | (data[off] << 16) | (data[off + 1] << 8) | data[off + 2];
    }

    const source = new window.ZXing.RGBLuminanceSource(rgb32, width, height);
    const bitmap = new window.ZXing.BinaryBitmap(new window.ZXing.HybridBinarizer(source));

    try {
      const res = reader.decodeWithState(bitmap);
      if (res && res.getText()) return res.getText();
    } catch (eHybrid) {
      // Try inverted luminance
      try {
        const invSource = source.invert();
        const invBitmap = new window.ZXing.BinaryBitmap(new window.ZXing.HybridBinarizer(invSource));
        const resInv = reader.decodeWithState(invBitmap);
        if (resInv && resInv.getText()) return resInv.getText();
      } catch (eInv) {
        // Try GlobalHistogramBinarizer for extreme contrast phone screens
        try {
          const histBitmap = new window.ZXing.BinaryBitmap(new window.ZXing.GlobalHistogramBinarizer(source));
          const resHist = reader.decodeWithState(histBitmap);
          if (resHist && resHist.getText()) return resHist.getText();
        } catch (eHist) {
          // Not found in this frame
        }
      }
    } finally {
      reader.reset();
    }
  } catch (err) {
    // Non-fatal frame decode error
  }
  return null;
}

// Contrast stretching filter for phone screens with overexposed white background
function applyContrastStretch(rgbaData) {
  const len = rgbaData.length;
  let minLum = 255;
  let maxLum = 0;

  for (let i = 0; i < len; i += 4) {
    const lum = (rgbaData[i] * 77 + rgbaData[i + 1] * 150 + rgbaData[i + 2] * 29) >> 8;
    if (lum < minLum) minLum = lum;
    if (lum > maxLum) maxLum = lum;
  }

  const range = maxLum - minLum;
  if (range < 20) return null;

  const output = new Uint8ClampedArray(len);
  const factor = 255 / range;

  for (let i = 0; i < len; i += 4) {
    const lum = (rgbaData[i] * 77 + rgbaData[i + 1] * 150 + rgbaData[i + 2] * 29) >> 8;
    const stretched = Math.min(255, Math.max(0, Math.floor((lum - minLum) * factor)));
    output[i] = stretched;
    output[i + 1] = stretched;
    output[i + 2] = stretched;
    output[i + 3] = 255;
  }
  return output;
}

// Adaptive local integral thresholding for uneven reflections & phone screen angles
function applyAdaptiveLocalThreshold(rgbaData, width, height) {
  const S = Math.max(8, Math.floor(width * 0.08));
  const s2 = Math.floor(S / 2);
  const integral = new Uint32Array(width * height);
  const gray = new Uint8Array(width * height);

  for (let y = 0; y < height; y++) {
    let sum = 0;
    for (let x = 0; x < width; x++) {
      const idx = (y * width + x) * 4;
      const lum = (rgbaData[idx] * 77 + rgbaData[idx + 1] * 150 + rgbaData[idx + 2] * 29) >> 8;
      gray[y * width + x] = lum;
      sum += lum;
      integral[y * width + x] = (y === 0 ? 0 : integral[(y - 1) * width + x]) + sum;
    }
  }

  const output = new Uint8ClampedArray(rgbaData.length);
  const factor = 0.88; // 12% darker than local mean

  for (let y = 0; y < height; y++) {
    const y1 = Math.max(0, y - s2);
    const y2 = Math.min(height - 1, y + s2);
    for (let x = 0; x < width; x++) {
      const x1 = Math.max(0, x - s2);
      const x2 = Math.min(width - 1, x + s2);
      const count = (x2 - x1 + 1) * (y2 - y1 + 1);

      const A = y1 > 0 && x1 > 0 ? integral[(y1 - 1) * width + (x1 - 1)] : 0;
      const B = y1 > 0 ? integral[(y1 - 1) * width + x2] : 0;
      const C = x1 > 0 ? integral[y2 * width + (x1 - 1)] : 0;
      const D = integral[y2 * width + x2];
      const sum = D - B - C + A;

      const mean = sum / count;
      const val = gray[y * width + x] < mean * factor ? 0 : 255;
      const outIdx = (y * width + x) * 4;
      output[outIdx] = val;
      output[outIdx + 1] = val;
      output[outIdx + 2] = val;
      output[outIdx + 3] = 255;
    }
  }
  return output;
}

// ─────────────────────────────────────────────────────────────────
// 5. PSID EXTRACTION & DETECTION SUCCESS HANDLER
// ─────────────────────────────────────────────────────────────────
function extractPsidFromText(text) {
  if (!text) return "";
  let clean = text.trim();

  // 1. Strip HTML head, style, script
  clean = clean.replace(/<head[\s\S]*?<\/head>/gi, "");
  clean = clean.replace(/<script[\s\S]*?<\/script>/gi, "");
  clean = clean.replace(/<style[\s\S]*?<\/style>/gi, "");

  // 2. Strip all HTML tags (<a href...>, <body>, etc.)
  clean = clean.replace(/<[^>]+>/g, "").trim();

  // 3. Strip prefixes like PSID:, SERIAL:, S/N:, KEY:
  clean = clean.replace(/^(PSID|SERIAL|SN|S\/N|KEY|CODIGO|QR)[:=\s]+/i, "").trim();

  // 4. If contains direct 32-character hexadecimal/alphanumeric sequence
  const match32 = clean.match(/[A-Za-z0-9]{32}/);
  if (match32) {
    return match32[0].toUpperCase();
  }

  // 5. If formatted with hyphens or spaces (e.g. W97C-82K1-9LPX-4821-N309-1LAK-9218-3921)
  const stripped = clean.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  if (stripped.startsWith("PSID") && stripped.length >= 36) {
    return stripped.substring(4, 36);
  }
  if (stripped.length >= 32) {
    return stripped.substring(0, 32);
  }
  if (stripped.length >= 16) {
    return stripped;
  }
  return clean;
}

function handleQrDetectionSuccess(rawCodeText) {
  const psid = extractPsidFromText(rawCodeText);
  if (!psid || psid.length < 10) return;

  const psidInput = document.getElementById("opal-psid-input");
  const overlay = document.getElementById("qr-scan-status-overlay");
  const reticle = document.getElementById("qr-target-reticle");

  playQrSuccessChime();

  if (reticle) reticle.classList.add("detected");

  if (psidInput) {
    psidInput.value = psid.substring(0, 32);
    psidInput.style.borderColor = "var(--success-green)";
    updatePsidCounter();
  }

  if (overlay) {
    overlay.style.display = "flex";
    overlay.innerText = `Código QR detectado: ${psid.substring(0, 32)}`;
    overlay.style.color = "var(--success-green)";
  }

  stopQrScanner();
}

// ─────────────────────────────────────────────────────────────────
// 6. PSID INPUT VALIDATOR & FORMATTER
// ─────────────────────────────────────────────────────────────────
function handlePsidInputChange(e) {
  const input = e.target || document.getElementById("opal-psid-input");
  if (!input) return;

  const clean = input.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  if (input.value !== clean) {
    input.value = clean;
  }
  updatePsidCounter();
}

function updatePsidCounter() {
  const input = document.getElementById("opal-psid-input");
  const counter = document.getElementById("psid-char-counter");
  if (!input || !counter) return;

  const len = input.value.length;
  counter.innerText = `${len} / 32 caracteres`;

  if (len === 32) {
    counter.style.color = "var(--success-green)";
    input.style.borderColor = "var(--success-green)";
  } else if (len > 0 && len < 32) {
    counter.style.color = "#f59e0b";
    input.style.borderColor = "#f59e0b";
  } else {
    counter.style.color = "var(--text-muted)";
    input.style.borderColor = "";
  }
}

// Listen for input events on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  const psidInput = document.getElementById("opal-psid-input");
  if (psidInput) {
    psidInput.addEventListener("input", handlePsidInputChange);
    psidInput.addEventListener("paste", () => setTimeout(handlePsidInputChange, 50));
  }
});

// ─────────────────────────────────────────────────────────────────
// 7. BLUETOOTH WIRELESS RECEIVER (DIRECT ANDROID SHARING / OBEX)
// ─────────────────────────────────────────────────────────────────
let btReceiverPollTimer = null;
let lastSeenBtTimestamp = 0;

async function startBluetoothReceiver() {
  stopBluetoothReceiver();

  const statusText = document.getElementById("bt-receiver-status-text");
  const dot = document.getElementById("bt-receiver-dot");
  if (statusText) statusText.innerText = 'Iniciando receptor Bluetooth ("DIAGNOST-DONOR")...';

  try {
    const res = await apiPost("/api/bluetooth-receiver/start", { name: "DIAGNOST-DONOR" });
    const data = await res.json();

    if (statusText) {
      if (data.active) {
        statusText.innerText = 'Receptor activo y visible como "DIAGNOST-DONOR"';
        if (dot) dot.className = "status-dot online";
      } else {
        statusText.innerText = "Adaptador Bluetooth no detectado o inactivo";
        if (dot) dot.className = "status-dot offline";
      }
    }

    if (data.last_timestamp) {
      lastSeenBtTimestamp = data.last_timestamp;
    }
  } catch (err) {
    console.warn("Error iniciando receptor Bluetooth:", err);
    if (statusText) statusText.innerText = "Servicio Bluetooth en espera...";
  }

  // Poll for incoming transfers
  btReceiverPollTimer = setInterval(pollBluetoothReceiverStatus, 1000);
}

async function pollBluetoothReceiverStatus() {
  try {
    const res = await fetch("/api/bluetooth-psid-status");
    if (!res.ok) return;
    const data = await res.json();

    const statusText = document.getElementById("bt-receiver-status-text");
    const dot = document.getElementById("bt-receiver-dot");

    if (statusText && data.active) {
      statusText.innerText = `Receptor activo y visible como "${data.device_name || 'DIAGNOST-DONOR'}"`;
      if (dot) dot.className = "status-dot online";
    }

    // Check if new PSID was received over Bluetooth
    if (data.last_psid && data.last_timestamp && data.last_timestamp > lastSeenBtTimestamp) {
      lastSeenBtTimestamp = data.last_timestamp;

      const psidInput = document.getElementById("opal-psid-input");
      const banner = document.getElementById("opal-result-banner");

      if (psidInput) {
        psidInput.value = data.last_psid.substring(0, 32);
        psidInput.style.borderColor = "var(--success-green)";
        updatePsidCounter();
      }

      playQrSuccessChime();

      if (banner) {
        banner.innerHTML = `
          <div style="background: rgba(16, 185, 129, 0.15); border: 1px solid var(--success-green); padding: 0.85rem 1rem; border-radius: 8px; color: var(--text-main); margin-bottom: 0.75rem;">
            <div style="font-weight: 700; color: var(--success-green); margin-bottom: 0.25rem;">Código PSID recibido por Bluetooth</div>
            <div style="font-family: var(--font-mono); font-size: 0.92rem; color: #a7f3d0; font-weight: 600;">${data.last_psid.substring(0, 32)}</div>
          </div>
        `;
      }

      // Stop camera if it was scanning
      stopQrScanner();
    }
  } catch (err) {
    // Non-critical poll error
  }
}

function stopBluetoothReceiver() {
  if (btReceiverPollTimer) {
    clearInterval(btReceiverPollTimer);
    btReceiverPollTimer = null;
  }
}

async function restartBluetoothReceiver() {
  const statusText = document.getElementById("bt-receiver-status-text");
  if (statusText) statusText.innerText = "Haciendo visible el equipo por Bluetooth...";
  await startBluetoothReceiver();
}

