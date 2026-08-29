/* DIAGNOSTDONOR - Application Logic */

// Global State
let audioContext = null;
let micStream = null;
let micAnalyser = null;
let micAnimId = null;
let cameraStream = null;

let qrStream = null;
let qrAnimId = null;

let pressedKeysSet = new Set();
let keyPressCounts = {}; // Rastreo de pulsaciones por tecla para ciclar colores
// KEYBOARD MATRIX STATE & MULTI-TOUCH COLOR SEQUENCE (VERDE -> VIOLETA -> NARANJO -> AZUL -> AMARILLO)
const KEY_COLOR_CLASSES = ["color-green", "color-violet", "color-orange", "color-blue", "color-yellow"];
let totalKeyPresses = 0;

// Touchpad test flags
let touchpadLeftClicked = false;
let touchpadRightClicked = false;
let touchpadDrawn = false;

// Audio test flags (requires 3/3 buttons)
let audioLeftTested = false;
let audioRightTested = false;
let audioBothTested = false;

const keyboardLayout = [
  ["Escape", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12", "Delete"],
  ["Backquote", "Digit1", "Digit2", "Digit3", "Digit4", "Digit5", "Digit6", "Digit7", "Digit8", "Digit9", "Digit0", "Minus", "Equal", "Backspace"],
  ["Tab", "KeyQ", "KeyW", "KeyE", "KeyR", "KeyT", "KeyY", "KeyU", "KeyI", "KeyO", "KeyP", "BracketLeft", "BracketRight", "Backslash"],
  ["CapsLock", "KeyA", "KeyS", "KeyD", "KeyF", "KeyG", "KeyH", "KeyJ", "KeyK", "KeyL", "Semicolon", "Quote", "Enter"],
  ["ShiftLeft", "KeyZ", "KeyX", "KeyC", "KeyV", "KeyB", "KeyN", "KeyM", "Comma", "Period", "Slash", "ShiftRight"],
  ["ControlLeft", "Fn", "MetaLeft", "AltLeft", "Space", "AltRight", "ControlRight", "ArrowLeft", "ArrowUp", "ArrowDown", "ArrowRight"]
];

const keyDisplayNames = {
  "Escape": "Esc", "Backquote": "~ `", "Digit1": "1", "Digit2": "2", "Digit3": "3", "Digit4": "4", "Digit5": "5",
  "Digit6": "6", "Digit7": "7", "Digit8": "8", "Digit9": "9", "Digit0": "0", "Minus": "-", "Equal": "=",
  "Backspace": "Bksp", "Tab": "Tab", "CapsLock": "Caps", "Enter": "Enter", "ShiftLeft": "L-Shift",
  "ShiftRight": "R-Shift", "ControlLeft": "Ctrl", "ControlRight": "Ctrl", "AltLeft": "Win / Super",
  "AltRight": "Alt", "MetaLeft": "Win", "Space": "Spacebar", "ArrowLeft": "<-", "ArrowUp": "^",
  "ArrowDown": "v", "ArrowRight": "->", "Fn": "Fn"
};

// Initialize Application
document.addEventListener("DOMContentLoaded", () => {
  buildKeyboardMatrix();
  initTouchpadCanvas();
  initTouchpadButtons();
  initKeyListeners();

  // Activar Keyboard Lock API para capturar F11, Escape, Tab, etc.
  requestKeyboardLock();

  refreshAllData();
  setInterval(refreshAllData, 2500);

  // AUTO RUN RAM BENCHMARK ON LOAD
  setTimeout(runRamTest, 1000);

  // AUTO-INICIAR cámara y micrófono al cargar (sin esperar interacción)
  setTimeout(startCamera, 800);
  setTimeout(startMicTest, 1000);

  // Desbloquear AudioContext y asegurar Keyboard Lock en el primer evento de interacción
  const unlockAudioAndLock = () => {
    requestKeyboardLock();
    if (audioContext && audioContext.state === 'suspended') {
      audioContext.resume();
    } else if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      if (audioContext.state === 'suspended') audioContext.resume();
    }
  };
  document.addEventListener('click', unlockAudioAndLock, { once: false });
  document.addEventListener('keydown', unlockAudioAndLock, { once: false, capture: true });
});

// FETCH DATA FROM PYTHON BACKEND REST API
async function refreshAllData() {
  try {
    const res = await fetch("/api/all");
    if (!res.ok) throw new Error("HTTP error " + res.status);
    const data = await res.json();

    updateSystemTab(data.system);
    updateBatteryTab(data.battery || data.batteries);
    updateThermalTab(data.thermal);
    updateStorageTab(data.storage);
    updateBluetoothTab(data.bluetooth);
    updateDisplayTab(data.display);
    updateWifiTab(data.wifi);
    updateDriveSelector(data.storage);
  } catch (err) {
    console.error("Error refreshing diagnostic data:", err);
  }
}

// ── TCG OPAL / MCAFEE PSID UNLOCK MODAL ──────────────────────────────
async function openOpalModal() {
  document.getElementById("opal-modal").style.display = "flex";
  document.getElementById("opal-result-banner").innerHTML = "";

  try {
    const res = await fetch("/api/drives");
    if (res.ok) {
      const drives = await res.json();
      updateDriveSelector(drives);
    }
  } catch (e) { }

  startQrScanner();

  // Auto-foco inmediato en el campo de texto del PSID para poder escribirlo directamente
  setTimeout(() => {
    const psidInput = document.getElementById("opal-psid-input");
    if (psidInput) {
      psidInput.focus();
    }
  }, 150);
}

function closeOpalModal() {
  stopQrScanner();
  const confirmModal = document.getElementById("opal-confirm-modal");
  if (confirmModal) confirmModal.style.display = "none";
  const modal = document.getElementById("opal-modal");
  if (modal) modal.style.display = "none";
}

function updateDriveSelector(drives) {
  const select = document.getElementById("opal-drive-select");
  if (!select || !drives) return;
  select.innerHTML = drives.map(d => `
    <option value="${d.device}">${d.device} - ${d.model} (${d.type}) ${d.is_opal_locked ? '[BLOQUEADO OPAL]' : ''}</option>
  `).join("");
}

async function startQrScanner() {
  const video = document.getElementById("qr-scanner-video");
  const overlay = document.getElementById("qr-scan-status-overlay");
  const reticle = document.getElementById("qr-target-reticle");
  if (!video) return;

  if (reticle) reticle.classList.remove("detected");

  try {
    qrStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "user" }, width: { ideal: 1280, min: 640 }, height: { ideal: 720, min: 480 } }
    });
    video.srcObject = qrStream;
    if (overlay) overlay.style.display = "none";
    await video.play().catch(e => console.warn(e));
    scanQrLoop();
  } catch (err) {
    if (overlay) {
      overlay.style.display = "flex";
      overlay.innerText = "Cámara no disponible para escáner QR. Puedes escribir el PSID manualmente.";
    }
  }
}

function scanQrLoop() {
  const video = document.getElementById("qr-scanner-video");
  const canvas = document.getElementById("qr-canvas");
  const overlay = document.getElementById("qr-scan-status-overlay");

  if (!qrStream || !video || video.readyState < video.HAVE_CURRENT_DATA) {
    qrAnimId = requestAnimationFrame(scanQrLoop);
    return;
  }

  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);

  if (window.jsQR) {
    const code = window.jsQR(imageData.data, imageData.width, imageData.height, {
      inversionAttempts: "attemptBoth",
    });

    if (code && code.data) {
      const psidText = code.data.trim().replace(/[^A-Za-z0-9]/g, "").toUpperCase();
      if (psidText.length >= 10) {
        const psidInput = document.getElementById("opal-psid-input");
        if (psidInput) psidInput.value = psidText.substring(0, 32);
        if (overlay) {
          overlay.style.display = "flex";
          overlay.innerText = `Código QR detectado: ${psidText.substring(0, 32)}`;
          overlay.style.color = "var(--success-green)";
        }
        stopQrScanner();
        return;
      }
    }
  }

  qrAnimId = requestAnimationFrame(scanQrLoop);
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
}

