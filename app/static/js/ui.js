/* ==============================================================================
   DIAGNOSTDONOR - UI RENDERING MODULE (js/ui.js)
   Renders hardware cards, sensor lists, and manages Checklist QA state.
   ============================================================================== */

// CHECKLIST STATE MANAGER
function markCheckpassed(pillId, text) {
  const el = document.getElementById(pillId);
  if (el) {
    el.classList.remove("failed");
    el.classList.add("passed");
    if (text) el.innerText = text;
  }
}

function markCheckfailed(pillId, text) {
  const el = document.getElementById(pillId);
  if (el) {
    el.classList.remove("passed");
    el.classList.add("failed");
    if (text) el.innerText = text;
  }
}

function unmarkCheckpassed(pillId, text) {
  const el = document.getElementById(pillId);
  if (el) {
    el.classList.remove("passed");
    el.classList.remove("failed");
    if (text) el.innerText = text;
  }
}

// FORMAT CPU SHORT NAME FOR QUICK STATS HEADER (All CPU generations supported)
function formatCpuShortName(raw) {
  if (!raw || raw === "--" || raw === "N/A") return "--";

  const clean = raw.replace(/\(R\)|\(TM\)|@.*$/gi, "").replace(/\s+/g, " ").trim();
  const upper = clean.toUpperCase();

  // 1. Intel Ultra Series (e.g., "Intel Ultra 5", "Intel Ultra 7", "Intel Ultra 9")
  const ultraMatch = clean.match(/Ultra\s+([3579])/i);
  if (ultraMatch) {
    return `Intel Ultra ${ultraMatch[1]}`;
  }

  // 2. Intel Core i3 / i5 / i7 / i9 (All generations: 1st through 14th+)
  // Covers: "i7-6700HQ", "i5 5200U", "i3-10110U", "i9-13900K", "i5 CPU M 520", "i7-8550U", etc.
  const coreIMatch = clean.match(/\b(i[3579])(?:-|\s+|\b)/i);
  if (coreIMatch) {
    const tier = coreIMatch[1].toLowerCase();
    return `Intel ${tier}`;
  }

  // 3. Intel Core m3 / m5 / m7 (e.g., Core m3-7Y30, m5-6Y54)
  const coreMMatch = clean.match(/\b(m[357])(?:-|\s+|\b)/i);
  if (coreMMatch) {
    const tier = coreMMatch[1].toLowerCase();
    return `Intel Core ${tier}`;
  }

  // 4. Intel Core 3 / 5 / 7 / 9 (New 14th+ gen branding without "i", e.g., "Core 5 120U", "Core 7 150U")
  const coreNumMatch = clean.match(/\bCore\s+([3579])\b/i);
  if (coreNumMatch) {
    return `Intel Core ${coreNumMatch[1]}`;
  }

  // 5. Intel Core 2 Duo / Quad
  if (upper.includes("CORE 2 DUO") || upper.includes("CORE(TM)2 DUO") || upper.includes("CORE2 DUO")) return "Intel Core 2 Duo";
  if (upper.includes("CORE 2 QUAD") || upper.includes("CORE(TM)2 QUAD") || upper.includes("CORE2 QUAD")) return "Intel Core 2 Quad";

  // 6. Intel other lines (Xeon, Celeron, Pentium, N-Series, Atom)
  if (upper.includes("XEON")) return "Intel Xeon";
  if (upper.includes("CELERON")) return "Intel Celeron";
  if (upper.includes("PENTIUM")) return "Intel Pentium";
  if (upper.includes("ATOM")) return "Intel Atom";
  const intelNMatch = clean.match(/\bProcessor\s+(N\d+)\b/i) || clean.match(/\b(N\d{2,4})\b/i);
  if (upper.includes("INTEL") && intelNMatch) return `Intel ${intelNMatch[1]}`;

  // 7. AMD Ryzen AI (e.g. Ryzen AI 9, Ryzen AI 7)
  const ryzenAiMatch = clean.match(/Ryzen\s+AI\s+([3579])/i);
  if (ryzenAiMatch) {
    return `AMD Ryzen AI ${ryzenAiMatch[1]}`;
  }

  // 8. AMD Ryzen 3 / 5 / 7 / 9 (Generations 1000 through 9000+)
  const ryzenMatch = clean.match(/Ryzen\s+([3579])/i);
  if (ryzenMatch) {
    return `AMD Ryzen ${ryzenMatch[1]}`;
  }

  // 9. AMD other lines (Threadripper, EPYC, Athlon, FX, A-Series, E-Series, Phenom)
  if (upper.includes("THREADRIPPER")) return "AMD Threadripper";
  if (upper.includes("EPYC")) return "AMD EPYC";
  if (upper.includes("ATHLON")) return "AMD Athlon";
  if (upper.includes("PHENOM")) return "AMD Phenom";
  if (upper.includes("FX-") || upper.includes("FX(TM)-") || /\bFX\s*\d{4}/i.test(clean)) return "AMD FX";

  const amdAMatch = clean.match(/\b(A[4689]|A1[02])(?:-|\s+)/i);
  if (amdAMatch) return `AMD ${amdAMatch[1].toUpperCase()}`;

  const amdEMatch = clean.match(/\b(E[12]|E\d{3,4})(?:-|\s+)/i);
  if (amdEMatch) return `AMD ${amdEMatch[1].toUpperCase()}`;

  // 10. Snapdragon
  if (upper.includes("SNAPDRAGON")) {
    if (upper.includes("X ELITE")) return "Snapdragon X Elite";
    if (upper.includes("X PLUS")) return "Snapdragon X Plus";
    return "Snapdragon";
  }

  // 11. Apple Silicon
  const appleMatch = clean.match(/\b(M[1234](?:\s+(?:Pro|Max|Ultra))?)\b/i);
  if (appleMatch) return `Apple ${appleMatch[1]}`;

  // 12. General Brand Fallback
  if (upper.includes("INTEL")) return "Intel";
  if (upper.includes("AMD")) return "AMD";

  return clean.split(" ")[0];
}

