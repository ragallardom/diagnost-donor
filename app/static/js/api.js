/* ==============================================================================
   DIAGNOSTDONOR - BACKEND REST API COMMUNICATION MODULE (js/api.js)
   Centralized async fetch calls, RAM test runner, power control & smart polling.
   ============================================================================== */

let currentPowerAction = null;

// 1. FULL DATA REFRESH (STATIC + DYNAMIC + RESET MANUAL TESTS + RUN AUTOMATIC ONES)
async function refreshAllData() {
  try {
    // 1. Reset all manual tests (and the manual failure flags)
    clearManualFails();
    if (typeof resetKeyboardTest === "function") resetKeyboardTest();
    if (typeof resetTouchpadTest === "function") resetTouchpadTest();
    if (typeof resetAudioTest === "function") resetAudioTest();
    if (typeof resetScreenTest === "function") resetScreenTest();
    if (typeof resetHdmiTest === "function") resetHdmiTest();
    if (typeof resetEthernetTest === "function") resetEthernetTest();

    // 2. Fetch each section in parallel and render it as soon as it arrives, so
    //    fast sections (system, battery, sensors) don't wait for the slow disk probes.
    const load = (url, render) => fetch(url)
      .then(res => { if (!res.ok) throw new Error(`HTTP ${res.status} en ${url}`); return res.json(); })
      .then(render)
      .catch(err => console.error("Error cargando", url, err));

    const fastSections = Promise.all([
      load("/api/system", updateSystemTab),
      load("/api/battery", data => updateBatteryTab(data)),
      load("/api/thermal", updateThermalTab),
      load("/api/wifi", updateWifiTab),
      load("/api/bluetooth", updateBluetoothTab),
      load("/api/display", updateDisplayTab),
    ]);
    // Disk probes (read tests, SMART, Opal) are the slowest part; the Opal drive
    // list itself is fetched only when its modal opens.
    load("/api/storage", storage => {
      updateStorageTab(storage);
      updateDriveSelector(storage);
    });

    await fastSections;

    // 3. Re-run all automatic tests
    setTimeout(runCpuQuickTest, 300);
    setTimeout(runRamTest, 700);
    setTimeout(startCamera, 900);
    setTimeout(startMicTest, 1100);
  } catch (err) {
    console.error("Error refreshing all diagnostic data:", err);
  }
}

// 2. SMART TELEMETRY REFRESH (DYNAMIC SENSORS, BATTERY & EXTERNAL DISPLAYS)
async function refreshTelemetry() {
  try {
    const res = await fetch("/api/telemetry");
    if (!res.ok) return;
    const data = await res.json();

    updateBatteryTab(data.battery || data.batteries);
    updateThermalTab(data.thermal);
    updateWifiTab(data.wifi);
    if (data.display) updateDisplayTab(data.display);
    if (data.storage) updateStorageTab(data.storage);
  } catch (err) {
    console.warn("Error in dynamic telemetry polling:", err);
  }
}

// Poll telemetry ~1s apart without overlapping requests: the next poll is
// scheduled only after the previous one has finished.
const TELEMETRY_INTERVAL_MS = 1000;

async function startTelemetryLoop() {
  const started = Date.now();
  await refreshTelemetry();
  const elapsed = Date.now() - started;
  setTimeout(startTelemetryLoop, Math.max(0, TELEMETRY_INTERVAL_MS - elapsed));
}