function submitOpalRevert() {
  const drive = document.getElementById("opal-drive-select").value;
  const psid = document.getElementById("opal-psid-input").value.trim();
  const banner = document.getElementById("opal-result-banner");

  if (!drive) {
    if (banner) {
      banner.innerHTML = `
        <div style="background: rgba(239, 68, 68, 0.2); border: 1px solid var(--danger-red); color: #fca5a5; padding: 0.75rem; border-radius: 6px; font-weight: 700;">
          Por favor selecciona una unidad de disco objetivo.
        </div>
      `;
    }
    return;
  }

  if (!psid || psid.length !== 32) {
    if (banner) {
      banner.innerHTML = `
        <div style="background: rgba(239, 68, 68, 0.2); border: 1px solid var(--danger-red); color: #fca5a5; padding: 0.75rem; border-radius: 6px; font-weight: 700;">
          Por favor ingresa o escanea el código PSID de 32 caracteres.
        </div>
      `;
    }
    return;
  }

  if (banner) banner.innerHTML = "";

  pendingOpalDevice = drive;
  pendingOpalPsid = psid;

  const confirmDeviceEl = document.getElementById("opal-confirm-device-text");
  const confirmPsidEl = document.getElementById("opal-confirm-psid-text");
  if (confirmDeviceEl) confirmDeviceEl.innerText = drive;
  if (confirmPsidEl) confirmPsidEl.innerText = psid;

  const confirmModal = document.getElementById("opal-confirm-modal");
  if (confirmModal) confirmModal.style.display = "flex";
}

function closeOpalConfirmModal() {
  const confirmModal = document.getElementById("opal-confirm-modal");
  if (confirmModal) confirmModal.style.display = "none";
}

async function executeOpalRevertConfirmed() {
  const drive = pendingOpalDevice;
  const psid = pendingOpalPsid;
  closeOpalConfirmModal();

  if (!drive || !psid) return;

  const banner = document.getElementById("opal-result-banner");
  const btn = document.getElementById("btn-exec-opal");

  if (banner) {
    banner.innerHTML = `
      <div style="background: rgba(124, 58, 237, 0.2); border: 1px solid var(--primary-violet); color: #ddd6fe; padding: 0.75rem; border-radius: 6px;">
        Ejecutando comando TCG Opal / PSID Revert en ${drive}... Por favor espera...
      </div>
    `;
  }
  if (btn) btn.disabled = true;

  try {
    const res = await fetch("/api/opal-revert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device: drive, psid: psid })
    });
    const data = await res.json();

    if (data.success) {
      if (banner) {
        banner.innerHTML = `
          <div style="background: rgba(16, 185, 129, 0.2); border: 1px solid var(--success-green); color: var(--success-green); padding: 0.75rem; border-radius: 6px; font-weight: 700;">
            ${data.message}
          </div>
        `;
      }
      if (typeof refreshAllData === "function") refreshAllData();
    } else {
      if (banner) {
        banner.innerHTML = `
          <div style="background: rgba(239, 68, 68, 0.2); border: 1px solid var(--danger-red); color: #fca5a5; padding: 0.75rem; border-radius: 6px; font-weight: 700;">
            ${data.message}
          </div>
        `;
      }
    }
  } catch (err) {
    if (banner) {
      banner.innerHTML = `
        <div style="background: rgba(239, 68, 68, 0.2); border: 1px solid var(--danger-red); color: #fca5a5; padding: 0.75rem; border-radius: 6px; font-weight: 700;">
          Error al ejecutar PSID Revert: ${err.message}
        </div>
      `;
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = "Ejecutar PSID Revert";
    }
  }
}