// FORMAT LAPTOP / DESKTOP MODEL SHORT NAME FOR QUICK STATS HEADER (Dynamic multi-brand engine)
function formatModelShortName(modelStr) {
  if (!modelStr || ["--", "N/A", "To be filled by O.E.M.", "Default string", "System Product Name"].includes(modelStr.trim())) {
    return "--";
  }

  let s = modelStr.trim();

  // Strip anything in parentheses (e.g. part numbers / SKU codes like "(SBKPFV3)", hardware revs "(1.0)")
  s = s.replace(/\s*\([^)]*\)/g, "").trim();

  // 1. Clean common redundant brand prefixes (including repeated e.g. "HP HP ")
  s = s.replace(/^(?:(LENOVO|HP|Hewlett-Packard|Dell\s+Inc\.?|Dell|ASUSTeK\s+COMPUTER\s+INC\.?|ASUS|Acer|Apple\s+Inc\.?|Apple|Microsoft\s+Corporation|Micro-Star\s+International\s+Co\.,\s+Ltd\.?|MSI|SAMSUNG|Toshiba|Dynabook)\s*[:\-]?\s*)+/i, "");

  // Strip machine type codes before model name (e.g. '21MLCTO1WW ThinkPad T14 Gen 6')
  s = s.replace(/^[0-9A-Z]{4,10}\s+(ThinkPad|ThinkBook|IdeaPad|Legion|Yoga|EliteBook|ProBook|Latitude|Precision|XPS|ZBook)/i, "$1");

  // 2. Lenovo ThinkPad X1 Carbon / Yoga / Nano / Extreme / Titanium / Fold
  const tpX1 = s.match(/ThinkPad\s+(X1\s+(?:Carbon|Yoga|Nano|Extreme|Titanium|Fold)(?:\s+(?:Gen\s+\d+|\d+th\s+Gen))?)/i);
  if (tpX1) {
    return tpX1[1].replace(/(\d+)th\s+Gen/i, "Gen $1");
  }

  // 3. Lenovo ThinkPad Series (T14, T14s, T15, T16, T480, T490, L14, L15, E14, E15, P14s, P15, P16, P1, X13, X13s, X280, X390, Z13, Z16, etc.)
  const tpMatch = s.match(/ThinkPad\s+([A-Z]\d+[a-z]?(?:\s+(?:Gen\s+\d+|\d+th\s+Gen))?)/i);
  if (tpMatch) {
    return tpMatch[1].replace(/(\d+)th\s+Gen/i, "Gen $1");
  }

  // 4. Lenovo ThinkBook / IdeaPad / Legion / Yoga
  const lenovoMatch = s.match(/(ThinkBook|IdeaPad|Legion|Yoga)\s+([^,]+)/i);
  if (lenovoMatch) {
    const family = lenovoMatch[1];
    let rest = lenovoMatch[2].replace(/\b(Notebook\s+PC|Laptop\s+PC|Laptop|PC)\b/gi, "");
    rest = rest.replace(/(\d+)th\s+Gen/gi, "Gen $1").replace(/\s+/g, " ").trim();
    return `${family} ${rest}`.trim();
  }

  // 5. HP (EliteBook, ProBook, ZBook, Dragonfly, Pavilion, Envy, Spectre, Omen, Victus)
  const hpMatch = s.match(/(EliteBook|ProBook|ZBook|Dragonfly|Pavilion|Envy|Spectre|Omen|Victus)\s+([^,]+)/i);
  if (hpMatch) {
    const family = hpMatch[1];
    let rest = hpMatch[2];
    rest = rest.replace(/\d+(?:\.\d+)?\s*(?:inch|\"|\-inch)/gi, "");
    rest = rest.replace(/\b(Notebook\s+PC|Mobile\s+Workstation|Laptop\s+PC|Laptop|PC)\b/gi, "");
    rest = rest.replace(/\s+/g, " ").trim();
    return `${family} ${rest}`.trim();
  }

  // 6. Dell (Latitude, Precision, XPS, Inspiron, Vostro, Alienware, OptiPlex)
  const dellMatch = s.match(/(Latitude|Precision|XPS|Inspiron|Vostro|Alienware|OptiPlex)\s+(\d+[\w]*(?:\s+\d+[\w]*)?)/i);
  if (dellMatch) {
    return `${dellMatch[1]} ${dellMatch[2]}`.trim();
  }

  // 7. ASUS (ROG Zephyrus, ROG Strix, TUF Gaming, ZenBook, VivoBook, ExpertBook)
  const asusMatch = s.match(/(ROG\s+(?:Zephyrus|Strix|Flow)|TUF\s+Gaming|ZenBook|VivoBook|ExpertBook)\s+([^,]+)/i);
  if (asusMatch) {
    const family = asusMatch[1];
    let rest = asusMatch[2].replace(/\b(Notebook\s+PC|Laptop\s+PC|Laptop|PC)\b/gi, "").replace(/\s+/g, " ").trim();
    return `${family} ${rest}`.trim();
  }

  // 8. Acer (Swift, Aspire, Nitro, Predator, Spin, TravelMate)
  const acerMatch = s.match(/(Swift|Aspire|Nitro|Predator|Spin|TravelMate)\s+([^,]+)/i);
  if (acerMatch) {
    const family = acerMatch[1];
    let rest = acerMatch[2].replace(/\b(Notebook\s+PC|Laptop\s+PC|Laptop|PC)\b/gi, "").replace(/\s+/g, " ").trim();
    return `${family} ${rest}`.trim();
  }

  // 9. Dynabook / Toshiba (Portégé, Tecra, Satellite Pro)
  const dynaMatch = s.match(/(Port[eé]g[eé]|Tecra|Satellite\s+Pro)\s+([^,]+)/i);
  if (dynaMatch) {
    const family = dynaMatch[1];
    let rest = dynaMatch[2].replace(/\b(Notebook\s+PC|Laptop\s+PC|Laptop|PC)\b/gi, "").replace(/\s+/g, " ").trim();
    return `${family} ${rest}`.trim();
  }

  // 10. Universal clean fallback for any other laptop/motherboard model
  s = s.replace(/\b(Notebook\s+PC|Mobile\s+Workstation|Laptop\s+PC|Laptop|PC|System\s+Product\s+Name)\b/gi, "");
  s = s.replace(/\s+/g, " ").trim();

  if (s.length > 24) {
    return s.slice(0, 24).trim();
  }
  return s || "--";
}

// 1. UPDATE SYSTEM IDENTIFICATION & CPU
function updateSystemTab(sys) {
  if (!sys) return;

  const serialStr = sys.serial && sys.serial !== 'N/A' ? sys.serial : 'N/A';
  const headerSerialEl = document.getElementById("header-serial");
  const sysSerialEl = document.getElementById("sys-serial");
  if (headerSerialEl) headerSerialEl.innerText = `S/N: ${serialStr}`;
  if (sysSerialEl) sysSerialEl.innerText = serialStr;

  const cardModel = (sys.model || "").replace(/\b(HP|LENOVO|DELL|ASUS|ACER)\s+\1\b/gi, "$1").trim();
  const sysModelEl = document.getElementById("sys-model");
  const quickModelEl = document.getElementById("quick-model");
  const sysVendorEl = document.getElementById("sys-vendor");
  if (sysModelEl) sysModelEl.innerText = cardModel || "Detectando modelo...";
  if (quickModelEl) quickModelEl.innerText = formatModelShortName(cardModel);
  if (sysVendorEl) sysVendorEl.innerText = sys.vendor || "--";

  const sysCpuEl = document.getElementById("sys-cpu");
  const sysArchEl = document.getElementById("sys-arch");
  const quickCpuEl = document.getElementById("quick-cpu");
  if (sysCpuEl) sysCpuEl.innerText = sys.cpu || "--";
  if (sysArchEl) sysArchEl.innerText = sys.architecture || "--";
  if (quickCpuEl) quickCpuEl.innerText = formatCpuShortName(sys.cpu);

  if (sys.ram) {
    const sysRamEl = document.getElementById("sys-ram");
    const ramUsedEl = document.getElementById("ram-used-detail");
    const quickRamEl = document.getElementById("quick-ram");
    const ramProgEl = document.getElementById("ram-progress");

    if (sysRamEl) sysRamEl.innerText = `${sys.ram.total_gb} GB Instalados`;
    if (ramUsedEl) ramUsedEl.innerText = `Usado: ${sys.ram.used_gb} GB (${sys.ram.percent_used}%)`;
    if (quickRamEl) quickRamEl.innerText = `${sys.ram.total_gb} GB`;
    if (ramProgEl) ramProgEl.style.width = `${sys.ram.percent_used}%`;
  }
}

// 2. UPDATE BATTERY TELEMETRY & HEALTH
function updateBatteryTab(batteries) {
  if (!batteries || batteries.length === 0) return;
  const bat = Array.isArray(batteries) ? batteries[0] : batteries;

  const quickBat = document.getElementById("quick-bat");
  const quickCharge = document.getElementById("quick-charge-status");
  const batCap = document.getElementById("bat-capacity");
  const batStatus = document.getElementById("bat-status-text");
  const batHealth = document.getElementById("bat-health-val");
  const batDesign = document.getElementById("bat-design-wh");
  const batFull = document.getElementById("bat-full-wh");
  const batCycles = document.getElementById("bat-cycles");
  const batVoltage = document.getElementById("bat-voltage");

  const statusColor = bat.has_charge_error ? "#ef4444" : (bat.is_charging ? "#10b981" : (bat.is_full ? "#3b82f6" : (bat.is_conservation ? "#a855f7" : "")));

  const cleanStatus = (bat.status_es || bat.status || "").replace(/\s*\(\d+%\)/g, "").trim();

  if (quickBat) quickBat.innerText = `${bat.capacity_percent}%`;
  if (quickCharge) {
    quickCharge.innerText = cleanStatus;
    quickCharge.style.color = statusColor || "";
  }
  if (batCap) batCap.innerText = `${bat.capacity_percent}%`;
  if (batStatus) {
    batStatus.innerText = cleanStatus;
    batStatus.style.color = statusColor || "";
  }

  if (batHealth) batHealth.innerText = `${bat.health_percent}%`;
  if (batDesign) batDesign.innerText = `${bat.design_wh} Wh`;
  if (batFull) batFull.innerText = `${bat.full_wh} Wh`;
  if (batCycles) batCycles.innerText = bat.cycle_count || "N/A";
  if (batVoltage) batVoltage.innerText = `${bat.voltage_v} V`;

  const alertBanner = document.getElementById("charge-alert-banner");
  if (alertBanner) {
    if (bat.has_charge_error && bat.error_msg) {
      alertBanner.innerHTML = `
        <div style="background-color: rgba(239, 68, 68, 0.2); border: 1px solid var(--danger-red); color: #fca5a5; padding: 0.5rem; border-radius: 6px; font-size: 0.8rem; margin-top: 0.4rem;">
          ${bat.error_msg}
        </div>
      `;
    } else if (bat.is_conservation) {
      alertBanner.innerHTML = `
        <div style="background-color: rgba(168, 85, 247, 0.15); border: 1px solid rgba(168, 85, 247, 0.4); color: #d8b4fe; padding: 0.45rem 0.6rem; border-radius: 6px; font-size: 0.78rem; margin-top: 0.4rem;">
          Modo de protección de batería activo (Límite: ${bat.charge_threshold}%). La carga se detiene para prolongar la vida útil de la batería.
        </div>
      `;
    } else {
      alertBanner.innerHTML = '';
    }
  }
}

// 3. UPDATE THERMAL SENSORS & FANS
function updateThermalTab(thermal) {
  if (!thermal) return;

  const fansContainer = document.getElementById("fans-list");
  if (fansContainer) {
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
  }

  const tempsContainer = document.getElementById("temps-list");
  if (tempsContainer) {
    if (thermal.temperatures && thermal.temperatures.length > 0) {
      tempsContainer.innerHTML = thermal.temperatures.map(t => `
        <div class="sensor-item">
          <span>${t.label}</span>
          <strong style="color: ${t.temp_c > 80 ? 'var(--danger-red)' : 'var(--success-green)'}">${Math.round(t.temp_c)} °C</strong>
        </div>
      `).join("");
    }
  }
}

let _lastInternalStorageJson = "";
let _lastUsbStorageJson = "";

// 4. UPDATE STORAGE (INTERNAL SSD/HDD & USB EXTERNAL DRIVES)
function updateStorageTab(storage) {
  if (!storage) return;

  let internalList = [];
  let usbList = [];

  if (Array.isArray(storage)) {
    internalList = storage.filter(s => !s.is_usb);
    usbList = storage.filter(s => s.is_usb);
  } else if (typeof storage === "object") {
    internalList = storage.internal || [];
    usbList = storage.usb || [];
  }

  // 4a. Render Internal SSD / HDD
  const internalContainer = document.getElementById("storage-list");
  if (internalContainer) {
    const currentInternalJson = JSON.stringify(internalList);
    const isHoveringTip = Boolean(internalContainer.querySelector('.info-tip-wrap:hover'));
    if (currentInternalJson !== _lastInternalStorageJson && !isHoveringTip) {
      _lastInternalStorageJson = currentInternalJson;
      if (internalList.length > 0) {
        internalContainer.innerHTML = internalList.map(s => {
          const smartText = (s.smart_status || '').includes('100%') ? 'Salud 100% (Sin errores)' : (s.smart_status || 'Correcto');
          const hasReadTests = Boolean(s.device_read_test && s.nvme_read_test);
          const devReadPassed = s.device_read_test === 'PASSED';
          const nvmeReadPassed = s.nvme_read_test === 'PASSED';
          const isOpal = hasReadTests && (!devReadPassed || !nvmeReadPassed);

          let readSectionHtml = '';
          if (s.device_read_test && s.nvme_read_test) {
            readSectionHtml = `
              <div class="card-spec-item">
                <span class="spec-label">Pruebas de lectura</span>
                <div class="spec-value spec-value-detail" style="font-family: var(--font-mono); font-size: 0.82rem; line-height: 1.45;">
                  Device Read: <span style="color: ${devReadPassed ? 'var(--success-green)' : '#f87171'}; font-weight: 700;">${s.device_read_test}</span><br>
                  NVMe Read: <span style="color: ${nvmeReadPassed ? 'var(--success-green)' : '#f87171'}; font-weight: 700;">${s.nvme_read_test}</span>
                </div>
              </div>
            `;
          }

          let opalAlertHtml = '';
          if (isOpal) {
            opalAlertHtml = `
              <div class="card-spec-item" style="background: rgba(239, 68, 68, 0.08); border-left: 3px solid #ef4444; border-radius: 4px; padding: 0.45rem 0.6rem; margin-top: 0.35rem; display: flex; flex-direction: column; gap: 0.2rem;">
                <div class="spec-value spec-value-detail" style="color: #f87171; font-weight: 700; font-size: 0.82rem;">
                  Posible bloqueo por cifrado TCG Opal
                </div>
              </div>
            `;
          }

          let enduranceHtml = '';
          if (s.endurance && s.endurance.supported) {
            enduranceHtml = `
              <div class="card-spec-item">
                <span class="spec-label">Vida útil y desgaste (Endurance)</span>
                <div class="spec-value spec-value-detail" style="font-family: var(--font-mono); font-size: 0.82rem; line-height: 1.55;">
                  Total Escrito (TBW): <span style="font-weight: 600; color: var(--text-main);">${s.endurance.tbw_str}</span>
                  <span class="info-tip-wrap">
                    <span class="info-tip-icon">i</span>
                    <span class="info-tip-box">
                      <strong style="color: #f1f5f9; display: block; margin-bottom: 0.25rem;">Total Escrito - TBW (SSD):</strong>
                      <span style="display: block; color: #94a3b8; margin-bottom: 0.35rem; font-size: 0.72rem;">
                        Terabytes Escritos (TBW): volumen total acumulado de datos grabados en las celdas flash desde su fabricación.
                      </span>
                      <strong style="color: #e2e8f0; display: block; margin-bottom: 0.2rem;">Límites típicos según tamaño:</strong>
                      • 128 - 256 GB: 75 a 150 TBW<br>
                      • 512 GB: 150 a 300 TBW<br>
                      • 1 TB: 300 a 600 TBW<br>
                      • 2 TB: 600 a 1200 TBW<br>
                      <span style="display: block; color: #38bdf8; margin-top: 0.3rem; font-size: 0.69rem;">
                        *Superar el límite del fabricante aumenta el riesgo de fallos o modo solo lectura.
                      </span>
                    </span>
                  </span><br>
                  Ciclos P/E: <span style="font-weight: 600; color: var(--text-main);">${s.endurance.pe_cycles_str}</span>
                  <span class="info-tip-wrap">
                    <span class="info-tip-icon">i</span>
                    <span class="info-tip-box">
                      <strong style="color: #f1f5f9; display: block; margin-bottom: 0.25rem;">Ciclos P/E (SSD):</strong>
                      <span style="display: block; color: #94a3b8; margin-bottom: 0.35rem; font-size: 0.72rem;">
                        Ciclos Programación/Borrado: promedio de veces que cada bloque de memoria física ha sido borrado y reescrito.
                      </span>
                      <strong style="color: #e2e8f0; display: block; margin-bottom: 0.2rem;">Referencia de desgaste:</strong>
                      • 0 a 100: Excelente (prácticamente nuevo)<br>
                      • 100 a 300: Muy bueno (vida útil óptima)<br>
                      • 300 a 600: Uso moderado / normal<br>
                      • Más de 800: Desgaste alto (memorias TLC/QLC toleran 600 - 1500 ciclos)
                    </span>
                  </span>
                </div>
              </div>
            `;
          }

          return `
            <div class="card-spec-item">
              <span class="spec-label">Disco interno (${s.type || 'SSD'})</span>
              <div class="spec-value spec-value-accent" style="font-size: 0.95rem;">${s.model} (${s.size_gb} GB)</div>
            </div>
            <div class="card-spec-item">
              <span class="spec-label">Dispositivo</span>
              <div class="spec-value spec-value-detail"><code>${s.device}</code></div>
            </div>
            <div class="card-spec-item">
              <span class="spec-label">Salud del disco (SMART)</span>
              <div class="spec-value spec-value-detail" style="color: ${isOpal ? '#f59e0b' : 'var(--success-green)'}; font-weight: 700;">
                ${isOpal ? 'SMART PASSED' : smartText}
              </div>
            </div>
            ${enduranceHtml}
            ${readSectionHtml}
            ${opalAlertHtml}
          `;
        }).join("<hr class='divider' style='margin: 0.6rem 0;'>");
        markCheckpassed("chk-ssd", "SSD");
      } else {
        internalContainer.innerHTML = `
          <div class="card-spec-item">
            <span class="spec-label">Disco interno</span>
            <div class="spec-value spec-value-detail" style="color: var(--text-muted);">Sin discos internos detectados</div>
          </div>
        `;
      }
    }
  }

  // 4b. Render USB External Storage
  const usbContainer = document.getElementById("usb-storage-list");
  if (usbContainer) {
    const currentUsbJson = JSON.stringify(usbList);
    if (currentUsbJson !== _lastUsbStorageJson) {
      _lastUsbStorageJson = currentUsbJson;
      if (usbList.length > 0) {
        usbContainer.innerHTML = usbList.map(u => `
          <div class="card-spec-item">
            <span class="spec-label">Almacenamiento USB</span>
            <div class="spec-value spec-value-accent" style="font-size: 0.95rem;">${u.model} (${u.size_gb} GB)</div>
          </div>
          <div class="card-spec-item">
            <span class="spec-label">Dispositivo</span>
            <div class="spec-value spec-value-detail"><code>${u.device}</code> (${u.type || 'USB Drive'})</div>
          </div>
          <div class="card-spec-item">
            <span class="spec-label">Estado de conexión</span>
            <div class="spec-value spec-value-detail" style="color: var(--success-green); font-weight: 700;">
              ${u.smart_status || 'Conectado OK'}
            </div>
          </div>
        `).join("<hr class='divider' style='margin: 0.6rem 0;'>");
      } else {
        usbContainer.innerHTML = `
          <div class="card-spec-item">
            <span class="spec-label">Almacenamiento USB</span>
            <div class="spec-value spec-value-detail" style="color: #cbd5e1;">Sin unidades USB conectadas</div>
          </div>
          <div class="card-spec-item">
            <span class="spec-label">Puerto</span>
            <div class="spec-value spec-value-detail" style="color: #94a3b8; font-size: 0.8rem;">Listo para pendrive / disco externo</div>
          </div>
        `;
      }
    }
  }
}

// 5. UPDATE BLUETOOTH ADAPTER
function updateBluetoothTab(bt) {
  if (!bt) return;
  const textEl = document.getElementById("bt-status-text");
  const detailEl = document.getElementById("bt-name-detail");

  if (bt.present) {
    if (textEl) {
      textEl.innerText = "Operativo y alimentado";
      textEl.style.color = "var(--success-green)";
    }
    if (detailEl) detailEl.innerText = bt.name || "HCI0";
    markCheckpassed("chk-bt", "BLUETOOTH");
  } else {
    if (textEl) {
      textEl.innerText = "No detectado";
      textEl.style.color = "var(--danger-red)";
    }
    if (detailEl) detailEl.innerText = "Sin adaptador activo";
    unmarkCheckpassed("chk-bt", "Bluetooth");
  }
}

// 6. UPDATE DISPLAY & HDMI (STRICT EXTERNAL MONITORS)
let hdmiEverConnected = false;

function resetHdmiTest() {
  hdmiEverConnected = false;
  unmarkCheckpassed("chk-hdmi", "HDMI");
}

function updateDisplayTab(display) {
  if (!display) return;
  const moboName = document.getElementById("mobo-name");
  const moboBios = document.getElementById("mobo-bios");
  if (moboName) moboName.innerText = display.motherboard || "--";
  if (moboBios) moboBios.innerText = display.bios_version || "--";

  const hdmiEl = document.getElementById("hdmi-status-text");
  if (hdmiEl) {
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
}

// 7. UPDATE WI-FI & ETHERNET NETWORKS TABLE
function updateWifiTab(wifi) {
  if (!wifi) return;

  // 7a. Wi-Fi networks and adapter
  const listContainer = document.getElementById("wifi-networks-list");
  if (listContainer) {
    if (wifi.nearby_networks && wifi.nearby_networks.length > 0) {
      listContainer.innerHTML = wifi.nearby_networks.map(n => `
        <tr>
          <td><strong>${n.ssid}</strong></td>
          <td>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
              <div class="progress-bar-tech" style="flex: 1; height: 6px;">
                <div class="progress-fill-tech" style="width: ${n.signal}%;"></div>
              </div>
              <span style="font-size: 0.75rem; font-family: var(--font-mono);">${n.signal}%</span>
            </div>
          </td>
        </tr>
      `).join("");

      const statusEl = document.getElementById("wifi-auto-status");
      if (statusEl) {
        statusEl.innerText = `${wifi.nearby_networks.length} detectadas`;
        statusEl.style.color = "var(--success-green)";
      }
      markCheckpassed("chk-wifi", "WI-FI");
    } else if (wifi.wifi_hardware_present) {
      listContainer.innerHTML = `<tr><td colspan="2" style="text-align: center; color: var(--success-green);">Adaptador Wi-Fi operativo (escaneando redes...)</td></tr>`;
      const statusEl = document.getElementById("wifi-auto-status");
      if (statusEl) {
        statusEl.innerText = "Adaptador detectado";
        statusEl.style.color = "var(--success-green)";
      }
      markCheckpassed("chk-wifi", "WI-FI");
    } else {
      listContainer.innerHTML = `<tr><td colspan="2" style="text-align: center; color: var(--text-muted);">No se detectaron redes Wi-Fi cercanas.</td></tr>`;
      unmarkCheckpassed("chk-wifi", "Wi-Fi");
    }
  }

  // 7b. Ethernet RJ-45
  const eth = wifi.ethernet;
  if (eth) {
    const ethStatus = document.getElementById("eth-status-text");
    const ethIface = document.getElementById("eth-iface-text");
    const ethCarrier = document.getElementById("eth-carrier-text");
    const ethLoopback = document.getElementById("eth-loopback-text");

    const isConnected = eth.present && (eth.connected || eth.loopback_verified);

    if (isConnected) {
      ethernetTestedPassed = true;
      markCheckpassed("chk-eth", "ETHERNET");
      if (ethStatus) {
        ethStatus.innerText = "Cable conectado";
        ethStatus.style.color = "var(--success-green)";
      }
      if (ethIface && eth.primary) {
        const speedStr = eth.primary.speed_mbps ? ` (${eth.primary.speed_mbps} Mbps)` : "";
        ethIface.innerHTML = `<code>${eth.primary.interface}</code>${speedStr}`;
      }
      if (ethCarrier) {
        ethCarrier.innerText = "Enlace activo";
        ethCarrier.style.color = "var(--success-green)";
      }
      if (ethLoopback) {
        ethLoopback.innerText = "Enlace activo";
        ethLoopback.style.color = "var(--success-green)";
      }
    } else if (eth.present && !eth.connected && !eth.loopback_verified) {
      if (ethernetTestedPassed) {
        markCheckpassed("chk-eth", "ETHERNET");
        if (ethStatus) {
          ethStatus.innerText = "Validado con éxito";
          ethStatus.style.color = "var(--success-green)";
        }
        if (ethIface && eth.primary) {
          ethIface.innerHTML = `<code>${eth.primary.interface}</code>`;
        }
        if (ethCarrier) {
          ethCarrier.innerText = "Cable desconectado";
          ethCarrier.style.color = "var(--text-muted)";
        }
        if (ethLoopback) {
          ethLoopback.innerText = "Validado";
          ethLoopback.style.color = "var(--success-green)";
        }
      } else {
        unmarkCheckpassed("chk-eth", "Ethernet");
        if (ethStatus) {
          ethStatus.innerText = "Puerto disponible";
          ethStatus.style.color = "var(--text-main)";
        }
        if (ethIface && eth.primary) {
          ethIface.innerHTML = `<code>${eth.primary.interface}</code>`;
        }
        if (ethCarrier) {
          ethCarrier.innerText = "Cable desconectado";
          ethCarrier.style.color = "var(--text-muted)";
        }
        if (ethLoopback) {
          ethLoopback.innerText = "En espera de cable";
          ethLoopback.style.color = "var(--text-muted)";
        }
      }
    } else {
      if (ethernetTestedPassed) {
        markCheckpassed("chk-eth", "ETHERNET");
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
          ethCarrier.innerText = "Sin puerto RJ-45";
          ethCarrier.style.color = "var(--text-muted)";
        }
        if (ethLoopback) {
          ethLoopback.innerText = "No aplicable";
          ethLoopback.style.color = "var(--text-muted)";
        }
      }
    }
  }
}

let ethernetTestedPassed = false;
function resetEthernetTest() {
  ethernetTestedPassed = false;
  unmarkCheckpassed("chk-eth", "Ethernet");
}

// 8. UPDATE TARGET OPAL DRIVE SELECTOR
function updateDriveSelector(storage) {
  if (!storage) return;
  const select = document.getElementById("opal-drive-select");
  if (!select) return;

  let driveList = [];
  if (Array.isArray(storage)) {
    driveList = storage;
  } else if (storage.internal || storage.usb) {
    driveList = [...(storage.internal || []), ...(storage.usb || [])];
  }

  if (driveList.length === 0) return;

  const currentVal = select.value;
  select.innerHTML = driveList.map(s => {
    const dev = s.device || s.name || "";
    const model = s.model || "Disco SSD";
    const type = s.type || (s.transport ? `${s.transport} SSD` : (s.is_usb ? "USB SSD" : "SSD"));
    const lockedBadge = s.is_opal_locked ? " [BLOQUEADO OPAL]" : "";
    return `<option value="${dev}">${dev} - ${model} (${type})${lockedBadge}</option>`;
  }).join("");

  if (currentVal && Array.from(select.options).some(o => o.value === currentVal)) {
    select.value = currentVal;
  }
}