// 3. FAST MULTI-CORE CPU BENCHMARK & STABILITY TEST
async function runCpuQuickTest() {
  const btn = document.getElementById("btn-run-cputest");
  const statusEl = document.getElementById("cpu-test-status");
  if (btn) btn.disabled = true;
  if (statusEl) {
    statusEl.style.display = "block";
    statusEl.innerText = "Probando CPU...";
    statusEl.style.color = "#a855f7";
  }

  try {
    const res = await fetch("/api/cpu-test");
    const data = await res.json();

    if (data.success) {
      if (statusEl) {
        statusEl.innerText = data.message || "CPU OK";
        statusEl.style.color = "var(--success-green)";
      }
      markCheckpassed("chk-cpu", "CPU");
    } else {
      if (statusEl) {
        statusEl.innerText = data.message || "Error en CPU";
        statusEl.style.color = "var(--danger-red)";
      }
      unmarkCheckpassed("chk-cpu", "CPU");
    }
  } catch (err) {
    if (statusEl) {
      statusEl.innerText = `Error: ${err.message}`;
      statusEl.style.color = "var(--danger-red)";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// 4. RUN RAM BENCHMARK & MULTI-GB INTEGRITY CHECK
async function runRamTest() {
  const btn = document.getElementById("btn-run-ramtest") || document.getElementById("btn-ram-test");
  const statusEl = document.getElementById("ram-test-status");
  if (btn) btn.disabled = true;
  if (statusEl) {
    statusEl.style.display = "block";
    statusEl.innerText = "Analizando memoria...";
    statusEl.style.color = "#a855f7";
  }

  try {
    const res = await fetch("/api/ram-test");
    const data = await res.json();

    if (data.success) {
      if (statusEl) {
        statusEl.innerText = data.message || "256 MB verificados sin errores";
        statusEl.style.color = "var(--success-green)";
      }
      markCheckpassed("chk-ram", "RAM");
    } else {
      if (statusEl) {
        statusEl.innerText = `Atención: ${data.errors || 1} error(es) detectado(s)`;
        statusEl.style.color = "var(--danger-red)";
      }
      unmarkCheckpassed("chk-ram", "RAM");
    }
  } catch (err) {
    if (statusEl) {
      statusEl.innerText = `Error: ${err.message}`;
      statusEl.style.color = "var(--danger-red)";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// 3. EXECUTE TCG OPAL / MCAFEE PSID REVERT
let pendingOpalDevice = "";
let pendingOpalPsid = "";
let pendingOpalAction = "psid_revert";

function submitOpalRevert() {
  const driveSelect = document.getElementById("opal-drive-select");
  const psidInput = document.getElementById("opal-psid-input");
  const banner = document.getElementById("opal-result-banner");

  const device = driveSelect ? driveSelect.value : "";
  const psid = psidInput ? psidInput.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase() : "";

  if (!device) {
    if (banner) {
      banner.innerHTML = `
        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid var(--danger-red); padding: 0.85rem; border-radius: 8px; color: #fca5a5; font-weight: 600;">
          Por favor selecciona una unidad de disco objetivo.
        </div>
      `;
    }
    return;
  }

  if (!psid || psid.length !== 32) {
    if (banner) {
      banner.innerHTML = `
        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid var(--danger-red); padding: 0.85rem; border-radius: 8px; color: #fca5a5; font-weight: 600;">
          El código PSID debe tener exactamente 32 caracteres alfanuméricos. (Ingresaste ${psid.length} caracteres).
        </div>
      `;
    }
    if (psidInput) psidInput.focus();
    return;
  }

  if (banner) banner.innerHTML = "";

  pendingOpalDevice = device;
  pendingOpalPsid = psid;
  pendingOpalAction = "psid_revert";

  const confirmTitle = document.getElementById("opal-confirm-title");
  const confirmDeviceEl = document.getElementById("opal-confirm-device-text");
  const confirmPsidEl = document.getElementById("opal-confirm-psid-text");
  const confirmPsidRow = document.getElementById("opal-confirm-psid-row");
  const confirmActionEl = document.getElementById("opal-confirm-action-text");
  const confirmWarningEl = document.getElementById("opal-confirm-warning-text");

  if (confirmTitle) confirmTitle.innerText = "Confirmar PSID Revert (TCG Opal)";
  if (confirmDeviceEl) confirmDeviceEl.innerText = device;
  if (confirmPsidRow) confirmPsidRow.style.display = "flex";
  if (confirmPsidEl) confirmPsidEl.innerText = psid;
  if (confirmActionEl) confirmActionEl.innerText = "PSID Revert (sedutil) + Creación tabla GPT limpia";
  if (confirmWarningEl) {
    confirmWarningEl.innerText = "Esta operación ejecutará un reseteo de fábrica por hardware (PSID Revert). Se destruirán irreversiblemente todas las particiones y datos existentes en la unidad.";
  }

  const confirmModal = document.getElementById("opal-confirm-modal");
  if (confirmModal) confirmModal.style.display = "flex";
}

function closeOpalConfirmModal() {
  const confirmModal = document.getElementById("opal-confirm-modal");
  if (confirmModal) confirmModal.style.display = "none";
}

async function executeOpalConfirmAction() {
  await executeOpalRevertConfirmed();
}

async function executeOpalRevertConfirmed() {
  const device = pendingOpalDevice;
  const psid = pendingOpalPsid;
  closeOpalConfirmModal();

  if (!device || !psid) return;

  const psidInput = document.getElementById("opal-psid-input");
  const banner = document.getElementById("opal-result-banner");
  const logContainer = document.getElementById("opal-log-container");
  const logPre = document.getElementById("opal-log-output");
  const btn = document.getElementById("btn-exec-opal");

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner" style="display:inline-block; width:14px; height:14px; border:2px solid #fff; border-top-color:transparent; border-radius:50%; animation:spin 0.8s linear infinite; margin-right:8px; vertical-align:middle;"></span> Ejecutando desbloqueo TCG Opal...`;
  }

  if (banner) {
    banner.innerHTML = `
      <div style="background: rgba(124, 58, 237, 0.15); border: 1px solid var(--primary-violet); padding: 0.85rem; border-radius: 8px; color: #ddd6fe;">
        <strong>Ejecutando comando PSID Revert en <code>${device}</code>...</strong><br>
        <span style="font-size: 0.85rem; opacity: 0.9;">Por favor espera unos segundos. No desconectes la unidad ni apagues el equipo.</span>
      </div>
    `;
  }

  if (logContainer) logContainer.style.display = "block";
  if (logPre) logPre.innerText = `[1/5] Iniciando desbloqueo PSID en ${device}...\n`;

  try {
    const res = await apiPost("/api/opal-revert", { device, psid });
    const data = await res.json();

    if (logPre && data.log) {
      logPre.innerText = data.log;
    }

    if (data.success) {
      if (banner) {
        banner.innerHTML = `
          <div style="background: rgba(16, 185, 129, 0.15); border: 1px solid var(--success-green); padding: 1rem; border-radius: 8px; color: var(--text-main);">
            <div style="font-size: 1rem; font-weight: 700; color: var(--success-green); margin-bottom: 0.4rem;">
              Desbloqueo TCG Opal Exitoso
            </div>
            <div style="white-space: pre-line; line-height: 1.5; font-size: 0.88rem; color: #d1fae5;">${data.message}</div>
          </div>
        `;
      }
      if (psidInput) {
        psidInput.value = "";
        psidInput.style.borderColor = "";
      }
      if (typeof updatePsidCounter === "function") updatePsidCounter();
      if (typeof fetchOpalDrives === "function") fetchOpalDrives();
      if (typeof refreshAllData === "function") refreshAllData();
    } else {
      if (banner) {
        banner.innerHTML = `
          <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid var(--danger-red); padding: 1rem; border-radius: 8px; color: var(--text-main);">
            <div style="font-size: 1rem; font-weight: 700; color: var(--danger-red); margin-bottom: 0.4rem;">
              Fallo en el Desbloqueo
            </div>
            <div style="white-space: pre-line; line-height: 1.5; font-size: 0.88rem; color: #fca5a5;">${data.message || 'Verifica el código PSID y la compatibilidad del disco.'}</div>
          </div>
        `;
      }
    }
  } catch (err) {
    if (banner) {
      banner.innerHTML = `
        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid var(--danger-red); padding: 0.85rem; border-radius: 8px; color: #fca5a5;">
          <strong>Error de comunicación con el servidor:</strong> ${err.message}
        </div>
      `;
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = "Ejecutar PSID Revert";
    }
    if (btnCrypto) btnCrypto.disabled = false;
  }
}

// 4. HARDWARE STRESS TEST API ACTIONS
async function startStressTest() {
  const chkCpu = document.getElementById("chk-stress-cpu");
  const chkRam = document.getElementById("chk-stress-ram");
  const chkSsd = document.getElementById("chk-stress-ssd");
  const chkGpu = document.getElementById("chk-stress-gpu");

  const components = [];
  if (chkCpu && chkCpu.checked) components.push("cpu");
  if (chkRam && chkRam.checked) components.push("ram");
  if (chkSsd && chkSsd.checked) components.push("ssd");
  if (chkGpu && chkGpu.checked) components.push("gpu");

  if (components.length === 0) {
    alert("Debes seleccionar al menos un componente para probar.");
    return;
  }

  setStressUiState(true);

  try {
    const res = await apiPost("/api/stress/start", {
      components: components,
      level: currentStressLevel
    });
    const data = await res.json();

    if (data.success) {
      startStressPolling();
    } else {
      alert(`Error iniciando prueba: ${data.message}`);
      setStressUiState(false);
    }
  } catch (err) {
    alert(`Error de conexión: ${err.message}`);
    setStressUiState(false);
  }
}

async function stopStressTest() {
  try {
    await apiPost("/api/stress/stop");
  } catch (e) {
    console.warn("Error abortando estrés:", e);
  }
}

// 5. POWER ACTIONS (SHUTDOWN / REBOOT MODAL)
function confirmPower(action) {
  currentPowerAction = action;
  const modal = document.getElementById("power-modal");
  const title = document.getElementById("power-modal-title");
  const msg = document.getElementById("power-modal-msg");
  const resultMsg = document.getElementById("power-result-msg");
  const confirmBtn = document.getElementById("power-confirm-btn");

  if (!modal || !title || !msg || !confirmBtn) return;

  if (resultMsg) resultMsg.innerText = "";
  confirmBtn.disabled = false;

  if (action === "shutdown") {
    title.innerText = "Apagar el equipo";
    msg.innerText = "¿Deseas apagar el laptop de forma segura?";
    confirmBtn.innerText = "Apagar";
    confirmBtn.className = "btn btn-power-off";
  } else {
    title.innerText = "Reiniciar el equipo";
    msg.innerText = "¿Deseas reiniciar el laptop?";
    confirmBtn.innerText = "Reiniciar";
    confirmBtn.className = "btn btn-power-reboot";
  }

  modal.style.display = "flex";
}

function closePowerModal() {
  const modal = document.getElementById("power-modal");
  if (modal) modal.style.display = "none";
  currentPowerAction = null;
}

async function executePowerAction() {
  if (!currentPowerAction) return;
  const resultMsg = document.getElementById("power-result-msg");
  const confirmBtn = document.getElementById("power-confirm-btn");

  if (confirmBtn) confirmBtn.disabled = true;
  const endpoint = currentPowerAction === "shutdown" ? "/api/shutdown" : "/api/reboot";
  const actionLabel = currentPowerAction === "shutdown" ? "Apagando el sistema..." : "Reiniciando el sistema...";

  if (resultMsg) {
    resultMsg.innerText = actionLabel;
    resultMsg.style.color = "var(--primary-violet)";
  }

  try {
    await apiPost(endpoint);
  } catch (err) {
    if (resultMsg) {
      resultMsg.innerText = `Comando enviado: ${actionLabel}`;
      resultMsg.style.color = "var(--success-green)";
    }
  }
}