// RAM BENCHMARK RUNNER
async function runRamTest() {
  const statusEl = document.getElementById("ram-test-status");
  const btn = document.getElementById("btn-run-ramtest");

  if (statusEl) {
    statusEl.innerText = "Analizando memoria...";
    statusEl.style.color = "#a855f7";
  }
  if (btn) btn.disabled = true;

  try {
    const res = await fetch("/api/ram-test");
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    if (data.errors === 0) {
      if (statusEl) {
        const mb = data.tested_mb || 256;
        const speed = data.speed_gbs ? `${data.speed_gbs} GB/s` : '';
        statusEl.innerText = `${mb} MB verificados (${speed})`;
        statusEl.style.color = "var(--success-green)";
      }
      markCheckpassed("chk-ram", "RAM");
    } else {
      if (statusEl) {
        statusEl.innerText = `Atención: ${data.errors} error(es) detectado(s)`;
        statusEl.style.color = "var(--danger-red)";
      }
      unmarkCheckpassed("chk-ram", "RAM");
    }
  } catch (err) {
    if (statusEl) {
      statusEl.innerText = "Error en prueba: " + err.message;
      statusEl.style.color = "var(--danger-red)";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// UPDATE SYSTEM SUMMARY
function updateSystemTab(sys) {
  if (!sys) return;

  const serialStr = sys.serial && sys.serial !== 'N/A' ? sys.serial : 'N/A';
  document.getElementById("header-serial").innerText = `S/N: ${serialStr}`;
  document.getElementById("sys-model").innerText = sys.model || "Detectando Modelo...";
  document.getElementById("quick-model").innerText = formatModelShortName(sys.model);
  document.getElementById("sys-vendor").innerText = sys.vendor || "--";

  function formatModelShortName(modelStr) {
    if (!modelStr || ["--", "N/A", "To be filled by O.E.M.", "Default string", "System Product Name"].includes(modelStr.trim())) return "--";
    let s = modelStr.trim();
    s = s.replace(/^(LENOVO|HP|Hewlett-Packard|Dell\s+Inc\.?|Dell|ASUSTeK\s+COMPUTER\s+INC\.?|ASUS|Acer|Apple\s+Inc\.?|Apple|Microsoft\s+Corporation|Micro-Star\s+International\s+Co\.,\s+Ltd\.?|MSI)\s*[:\-]?\s*/i, "");
    s = s.replace(/^[0-9A-Z]{4,10}\s+(ThinkPad|EliteBook|ProBook|Latitude|Precision|XPS|ZBook)/i, "$1");
    const tpX1 = s.match(/ThinkPad\s+(X1\s+(?:Carbon|Yoga|Nano|Extreme|Titanium)(?:\s+(?:Gen\s+\d+|\d+th\s+Gen))?)/i);
    if (tpX1) return tpX1[1].replace(/(\d+)th\s+Gen/i, "Gen $1");
    const tpMatch = s.match(/ThinkPad\s+([A-Z]\d+[a-z]?(?:\s+(?:Gen\s+\d+|\d+th\s+Gen))?)/i);
    if (tpMatch) return tpMatch[1].replace(/(\d+)th\s+Gen/i, "Gen $1");
    const hpMatch = s.match(/(EliteBook|ProBook|ZBook|Dragonfly|Pavilion|Envy|Omen|Victus)\s+([^,]+)/i);
    if (hpMatch) {
      let rest = hpMatch[2].replace(/\d+(?:\.\d+)?\s*(?:inch|\"|\-inch)/gi, "");
      rest = rest.replace(/\b(Notebook\s+PC|Mobile\s+Workstation|Laptop\s+PC|Laptop|PC)\b/gi, "").replace(/\s+/g, " ").trim();
      return `${hpMatch[1]} ${rest}`.trim();
    }
    const dellMatch = s.match(/(Latitude|Precision|XPS|Inspiron|Vostro|Alienware|OptiPlex)\s+(\d+[\w]*(?:\s+\d+[\w]*)?)/i);
    if (dellMatch) return `${dellMatch[1]} ${dellMatch[2]}`.trim();
    s = s.replace(/\b(Notebook\s+PC|Mobile\s+Workstation|Laptop\s+PC|Laptop|PC|System\s+Product\s+Name)\b/gi, "").replace(/\s+/g, " ").trim();
    return s.length > 24 ? s.slice(0, 24).trim() : (s || "--");
  }

  function formatCpuShortName(raw) {
    if (!raw || raw === "--" || raw === "N/A") return "--";
    const clean = raw.replace(/\(R\)|\(TM\)|@.*$/gi, "").replace(/\s+/g, " ").trim();
    const upper = clean.toUpperCase();
    const ultraMatch = clean.match(/Ultra\s+([3579])/i);
    if (ultraMatch) return `Intel Ultra ${ultraMatch[1]}`;
    const coreIMatch = clean.match(/\b(i[3579])[- ]/i);
    if (coreIMatch) return `Intel ${coreIMatch[1].toLowerCase()}`;
    const coreNumMatch = clean.match(/\bCore\s+([3579])\b/i);
    if (coreNumMatch) return `Intel Core ${coreNumMatch[1]}`;
    if (upper.includes("XEON")) return "Intel Xeon";
    if (upper.includes("CELERON")) return "Intel Celeron";
    if (upper.includes("PENTIUM")) return "Intel Pentium";
    if (upper.includes("ATOM")) return "Intel Atom";
    const intelNMatch = clean.match(/\bProcessor\s+(N\d+)\b/i) || clean.match(/\b(N\d{3,4})\b/i);
    if (upper.includes("INTEL") && intelNMatch) return `Intel ${intelNMatch[1]}`;
    const ryzenAiMatch = clean.match(/Ryzen\s+AI\s+([3579])/i);
    if (ryzenAiMatch) return `AMD Ryzen AI ${ryzenAiMatch[1]}`;
    const ryzenMatch = clean.match(/Ryzen\s+([3579])/i);
    if (ryzenMatch) return `AMD Ryzen ${ryzenMatch[1]}`;
    if (upper.includes("THREADRIPPER")) return "AMD Threadripper";
    if (upper.includes("EPYC")) return "AMD EPYC";
    if (upper.includes("ATHLON")) return "AMD Athlon";
    const amdAMatch = clean.match(/\b(A\d{1,2})-\d+/i);
    if (amdAMatch) return `AMD ${amdAMatch[1].toUpperCase()}`;
    if (upper.includes("SNAPDRAGON")) return upper.includes("X ELITE") ? "Snapdragon X Elite" : (upper.includes("X PLUS") ? "Snapdragon X Plus" : "Snapdragon");
    const appleMatch = clean.match(/\b(M[1234](?:\s+(?:Pro|Max|Ultra))?)\b/i);
    if (appleMatch) return `Apple ${appleMatch[1]}`;
    if (upper.includes("INTEL")) return "Intel";
    if (upper.includes("AMD")) return "AMD";
    return clean.split(" ")[0];
  }
  document.getElementById("quick-cpu").innerText = formatCpuShortName(sys.cpu);

  if (sys.ram) {
    document.getElementById("sys-ram").innerText = `${sys.ram.total_gb} GB Instalados`;
    document.getElementById("ram-used-detail").innerText = `Usado actualmente: ${sys.ram.used_gb} GB (${sys.ram.percent_used}%)`;
    document.getElementById("quick-ram").innerText = `${sys.ram.total_gb} GB`;
    document.getElementById("ram-progress").style.width = `${sys.ram.percent_used}%`;
  }
}

// UPDATE BATTERY & CHARGING ANOMALIES
function updateBatteryTab(batteries) {
  if (!batteries || batteries.length === 0) return;
  const bat = batteries[0];

  document.getElementById("quick-bat").innerText = `${bat.capacity_percent}%`;
  document.getElementById("quick-charge-status").innerText = bat.status_es;
  document.getElementById("bat-capacity").innerText = `${bat.capacity_percent}%`;
  document.getElementById("bat-status-text").innerText = bat.status_es;

  document.getElementById("bat-health-val").innerText = `${bat.health_percent}%`;
  document.getElementById("bat-design-wh").innerText = `${bat.design_wh} Wh`;
  document.getElementById("bat-full-wh").innerText = `${bat.full_wh} Wh`;
  document.getElementById("bat-cycles").innerText = bat.cycle_count;
  document.getElementById("bat-voltage").innerText = `${bat.voltage_v} V`;

  const alertBanner = document.getElementById("charge-alert-banner");
  if (bat.has_charge_error && bat.error_msg) {
    alertBanner.innerHTML = `
      <div style="background-color: rgba(239, 68, 68, 0.2); border: 1px solid var(--danger-red); color: #fca5a5; padding: 0.5rem; border-radius: 6px; font-size: 0.8rem; margin-top: 0.4rem;">
        ${bat.error_msg}
      </div>
    `;
  } else {
    alertBanner.innerHTML = '';
  }
}

// UPDATE THERMAL & FANS
function updateThermalTab(thermal) {
  if (!thermal) return;

  const fansContainer = document.getElementById("fans-list");
  if (thermal.fans && thermal.fans.length > 0) {
    fansContainer.innerHTML = thermal.fans.map(f => `
      <div class="sensor-item">
        <span>${f.label}</span>
        <strong>${f.rpm} RPM (${f.status})</strong>
      </div>
    `).join("");
  } else {
    fansContainer.innerHTML = `<div class="sensor-item">Fan Principal: Girando OK</div>`;
  }

  const tempsContainer = document.getElementById("temps-list");
  if (thermal.temperatures && thermal.temperatures.length > 0) {
    tempsContainer.innerHTML = thermal.temperatures.map(t => `
      <div class="sensor-item">
        <span>${t.label}</span>
        <strong style="color: ${t.temp_c > 80 ? 'var(--danger-red)' : 'var(--success-green)'}">${t.temp_c} °C</strong>
      </div>
    `).join("");
  }
}

// UPDATE STORAGE (SSD)
function updateStorageTab(storage) {
  if (!storage) return;

  let internalList = [];
  if (Array.isArray(storage)) {
    internalList = storage.filter(s => !s.is_usb);
  } else if (typeof storage === "object") {
    internalList = storage.internal || [];
  }

  const container = document.getElementById("storage-list");
  if (!container) return;

  if (internalList.length === 0) {
    container.innerHTML = `
      <div class="card-spec-item">
        <span class="spec-label">Disco interno</span>
        <div class="spec-value spec-value-detail" style="color: var(--text-muted);">Sin discos internos detectados</div>
      </div>
    `;
    return;
  }

  container.innerHTML = internalList.map(s => {
    const smartText = (s.smart_status || '').includes('100%') ? 'Salud 100% (Sin errores)' : (s.smart_status || 'Correcto');
    const devReadPassed = s.device_read_test !== 'FAILED';
    const nvmeReadPassed = s.nvme_read_test !== 'FAILED';
    const isOpal = s.is_opal_locked || (!devReadPassed && !nvmeReadPassed);

    let readSectionHtml = '';
    if (s.device_read_test && s.nvme_read_test) {
      readSectionHtml = `
        <div class="card-spec-item">
          <span class="spec-label">Pruebas de lectura</span>
          <div class="spec-value spec-value-detail" style="font-family: var(--font-mono); font-size: 0.82rem;">
            Device Read: <span style="color: ${devReadPassed ? 'var(--success-green)' : '#f87171'}; font-weight: 700;">${s.device_read_test}</span> | 
            NVMe Read: <span style="color: ${nvmeReadPassed ? 'var(--success-green)' : '#f87171'}; font-weight: 700;">${s.nvme_read_test}</span>
          </div>
        </div>
      `;
    }

    let opalAlertHtml = '';
    if (isOpal) {
      opalAlertHtml = `
        <div class="card-spec-item" style="background: rgba(239, 68, 68, 0.08); border-left: 3px solid #ef4444; border-radius: 4px; padding: 0.45rem 0.6rem; margin-top: 0.35rem; display: flex; flex-direction: column; gap: 0.35rem;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <span class="spec-label" style="color: #fca5a5; font-size: 0.78rem; margin: 0;">Diagnostico</span>
            <span style="font-size: 0.72rem; color: #cbd5e1; font-family: var(--font-mono);">${s.crypto_status_label || 'Compatible (NVMe Sanitize)'}</span>
          </div>
          <div class="spec-value spec-value-detail" style="color: #f87171; font-weight: 700; font-size: 0.82rem;">
            Disco posiblemente encriptado con OPAL
          </div>
          <button type="button" class="btn btn-secondary btn-sm" onclick="openOpalModalWithDrive('${s.device}')" style="padding: 0.3rem 0.5rem; font-size: 0.75rem; border-color: rgba(239, 68, 68, 0.4); color: #fecaca; width: 100%; margin-top: 0.15rem;">
            Desbloquear disco (Crypto Erase / PSID)
          </button>
        </div>
      `;
    }

    let cryptoCompatHtml = '';
    if (!isOpal && s.crypto_supported) {
      cryptoCompatHtml = `
        <div class="card-spec-item">
          <span class="spec-label">Borrado seguro</span>
          <div class="spec-value spec-value-detail" style="font-size: 0.78rem; color: #a5b4fc; font-family: var(--font-mono);">
            ${s.crypto_status_label || 'Compatible (NVMe Sanitize / SES-2)'}
          </div>
        </div>
      `;
    }

    return `
      <div class="card-spec-item">
        <span class="spec-label">Disco interno SSD</span>
        <div class="spec-value spec-value-accent" style="font-size: 0.95rem;">${s.model} (${s.size_gb} GB)</div>
      </div>
      <div class="card-spec-item">
        <span class="spec-label">Dispositivo</span>
        <div class="spec-value spec-value-detail"><code>${s.device}</code> (${s.type})</div>
      </div>
      <div class="card-spec-item">
        <span class="spec-label">Salud del disco (SMART)</span>
        <div class="spec-value spec-value-detail" style="color: ${isOpal ? '#f59e0b' : 'var(--success-green)'}; font-weight: 700;">
          ${isOpal ? 'SMART PASSED (Controlador activo)' : smartText}
        </div>
      </div>
      ${readSectionHtml}
      ${cryptoCompatHtml}
      ${opalAlertHtml}
    `;
  }).join("<hr class='divider' style='margin: 0.6rem 0;'>");

  markCheckpassed("chk-ssd", "SSD");
}

// UPDATE BLUETOOTH WITH ACTIVE CONTROLLER
function updateBluetoothTab(bt) {
  if (!bt) return;
  const textEl = document.getElementById("bt-status-text");
  const detailEl = document.getElementById("bt-name-detail");

  if (bt.present) {
    textEl.innerText = "Operativo y alimentado";
    textEl.style.color = "var(--success-green)";
    detailEl.innerText = bt.name || "HCI0";
    markCheckpassed("chk-bt", "BLUETOOTH");
  } else {
    textEl.innerText = "No detectado";
    textEl.style.color = "var(--danger-red)";
    detailEl.innerText = "Sin adaptador activo";
    unmarkCheckpassed("chk-bt", "Bluetooth");
  }
}

// UPDATE DISPLAY & HDMI (STRICT EXTERNAL MONITORS ONLY)
let hdmiEverConnected = false;

function resetHdmiTest() {
  hdmiEverConnected = false;
  unmarkCheckpassed("chk-hdmi", "HDMI");
}

function updateDisplayTab(display) {
  if (!display) return;
  document.getElementById("mobo-name").innerText = display.motherboard || "--";
  document.getElementById("mobo-bios").innerText = display.bios_version || "--";

  const hdmiEl = document.getElementById("hdmi-status-text");
  if (display.hdmi_connected) {
    hdmiEverConnected = true;
    hdmiEl.innerText = `Monitor externo conectado (${display.hdmi_port})`;
    hdmiEl.style.color = "var(--success-green)";
    hdmiEl.style.fontWeight = "700";
    markCheckpassed("chk-hdmi", "HDMI");
  } else {
    if (hdmiEverConnected) {
      hdmiEl.innerText = "Desconectado (Validado con éxito)";
      hdmiEl.style.color = "var(--success-green)";
      hdmiEl.style.fontWeight = "600";
      markCheckpassed("chk-hdmi", "HDMI");
    } else {
      hdmiEl.innerText = "Sin monitor conectado";
      hdmiEl.style.color = "#cbd5e1";
      hdmiEl.style.fontWeight = "500";
      unmarkCheckpassed("chk-hdmi", "HDMI");
    }
  }
}

// UPDATE WIFI & ETHERNET AUTO-APPROVE
function updateWifiTab(wifi) {
  if (!wifi) return;

  const listContainer = document.getElementById("wifi-networks-list");
  if (listContainer) {
    if (wifi.nearby_networks && wifi.nearby_networks.length > 0) {
      const autoStatus = document.getElementById("wifi-auto-status");
      if (autoStatus) {
        autoStatus.innerText = `Detectadas ${wifi.nearby_networks.length} redes Wi-Fi (Aprobado)`;
        autoStatus.style.color = "var(--success-green)";
      }
      markCheckpassed("chk-wifi", "WI-FI");

      listContainer.innerHTML = wifi.nearby_networks.map(net => `
        <tr>
          <td><strong>${net.ssid}</strong></td>
          <td>${net.signal}%</td>
        </tr>
      `).join("");
    } else if (wifi.wifi_hardware_present) {
      const autoStatus = document.getElementById("wifi-auto-status");
      if (autoStatus) {
        autoStatus.innerText = "Adaptador Wi-Fi operativo (escaneando redes...)";
        autoStatus.style.color = "var(--success-green)";
      }
      markCheckpassed("chk-wifi", "WI-FI");
      listContainer.innerHTML = `<tr><td colspan="2" style="text-align: center; color: var(--success-green);">Adaptador Wi-Fi detectado y operativo.</td></tr>`;
    } else {
      const autoStatus = document.getElementById("wifi-auto-status");
      if (autoStatus) {
        autoStatus.innerText = "No se detectó adaptador Wi-Fi.";
        autoStatus.style.color = "var(--text-muted)";
      }
      listContainer.innerHTML = `<tr><td colspan="2" style="text-align: center;">No se detectó adaptador Wi-Fi.</td></tr>`;
      unmarkCheckpassed("chk-wifi", "Wi-Fi");
    }
  }

  // Ethernet RJ-45 handling
  const eth = wifi.ethernet;
  if (eth) {
    const ethStatus = document.getElementById("eth-status-text");
    const ethIface = document.getElementById("eth-iface-text");
    const ethCarrier = document.getElementById("eth-carrier-text");

    if (eth.present && eth.connected) {
      markCheckpassed("chk-eth", "ETHERNET");
      if (ethStatus) {
        ethStatus.innerText = "Cable conectado OK";
        ethStatus.style.color = "var(--success-green)";
      }
      if (ethIface && eth.primary) {
        const speedStr = eth.primary.speed_mbps ? ` (${eth.primary.speed_mbps} Mbps)` : "";
        ethIface.innerHTML = `<code>${eth.primary.interface}</code>${speedStr}`;
      }
      if (ethCarrier) {
        ethCarrier.innerText = "Enlace activo y transmitiendo";
        ethCarrier.style.color = "var(--success-green)";
      }
    } else if (eth.present && !eth.connected) {
      unmarkCheckpassed("chk-eth", "Ethernet");
      if (ethStatus) {
        ethStatus.innerText = "Puerto disponible (Esperando conexión...)";
        ethStatus.style.color = "var(--text-main)";
      }
      if (ethIface && eth.primary) {
        ethIface.innerHTML = `<code>${eth.primary.interface}</code>`;
      }
      if (ethCarrier) {
        ethCarrier.innerText = "Cable desconectado (Inserta cable RJ-45 para probar)";
        ethCarrier.style.color = "var(--text-muted)";
      }
    } else {
      markCheckfailed("chk-eth", "ETHERNET");
      if (ethStatus) {
        ethStatus.innerText = "No disponible / Sin puerto integrado";
        ethStatus.style.color = "var(--danger-red)";
      }
      if (ethIface) {
        ethIface.innerHTML = `<code>No integrado</code>`;
      }
      if (ethCarrier) {
        ethCarrier.innerText = "Sin puerto RJ-45 en este equipo";
        ethCarrier.style.color = "var(--text-muted)";
      }
    }
  }
}

// KEYBOARD TESTER & MULTIMEDIA / HOTKEY NORMALIZER
const mediaKeyMap = {
  "AudioVolumeMute": "F1", "VolumeMute": "F1",
  "AudioVolumeDown": "F2", "VolumeDown": "F2",
  "AudioVolumeUp": "F3", "VolumeUp": "F3",
  "MicrophoneMute": "F4", "AudioMicMute": "F4",
  "BrightnessDown": "F5", "MonBrightnessDown": "F5",
  "BrightnessUp": "F6", "MonBrightnessUp": "F6",
  "DisplayToggle": "F7", "LaunchScreenSaver": "F7", "VideoModeCycle": "F7",
  "MediaPlayPause": "F8", "MediaTrackPrevious": "F8", "AirplaneMode": "F8",
  "MediaTrackNext": "F9", "LaunchSettings": "F9", "LaunchApplication1": "F9",
  "Search": "F10", "BrowserSearch": "F10", "LaunchMail": "F10",
  "ZoomIn": "F11", "KbdBrightnessUp": "F11", "KbdToggle": "F11",
  "Calculator": "F12", "ZoomOut": "F12"
};

async function requestKeyboardLock() {
  if (navigator.keyboard && typeof navigator.keyboard.lock === "function") {
    try {
      await navigator.keyboard.lock([
        "Escape", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
        "Tab", "AltLeft", "AltRight", "MetaLeft", "MetaRight", "ContextMenu"
      ]);
      console.log("Keyboard Lock API activada para F11, Escape y modificadores.");
    } catch (err) {
      // Fallback a lock general
      navigator.keyboard.lock().catch(() => { });
    }
  }
}

function markKeyPassed(code) {
  if (!code) return;
  pressedKeysSet.add(code);

  // Incrementar contador de toques de esta tecla específica
  keyPressCounts[code] = (keyPressCounts[code] || 0) + 1;
  const colorIndex = (keyPressCounts[code] - 1) % KEY_COLOR_CLASSES.length;
  const activeColorClass = KEY_COLOR_CLASSES[colorIndex];

  const totalKeys = keyboardLayout.flat().length;
  const count = pressedKeysSet.size;
  document.getElementById("key-count").innerText = count;

  if (count >= totalKeys) {
    markCheckpassed("chk-keyboard", "TECLADO");
  } else {
    unmarkCheckpassed("chk-keyboard", `Teclado (${count}/${totalKeys})`);
  }

  const tile = document.querySelector(`.key-tile[data-code="${code}"]`);
  if (tile) {
    tile.classList.add("pressed");
    // Remover colores anteriores y aplicar el color del ciclo actual
    KEY_COLOR_CLASSES.forEach(cls => tile.classList.remove(cls));
    tile.classList.add(activeColorClass);
  }
}

function buildKeyboardMatrix() {
  const container = document.getElementById("keyboard-matrix");
  container.innerHTML = "";

  keyboardLayout.forEach(row => {
    const rowDiv = document.createElement("div");
    rowDiv.className = "kb-row";

    row.forEach(code => {
      const tile = document.createElement("div");
      tile.className = "key-tile";
      tile.setAttribute("data-code", code);

      let label = keyDisplayNames[code] || code.replace("Key", "").replace("Digit", "");
      tile.innerText = label;

      // La tecla Fn es gestionada por hardware (EC). Permitir clic manual y mostrar ayuda
      if (code === "Fn") {
        tile.title = "Tecla gestionada por hardware (EC). Se auto-detecta al pulsar cualquier combo Fn/multimedia o haciendo clic.";
        tile.style.cursor = "pointer";
        tile.addEventListener("click", () => {
          markKeyPassed("Fn");
          document.getElementById("last-key-code").innerText = "Fn (Clic Manual / EC)";
        });
      }

      rowDiv.appendChild(tile);
    });

    container.appendChild(rowDiv);
  });
}

function initKeyListeners() {
  const handleKeyDown = (e) => {
    // Si el usuario está interactuando con un campo de formulario (input, textarea, select),
    // permitir escribir libremente sin bloquear eventos.
    const targetTag = e.target ? e.target.tagName : "";
    const isInput = targetTag === "INPUT" || targetTag === "TEXTAREA" || targetTag === "SELECT" || (e.target && e.target.isContentEditable);

    if (isInput) {
      if (e.key === "Escape") {
        closeOpalModal();
        if (typeof closePowerModal === "function") closePowerModal();
      } else if (e.key === "Enter" && e.target.id === "opal-psid-input") {
        e.preventDefault();
        submitOpalRevert();
      }
      return;
    }

    // Bloquear atajos nativos del navegador (F11 fullscreen, F5 recarga, etc.) durante el test de teclado
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();

    requestKeyboardLock();

    let rawCode = e.code || "";
    let rawKey = e.key || "";
    let code = rawCode || rawKey;

    // 1. Normalizar F11 y teclas de función estándar
    if (rawKey === "F11" || rawCode === "F11" || e.keyCode === 122 || e.which === 122) {
      code = "F11";
    } else if (rawKey === "Escape" || rawCode === "Escape" || e.keyCode === 27) {
      code = "Escape";
    } else if (rawKey === "Meta" || rawCode === "MetaLeft" || rawCode === "MetaRight") {
      code = "MetaLeft";
    } else if (rawKey === "Fn" || rawCode === "Fn" || rawKey === "FnLock" || rawCode === "FnLock" || e.keyCode === 255 || e.keyCode === 143) {
      code = "Fn";
    } else if (mediaKeyMap[rawKey] || mediaKeyMap[rawCode]) {
      // Tecla multimedia enviada por BIOS/EC -> Mapear a F-key y auto-aprobar Fn
      const fKey = mediaKeyMap[rawKey] || mediaKeyMap[rawCode];
      markKeyPassed(fKey);
      markKeyPassed("Fn");
      code = fKey;
    }

    totalKeyPresses++;
    document.getElementById("key-count").innerText = totalKeyPresses;
    document.getElementById("last-key-code").innerText = `${rawKey || rawCode} -> ${code}`;

    markKeyPassed(code);

    const tile = document.querySelector(`.key-tile[data-code="${code}"]`);
    if (tile) {
      tile.classList.add("active-down");
    }
  };

  const handleKeyUp = (e) => {
    const targetTag = e.target ? e.target.tagName : "";
    const isInput = targetTag === "INPUT" || targetTag === "TEXTAREA" || targetTag === "SELECT" || (e.target && e.target.isContentEditable);
    if (isInput) {
      return;
    }

    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();

    let rawCode = e.code || "";
    let rawKey = e.key || "";
    let code = rawCode || rawKey;

    if (rawKey === "F11" || rawCode === "F11" || e.keyCode === 122) code = "F11";
    if (rawKey === "Meta" || rawCode === "MetaLeft" || rawCode === "MetaRight") code = "MetaLeft";
    if (rawKey === "Fn" || rawKey === "FnLock") code = "Fn";
    if (mediaKeyMap[rawKey] || mediaKeyMap[rawCode]) {
      code = mediaKeyMap[rawKey] || mediaKeyMap[rawCode];
    }

    const tile = document.querySelector(`.key-tile[data-code="${code}"]`);
    if (tile) {
      tile.classList.remove("active-down");
    }
    const fnTile = document.querySelector(`.key-tile[data-code="Fn"]`);
    if (fnTile) {
      fnTile.classList.remove("active-down");
    }
  };

  // Interceptar con capture: true en window, document y body
  window.addEventListener("keydown", handleKeyDown, { capture: true, passive: false });
  window.addEventListener("keyup", handleKeyUp, { capture: true, passive: false });
  document.addEventListener("keydown", handleKeyDown, { capture: true, passive: false });
  document.addEventListener("keyup", handleKeyUp, { capture: true, passive: false });
}

function resetKeyboardTest() {
  totalKeyPresses = 0;
  pressedKeysSet.clear();
  keyPressCounts = {};
  document.getElementById("key-count").innerText = "0";
  document.getElementById("last-key-code").innerText = "Ninguna";
  document.querySelectorAll(".key-tile").forEach(t => {
    t.classList.remove("pressed");
    t.classList.remove("active-down");
    KEY_COLOR_CLASSES.forEach(cls => t.classList.remove(cls));
  });
  unmarkCheckpassed("chk-keyboard", `Teclado (0/${keyboardLayout.flat().length})`);
}

// TOUCHPAD TESTER (LEFT & RIGHT CLICK TILES + CANVAS)
function initTouchpadButtons() {
  const tileLeft = document.getElementById("tile-left-click");
  const tileRight = document.getElementById("tile-right-click");

  tileLeft.addEventListener("mousedown", (e) => {
    if (e.button === 0) {
      touchpadLeftClicked = true;
      tileLeft.classList.add("passed");
      document.getElementById("status-left-click").innerText = "Aprobado";
      checkTouchpadComplete();
    }
  });

  tileRight.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    touchpadRightClicked = true;
    tileRight.classList.add("passed");
    document.getElementById("status-right-click").innerText = "Aprobado";
    checkTouchpadComplete();
  });

  tileRight.addEventListener("mousedown", (e) => {
    if (e.button === 2) {
      e.preventDefault();
      touchpadRightClicked = true;
      tileRight.classList.add("passed");
      document.getElementById("status-right-click").innerText = "Aprobado";
      checkTouchpadComplete();
    }
  });
}

function initTouchpadCanvas() {
  const canvas = document.getElementById("touchpad-canvas");
  const ctx = canvas.getContext("2d");
  const log = document.getElementById("touch-log");
  let isDrawing = false;

  function resizeCanvas() {
    const rect = canvas.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      if (canvas.width !== Math.round(rect.width) || canvas.height !== Math.round(rect.height)) {
        canvas.width = Math.round(rect.width);
        canvas.height = Math.round(rect.height);
      }
    }
  }

  window.addEventListener("resize", resizeCanvas);
  setTimeout(resizeCanvas, 50);

  function getPos(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = rect.width ? canvas.width / rect.width : 1;
    const scaleY = rect.height ? canvas.height / rect.height : 1;

    const clientX = (e.touches && e.touches.length > 0) ? e.touches[0].clientX : e.clientX;
    const clientY = (e.touches && e.touches.length > 0) ? e.touches[0].clientY : e.clientY;

    return {
      x: (clientX - rect.left) * scaleX,
      y: (clientY - rect.top) * scaleY
    };
  }

  function startDraw(e) {
    isDrawing = true;
    touchpadDrawn = true;
    const pos = getPos(e);
    ctx.beginPath();
    ctx.moveTo(pos.x, pos.y);
    log.innerText = `Touchpad: Trazo en (${Math.round(pos.x)}, ${Math.round(pos.y)})`;
    checkTouchpadComplete();
  }

  function draw(e) {
    if (!isDrawing) return;
    const pos = getPos(e);
    ctx.lineTo(pos.x, pos.y);
    ctx.strokeStyle = "#a855f7";
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    ctx.stroke();

    if (e.touches) {
      log.innerText = `Multitouch: ${e.touches.length} dedo(s) detectado(s)`;
      if (e.touches.length >= 2) {
        touchpadRightClicked = true;
        document.getElementById("tile-right-click").classList.add("passed");
        document.getElementById("status-right-click").innerText = "Aprobado (2 dedos)";
        checkTouchpadComplete();
      }
    }
  }

  function stopDraw() {
    isDrawing = false;
  }

  canvas.addEventListener("mousedown", startDraw);
  canvas.addEventListener("mousemove", draw);
  canvas.addEventListener("mouseup", stopDraw);

  canvas.addEventListener("touchstart", startDraw);
  canvas.addEventListener("touchmove", draw);
  canvas.addEventListener("touchend", stopDraw);

  canvas.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    touchpadRightClicked = true;
    document.getElementById("tile-right-click").classList.add("passed");
    document.getElementById("status-right-click").innerText = "Aprobado";
    checkTouchpadComplete();
  });
}

