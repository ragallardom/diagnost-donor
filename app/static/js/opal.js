/* ==============================================================================
   DIAGNOSTDONOR - TCG OPAL / MCAFEE PSID REVERT MODULE (js/opal.js)
   Hardware disk crypto-erase via sedutil and integrated QR Camera Scanner.
   ============================================================================== */

let qrStream = null;
let qrAnimId = null;

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

  // 4. Fetch target drives list
  await fetchOpalDrives();

  // 5. Automatically start QR Scanner
  await startQrScanner();

  // 6. Autofocus on PSID input for keyboard convenience
  setTimeout(() => {
    if (psidInput) psidInput.focus();
  }, 200);
}

function closeOpalModal() {
  stopQrScanner();
  const modal = document.getElementById("opal-modal");
  if (modal) modal.style.display = "none";
}

// ─────────────────────────────────────────────────────────────────
// 2. DRIVE LIST POPULATOR & REFRESH
// ─────────────────────────────────────────────────────────────────
async function fetchOpalDrives() {
  const select = document.getElementById("opal-drive-select");
  if (!select) return;

  const currentSelected = select.value;
  select.innerHTML = `<option value="">Cargando unidades de disco...</option>`;

  try {
    const res = await fetch("/api/drives");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const drives = await res.json();

    if (!Array.isArray(drives) || drives.length === 0) {
      select.innerHTML = `<option value="">No se detectaron unidades SSD / SED</option>`;
      return;
    }

    select.innerHTML = drives.map(d => {
      const dev = d.device || d.name || "";
      const model = d.model || "Disco SSD";
      const type = d.type || (d.transport ? `${d.transport} SSD` : "SSD");
      const lockedBadge = d.is_opal_locked ? " 🔒 [BLOQUEADO OPAL/SED]" : "";
      return `<option value="${dev}">${dev} - ${model} (${type})${lockedBadge}</option>`;
    }).join("");

    if (currentSelected && Array.from(select.options).some(o => o.value === currentSelected)) {
      select.value = currentSelected;
    }
  } catch (err) {
    console.error("Error cargando unidades:", err);
    select.innerHTML = `
      <option value="/dev/nvme0n1">/dev/nvme0n1 (SSD NVMe Principal)</option>
      <option value="/dev/sda">/dev/sda (SSD/HDD SATA)</option>
    `;
  }
}

// ─────────────────────────────────────────────────────────────────
// 3. QR WEBCAM SCANNER PIPELINE (FOR SSD PSID BARCODES/QR)
// ─────────────────────────────────────────────────────────────────
async function startQrScanner() {
  const video = document.getElementById("qr-scanner-video");
  const overlay = document.getElementById("qr-scan-status-overlay");
  if (!video) return;

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

    // First attempt: environment/back camera (if available), else default
    try {
      qrStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1280, min: 640 },
          height: { ideal: 720, min: 480 }
        },
        audio: false
      });
    } catch (e1) {
      console.warn("Intento con constraints avanzados falló, reintentando básico:", e1);
      qrStream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false
      });
    }

    video.srcObject = qrStream;
    await video.play().catch(e => console.warn("Video QR play() diferido:", e));

    if (overlay) {
      overlay.style.display = "none";
    }

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

function scanQrLoop() {
  const video = document.getElementById("qr-scanner-video");
  const canvas = document.getElementById("qr-canvas");
  const overlay = document.getElementById("qr-scan-status-overlay");
  const psidInput = document.getElementById("opal-psid-input");

  if (!video || !canvas || !qrStream) return;

  if (video.readyState >= video.HAVE_CURRENT_DATA && video.videoWidth > 0 && video.videoHeight > 0) {
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);

    // Decodificar con jsQR
    if (typeof jsQR !== "undefined" || window.jsQR) {
      const decoder = typeof jsQR !== "undefined" ? jsQR : window.jsQR;
      let code = decoder(imageData.data, imageData.width, imageData.height, {
        inversionAttempts: "dontInvert"
      });

      if (!code) {
        code = decoder(imageData.data, imageData.width, imageData.height, {
          inversionAttempts: "attemptBoth"
        });
      }

      if (code && code.data) {
        const raw = code.data.trim().replace(/[^A-Za-z0-9]/g, "").toUpperCase();
        if (raw.length >= 16) {
          if (psidInput) {
            psidInput.value = raw.substring(0, 32);
            psidInput.style.borderColor = "var(--success-green)";
            updatePsidCounter();
          }
          if (overlay) {
            overlay.style.display = "flex";
            overlay.innerText = `¡Código QR detectado!: ${raw.substring(0, 32)}`;
            overlay.style.color = "var(--success-green)";
          }
          stopQrScanner();
          return;
        }
      }
    }
  }

  qrAnimId = requestAnimationFrame(scanQrLoop);
}

// ─────────────────────────────────────────────────────────────────
// 4. PSID INPUT VALIDATOR & FORMATTER
// ─────────────────────────────────────────────────────────────────
function handlePsidInputChange(e) {
  const input = e.target || document.getElementById("opal-psid-input");
  if (!input) return;

  // Auto clean dashes, spaces, lowercase
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