function clearTouchCanvas() {
  const canvas = document.getElementById("touchpad-canvas");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function checkTouchpadComplete() {
  if (touchpadLeftClicked && touchpadRightClicked && touchpadDrawn) {
    markCheckpassed("chk-touchpad", "TOUCHPAD");
  } else {
    unmarkCheckpassed("chk-touchpad", "Touchpad");
  }
}

// SPEAKER VOLUME CONTROL
let currentVolumePercent = 80;

async function updateSpeakerVolume(val) {
  currentVolumePercent = parseInt(val) || 80;
  const valEl = document.getElementById("speaker-vol-val");
  if (valEl) valEl.innerText = `${currentVolumePercent}%`;

  try {
    await fetch('/api/volume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ volume: currentVolumePercent })
    });
  } catch (err) {
    console.warn("No se pudo actualizar el volumen del sistema:", err);
  }
}

// CAMERA TEST (ROBUST MULTI-DEVICE & FALLBACK CAMERA PIPELINE)
async function startCamera() {
  const video = document.getElementById("camera-video");
  const overlay = document.getElementById("cam-overlay");
  const resInfo = document.getElementById("cam-res-info");

  if (cameraStream) {
    stopCamera();
  }

  try {
    overlay.innerText = "Inicializando cámara web...";
    overlay.style.display = "block";

    let preferredDeviceId = null;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const videoDevices = devices.filter(d => d.kind === 'videoinput');

      if (videoDevices.length > 0) {
        // En laptops con doble cámara IR + RGB (ej. ThinkPad X1/T14), preferir la cámara principal RGB
        const rgbDev = videoDevices.find(d => !d.label.toLowerCase().includes('ir') && !d.label.toLowerCase().includes('infrared'));
        if (rgbDev) {
          preferredDeviceId = rgbDev.deviceId;
        } else {
          preferredDeviceId = videoDevices[0].deviceId;
        }
      }
    } catch (e) {
      console.warn("Enumeración de cámaras no disponible:", e);
    }

    // Estrategia 1: Intentar resolución HD con el dispositivo preferido
    const constraints1 = {
      video: preferredDeviceId
        ? { deviceId: { exact: preferredDeviceId }, width: { ideal: 1280 }, height: { ideal: 720 } }
        : { width: { ideal: 1280 }, height: { ideal: 720 } }
    };

    try {
      cameraStream = await navigator.mediaDevices.getUserMedia(constraints1);
    } catch (hdErr) {
      console.warn("Falló captura HD, intentando fallback básico:", hdErr);
      // Estrategia 2: Fallback sin restricciones de resolución
      const constraints2 = preferredDeviceId
        ? { video: { deviceId: { exact: preferredDeviceId } } }
        : { video: true };
      cameraStream = await navigator.mediaDevices.getUserMedia(constraints2);
    }

    const setCamPassed = () => {
      if (video.videoWidth && video.videoHeight) {
        resInfo.innerText = `Res: ${video.videoWidth}x${video.videoHeight}`;
      }
      markCheckpassed("chk-camera", "CÁMARA");
    };

    video.onloadedmetadata = setCamPassed;
    video.onplaying = setCamPassed;
    video.oncanplay = setCamPassed;

    video.srcObject = cameraStream;
    await video.play().catch(e => console.warn("play() diferido:", e));

    overlay.style.display = "none";
    setCamPassed();
  } catch (err) {
    overlay.style.display = "block";
    if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
      overlay.innerText = "No se detectó ninguna cámara web física en este equipo.";
    } else if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
      overlay.innerText = "Permiso de cámara denegado por el sistema o el navegador.";
    } else {
      overlay.innerText = `Error abriendo cámara (${err.name}): ${err.message}`;
    }
    console.error("Error en cámara web:", err);
  }
}

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach(t => t.stop());
    cameraStream = null;
  }
  const video = document.getElementById("camera-video");
  if (video) video.srcObject = null;
  const overlay = document.getElementById("cam-overlay");
  if (overlay) {
    overlay.style.display = "block";
    overlay.innerText = "Cámara Detenida";
  }
}

// BASS & SPEAKER FREQUENCY SWEEP TEST (100Hz - 3500Hz)
function playFrequencySweep(channel) {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }

  if (channel === 'left') {
    audioLeftTested = true;
    document.getElementById("btn-audio-left").style.borderColor = "var(--success-green)";
  } else if (channel === 'right') {
    audioRightTested = true;
    document.getElementById("btn-audio-right").style.borderColor = "var(--success-green)";
  } else if (channel === 'both') {
    audioBothTested = true;
    document.getElementById("btn-audio-both").style.borderColor = "var(--success-green)";
  }

  const statusEl = document.getElementById("audio-status-text");
  statusEl.innerText = `Barrido de graves a agudos (100Hz - 3500Hz) en canal: ${channel.toUpperCase()}`;

  const osc = audioContext.createOscillator();
  const gain = audioContext.createGain();
  const panner = audioContext.createStereoPanner();

  const now = audioContext.currentTime;
  const duration = 3.0;

  osc.type = 'sine';
  osc.frequency.setValueAtTime(100, now);
  osc.frequency.exponentialRampToValueAtTime(3500, now + duration);

  if (channel === 'left') panner.pan.setValueAtTime(-1, now);
  else if (channel === 'right') panner.pan.setValueAtTime(1, now);
  else panner.pan.setValueAtTime(0, now);

  gain.gain.setValueAtTime(0.35, now);
  gain.gain.exponentialRampToValueAtTime(0.01, now + duration);

  osc.connect(panner);
  panner.connect(gain);
  gain.connect(audioContext.destination);

  osc.start(now);
  osc.stop(now + duration);

  setTimeout(() => {
    let testedCount = (audioLeftTested ? 1 : 0) + (audioRightTested ? 1 : 0) + (audioBothTested ? 1 : 0);
    statusEl.innerText = `Pruebas de altavoz: ${testedCount}/3 completados.`;

    if (audioLeftTested && audioRightTested && audioBothTested) {
      markCheckpassed("chk-audio", "PARLANTES");
      statusEl.innerText = "Barrido completo en todos los canales (3/3).";
    } else {
      unmarkCheckpassed("chk-audio", "Parlantes");
    }
  }, duration * 1000);
}

// MICROPHONE VU METER & RECORD LOOP
async function startMicTest() {
  const statusText = document.getElementById("mic-status-text");
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioContext.createMediaStreamSource(micStream);
    micAnalyser = audioContext.createAnalyser();
    micAnalyser.fftSize = 256;
    source.connect(micAnalyser);

    statusText.innerText = "Micrófono: Escuchando";
    markCheckpassed("chk-mic", "MICRÓFONO");
    updateMicVUMeter();
  } catch (err) {
    statusText.innerText = "Error accediendo al Micrófono: " + err.message;
  }
}

function updateMicVUMeter() {
  if (!micAnalyser) return;
  const dataArray = new Uint8Array(micAnalyser.frequencyBinCount);
  micAnalyser.getByteFrequencyData(dataArray);

  let sum = 0;
  for (let i = 0; i < dataArray.length; i++) {
    sum += dataArray[i];
  }
  const average = sum / dataArray.length;
  const percentage = Math.min(100, Math.round((average / 128) * 100));

  document.getElementById("mic-vu-bar").style.width = `${percentage}%`;
  micAnimId = requestAnimationFrame(updateMicVUMeter);
}

function stopMicTest() {
  if (micAnimId) cancelAnimationFrame(micAnimId);
  if (micStream) {
    micStream.getTracks().forEach(t => t.stop());
    micStream = null;
  }
  document.getElementById("mic-vu-bar").style.width = "0%";
  document.getElementById("mic-status-text").innerText = "Micrófono: Inactivo";
}

async function recordAndPlayMic() {
  const btn = document.getElementById("btn-rec-loop");
  const statusText = document.getElementById("mic-status-text");

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mediaRecorder = new MediaRecorder(stream);
    const audioChunks = [];

    mediaRecorder.ondataavailable = e => {
      if (e.data && e.data.size > 0) audioChunks.push(e.data);
    };

    mediaRecorder.onstop = async () => {
      if (audioChunks.length === 0) {
        if (btn) {
          btn.disabled = false;
          btn.innerText = "Grabar 3s y escuchar";
        }
        if (statusText) statusText.innerText = "Error: no se capturó audio";
        unmarkCheckpassed("chk-mic", "Micrófono");
        stream.getTracks().forEach(t => t.stop());
        return;
      }

      const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });

      // Decode audio and calculate peak and RMS to detect silence / VM dummy device
      let isSilence = false;
      try {
        if (!audioContext) audioContext = new (window.AudioContext || window.webkitAudioContext)();
        if (audioContext.state === "suspended") await audioContext.resume().catch(() => {});
        const arrayBuffer = await audioBlob.arrayBuffer();
        const decodedBuffer = await audioContext.decodeAudioData(arrayBuffer.slice(0));
        const channelData = decodedBuffer.getChannelData(0);
        let maxPeak = 0;
        let sumSq = 0;
        for (let i = 0; i < channelData.length; i++) {
          const absVal = Math.abs(channelData[i]);
          if (absVal > maxPeak) maxPeak = absVal;
          sumSq += absVal * absVal;
        }
        const rms = Math.sqrt(sumSq / channelData.length);
        if (maxPeak < 0.015 || rms < 0.002) {
          isSilence = true;
        }
      } catch (decErr) {
        console.warn("Análisis de buffer omitido:", decErr);
      }

      if (isSilence) {
        if (btn) {
          btn.disabled = false;
          btn.innerText = "Grabar 3s y escuchar";
        }
        if (statusText) statusText.innerText = "No se detectó audio (micrófono mudo o sin señal)";
        unmarkCheckpassed("chk-mic", "Micrófono");
        stream.getTracks().forEach(t => t.stop());
        return;
      }

      const audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(audioUrl);
      if (statusText) statusText.innerText = "Reproduciendo audio grabado...";
      audio.play();

      audio.onended = () => {
        if (btn) {
          btn.disabled = false;
          btn.innerText = "Grabar 3s y escuchar";
        }
        if (statusText) statusText.innerText = "Prueba de audio completada";
        markCheckpassed("chk-mic", "MICRÓFONO");
        stream.getTracks().forEach(t => t.stop());
        URL.revokeObjectURL(audioUrl);
      };

      audio.onerror = () => {
        if (btn) {
          btn.disabled = false;
          btn.innerText = "Grabar 3s y escuchar";
        }
        if (statusText) statusText.innerText = "Error reproduciendo audio";
        unmarkCheckpassed("chk-mic", "Micrófono");
        stream.getTracks().forEach(t => t.stop());
        URL.revokeObjectURL(audioUrl);
      };
    };

    btn.innerText = "Grabando (3s)...";
    btn.disabled = true;
    if (statusText) statusText.innerText = "Grabando audio...";
    mediaRecorder.start();

    setTimeout(() => {
      mediaRecorder.stop();
    }, 3000);
  } catch (err) {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "Grabar 3s y escuchar";
    }
    if (statusText) statusText.innerText = "Error: " + err.message;
    unmarkCheckpassed("chk-mic", "Micrófono");
  }
}

// CHECKLIST TRACKER HELPERS
function markCheckpassed(elementId, text) {
  const el = document.getElementById(elementId);
  if (el) {
    el.classList.remove("failed");
    el.classList.add("passed");
    if (text) el.innerText = text;
  }
}

function markCheckfailed(elementId, text) {
  const el = document.getElementById(elementId);
  if (el) {
    el.classList.remove("passed");
    el.classList.add("failed");
    if (text) el.innerText = text;
  }
}

function unmarkCheckpassed(elementId, text) {
  const el = document.getElementById(elementId);
  if (el) {
    el.classList.remove("passed");
    el.classList.remove("failed");
    if (text) el.innerText = text;
  }
}

// ── CONTROL DE ENERGÍA: APAGAR / REINICIAR ───────────────────────────
let pendingPowerAction = null;

function confirmPower(action) {
  pendingPowerAction = action;
  const modal = document.getElementById("power-modal");
  const title = document.getElementById("power-modal-title");
  const msg = document.getElementById("power-modal-msg");
  const btn = document.getElementById("power-confirm-btn");
  const result = document.getElementById("power-result-msg");

  result.innerText = "";

  if (action === "shutdown") {
    title.innerText = "Confirmar apagado";
    msg.innerHTML = "¿Estás seguro de que deseas <strong>apagar</strong> este equipo?<br>Se cerrará la sesión de diagnóstico.";
    btn.className = "btn btn-power-off";
    btn.innerText = "Apagar ahora";
  } else {
    title.innerText = "Confirmar reinicio";
    msg.innerHTML = "¿Estás seguro de que deseas <strong>reiniciar</strong> este equipo?<br>Se cerrará la sesión de diagnóstico.";
    btn.className = "btn btn-power-reboot";
    btn.innerText = "Reiniciar ahora";
  }

  modal.style.display = "flex";
}

function closePowerModal() {
  document.getElementById("power-modal").style.display = "none";
  pendingPowerAction = null;
}

async function executePowerAction() {
  if (!pendingPowerAction) return;

  const result = document.getElementById("power-result-msg");
  const btn = document.getElementById("power-confirm-btn");
  btn.disabled = true;

  const endpoint = pendingPowerAction === "shutdown" ? "/api/shutdown" : "/api/reboot";
  const label = pendingPowerAction === "shutdown" ? "Apagando..." : "Reiniciando...";

  result.style.color = "#a855f7";
  result.innerText = label;

  try {
    const res = await fetch(endpoint, { method: "POST" });
    const data = await res.json();
    result.style.color = "var(--success-green)";
    result.innerText = data.message || label;
  } catch (err) {
    result.style.color = "var(--danger-red)";
    result.innerText = "Error al enviar la orden: " + err.message;
    btn.disabled = false;
  }
}

// ==============================================================================
// STRESS TEST CONTROLLER (CPU, RAM DDR3/4/5, SSD, GPU)
// ==============================================================================
let currentStressLevel = "quick";
let stressStatusPoller = null;
let gpuStressAnimId = null;
let gpuStressStartTime = 0;
let gpuStressFrameCount = 0;

function openStressModal() {
  document.getElementById("stress-modal").style.display = "flex";
  // Si no está corriendo, verificar estado
  checkStressInitialState();
}

function closeStressModal() {
  document.getElementById("stress-modal").style.display = "none";
}

function selectStressLevel(lvl) {
  currentStressLevel = lvl;
  document.querySelectorAll(".btn-level-pill").forEach(btn => {
    btn.classList.remove("active");
  });
  const activeBtn = document.getElementById(`btn-lvl-${lvl}`);
  if (activeBtn) activeBtn.classList.add("active");
}

async function checkStressInitialState() {
  try {
    const res = await fetch("/api/stress/status");
    if (res.ok) {
      const data = await res.json();
      if (data.is_running) {
        setStressUiState(true);
        startStressPolling();
      }
    }
  } catch (e) { }
}

async function startStressTest() {
  const components = [];
  if (document.getElementById("chk-stress-cpu").checked) components.push("cpu");
  if (document.getElementById("chk-stress-ram").checked) components.push("ram");
  if (document.getElementById("chk-stress-ssd").checked) components.push("ssd");
  if (document.getElementById("chk-stress-gpu").checked) components.push("gpu");

  if (components.length === 0) {
    alert("Por favor selecciona al menos un componente para la prueba de estrés.");
    return;
  }

  setStressUiState(true);
  document.getElementById("stress-results-report").style.display = "none";
  document.getElementById("stress-results-report").innerHTML = "";

  try {
    const res = await fetch("/api/stress/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ components: components, level: currentStressLevel })
    });
    const data = await res.json();
    if (!data.success) {
      alert(data.message);
      setStressUiState(false);
      return;
    }
    startStressPolling();
  } catch (err) {
    alert("Error de conexión al iniciar prueba de estrés: " + err.message);
    setStressUiState(false);
  }
}

async function stopStressTest() {
  const btn = document.getElementById("btn-stop-stress");
  btn.disabled = true;
  btn.innerText = "Abortando...";

  try {
    await fetch("/api/stress/stop", { method: "POST" });
  } catch (e) { }
}

function startStressPolling() {
  if (stressStatusPoller) clearInterval(stressStatusPoller);
  stressStatusPoller = setInterval(updateStressTelemetry, 450);
}

function stopStressPolling() {
  if (stressStatusPoller) {
    clearInterval(stressStatusPoller);
    stressStatusPoller = null;
  }
  stopGpu3DStress();
}

async function updateStressTelemetry() {
  try {
    const res = await fetch("/api/stress/status");
    if (!res.ok) return;
    const data = await res.json();

    // Actualizar progreso y tiempo
    document.getElementById("stress-progress-fill").style.width = `${data.progress_percent}%`;
    const formatTime = (sec) => {
      const m = Math.floor(sec / 60).toString().padStart(2, '0');
      const s = (sec % 60).toString().padStart(2, '0');
      return `${m}:${s}`;
    };
    document.getElementById("stress-time-display").innerText = `${formatTime(data.elapsed_sec)} / ${formatTime(data.total_duration_sec)}`;

    // Componente actual
    const badge = document.getElementById("stress-current-badge");
    if (data.current_component) {
      badge.className = "badge-purple";
      badge.innerText = `Probando: ${data.current_component.toUpperCase()}`;
    } else if (data.is_running) {
      badge.innerText = "Transición...";
    } else {
      badge.className = data.aborted ? "badge-red" : "badge-green";
      badge.innerText = data.aborted ? "Abortado" : "Completado [OK]";
    }

    // Temperatura
    document.getElementById("stress-temp-val").innerText = `${data.current_temp_c} °C`;
    document.getElementById("stress-max-temp-val").innerText = `${data.max_temp_c} °C`;

    // Activar/desactivar canvas WebGL si el componente es GPU
    if (data.current_component === "gpu" && data.is_running) {
      startGpu3DStress();
    } else {
      stopGpu3DStress();
    }

    // Renderizar Logs
    const logConsole = document.getElementById("stress-log-console");
    if (data.logs && data.logs.length > 0) {
      logConsole.innerHTML = data.logs.map(l => `
        <div class="log-line ${l.type}">[${l.time}] ${l.message}</div>
      `).join("");
      logConsole.scrollTop = logConsole.scrollHeight;
    }

    // Fin de prueba
    if (!data.is_running) {
      stopStressPolling();
      setStressUiState(false);
      renderStressFinalReport(data);
    }

  } catch (err) {
    console.warn("Error polling stress status:", err);
  }
}

function setStressUiState(isRunning) {
  document.getElementById("stress-config-container").style.display = isRunning ? "none" : "block";
  document.getElementById("stress-live-panel").style.display = "block";
  document.getElementById("btn-start-stress").style.display = isRunning ? "none" : "block";

  const stopBtn = document.getElementById("btn-stop-stress");
  stopBtn.style.display = isRunning ? "block" : "none";
  stopBtn.disabled = false;
  stopBtn.innerText = "Abortar prueba";
}

function renderStressFinalReport(data) {
  const reportContainer = document.getElementById("stress-results-report");
  reportContainer.style.display = "block";

  const results = data.results || {};
  let itemsHtml = "";

  for (const [comp, info] of Object.entries(results)) {
    const isPassed = info.passed;
    itemsHtml += `
      <div class="stress-report-item">
        <div>
          <strong style="color: ${isPassed ? 'var(--success-green)' : 'var(--danger-red)'}">
            [${isPassed ? 'OK' : 'FAIL'}] ${comp.toUpperCase()}
          </strong>
          <div style="font-size: 0.75rem; color: #94a3b8; margin-top: 0.15rem;">${info.message || ''}</div>
        </div>
        <span style="font-family: var(--font-mono); font-size: 0.8rem; color: #38bdf8;">${info.duration_sec || 0}s</span>
      </div>
    `;
  }

  reportContainer.innerHTML = `
    <div class="stress-report-title">INFORME FINAL DE ESTABILIDAD & ESTRÉS</div>
    <div class="stress-report-grid">
      ${itemsHtml || '<p style="color: #94a3b8; font-size: 0.8rem;">No se completaron componentes.</p>'}
    </div>
    <div style="margin-top: 0.75rem; font-size: 0.8rem; color: #c4b5fd; display: flex; justify-content: space-between;">
      <span>Temperatura máxima alcanzada: <strong>${data.max_temp_c} °C</strong></span>
      <span>Estado: <strong>${data.aborted ? 'Interrumpido' : 'Superado'}</strong></span>
    </div>
  `;
}

// ─────────────────────────────────────────────────────────────────
// WEBGL 3D SHADER STRESS RENDERER (GPU / iGPU)
// ─────────────────────────────────────────────────────────────────
function startGpu3DStress() {
  const container = document.getElementById("stress-gpu-canvas-container");
  if (!container) return;
  container.style.display = "block";

  if (gpuStressAnimId) return; // Ya está corriendo

  const canvas = document.getElementById("stress-webgl-canvas");
  const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
  if (!gl) {
    document.getElementById("stress-gpu-fps").innerText = "WebGL no soportado";
    return;
  }

  // Shaders de renderizado de vórtice 3D y fractales en tiempo real
  const vsSource = `
    attribute vec2 position;
    void main() {
      gl_Position = vec4(position, 0.0, 1.0);
    }
  `;

  const fsSource = `
    precision highp float;
    uniform float u_time;
    uniform vec2 u_resolution;
    void main() {
      vec2 st = (gl_FragCoord.xy * 2.0 - u_resolution) / min(u_resolution.x, u_resolution.y);
      float d = 0.0;
      for(float i=1.0; i<8.0; i++) {
        st.x += 0.3 / i * sin(i * 3.0 * st.y + u_time * 2.5);
        st.y += 0.3 / i * cos(i * 3.0 * st.x + u_time * 2.5);
      }
      float r = sin(st.x + st.y + 1.0) * 0.5 + 0.5;
      float g = sin(st.x + st.y + 2.0) * 0.5 + 0.5;
      float b = sin(st.x + st.y + 4.0) * 0.5 + 0.5;
      gl_FragColor = vec4(r * 0.8, g * 0.4 + 0.2, b * 0.9 + 0.1, 1.0);
    }
  `;

  function createShader(gl, type, source) {
    const s = gl.createShader(type);
    gl.shaderSource(s, source);
    gl.compileShader(s);
    return s;
  }

  const vs = createShader(gl, gl.VERTEX_SHADER, vsSource);
  const fs = createShader(gl, gl.FRAGMENT_SHADER, fsSource);
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  gl.useProgram(program);

  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
    -1, -1, 1, -1, -1, 1,
    -1, 1, 1, -1, 1, 1
  ]), gl.STATIC_DRAW);

  const posLoc = gl.getAttribLocation(program, "position");
  gl.enableVertexAttribArray(posLoc);
  gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

  const timeLoc = gl.getUniformLocation(program, "u_time");
  const resLoc = gl.getUniformLocation(program, "u_resolution");

  gpuStressStartTime = performance.now();
  gpuStressFrameCount = 0;
  let lastFpsUpdate = performance.now();

  function renderLoop(now) {
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform1f(timeLoc, (now - gpuStressStartTime) * 0.001);
    gl.uniform2f(resLoc, canvas.width, canvas.height);

    gl.drawArrays(gl.TRIANGLES, 0, 6);
    gpuStressFrameCount++;

    if (now - lastFpsUpdate >= 500) {
      const fps = Math.round((gpuStressFrameCount * 1000) / (now - lastFpsUpdate));
      document.getElementById("stress-gpu-fps").innerText = `GPU 3D Shader: ${fps} FPS`;
      gpuStressFrameCount = 0;
      lastFpsUpdate = now;
    }

    gpuStressAnimId = requestAnimationFrame(renderLoop);
  }

  gpuStressAnimId = requestAnimationFrame(renderLoop);
}

function stopGpu3DStress() {
  if (gpuStressAnimId) {
    cancelAnimationFrame(gpuStressAnimId);
    gpuStressAnimId = null;
  }
  const container = document.getElementById("stress-gpu-canvas-container");
  if (container) container.style.display = "none";
}

