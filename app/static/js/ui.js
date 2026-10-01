/* ==============================================================================
   DIAGNOSTDONOR - UI RENDERING MODULE (js/ui.js)
   Renders hardware cards, sensor lists, and manages Checklist QA state.
   ============================================================================== */

// CHECKLIST STATE MANAGER
// "n/total" counter next to the checklist title: passed pills over all pills.
function updateChecklistProgress() {
  const el = document.getElementById("chk-progress");
  if (!el) return;
  const pills = [...document.querySelectorAll(".chk-bar-grid .chk-pill")].filter(p => p.style.display !== "none");
  const passed = pills.filter(p => p.classList.contains("passed")).length;
  const failed = pills.filter(p => p.classList.contains("failed")).length;
  el.innerText = `${passed}/${pills.length}`;
  el.classList.toggle("all-passed", pills.length > 0 && passed === pills.length);
  el.classList.toggle("has-failed", failed > 0);
}

// The technician can flag any test as failed by hand (things the app cannot detect, e.g. an HDMI
// monitor that stays black). The flag wins over the automatic state; the automatic state is kept so
// that unflagging restores it.
const manualFails = new Set();
const autoStates = {};   // pillId -> "passed" | "failed" | ""

function setCheck(pillId, state, text) {
  const el = document.getElementById(pillId);
  if (el) {
    autoStates[pillId] = state;
    if (text) (el.querySelector(".chk-text") || el).innerText = text;
    const shown = manualFails.has(pillId) ? "failed" : state;
    el.classList.toggle("passed", shown === "passed");
    el.classList.toggle("failed", shown === "failed");
    el.classList.toggle("manual", manualFails.has(pillId));
  }
  updateChecklistProgress();
}

function markCheckpassed(pillId, text) { setCheck(pillId, "passed", text); }
function markCheckfailed(pillId, text) { setCheck(pillId, "failed", text); }
function unmarkCheckpassed(pillId, text) { setCheck(pillId, "", text); }

function isManualFail(pillId) { return manualFails.has(pillId); }

function toggleManualFail(pillId) {
  if (manualFails.has(pillId)) manualFails.delete(pillId); else manualFails.add(pillId);
  setCheck(pillId, autoStates[pillId] || "", null);
}

function clearManualFails() {
  [...manualFails].forEach(id => { manualFails.delete(id); setCheck(id, autoStates[id] || "", null); });
}

// Adds the small "✗" button to every checklist chip (the text moves into its own span).
function initFailButtons() {
  document.querySelectorAll(".chk-bar-grid .chk-pill").forEach(pill => {
    if (pill.querySelector(".chk-text")) return;
    const text = document.createElement("span");
    text.className = "chk-text";
    text.innerText = pill.innerText;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chk-fail-btn";
    btn.innerText = "✗";
    btn.title = "Marcar como fallo (otro clic lo quita)";
    btn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); toggleManualFail(pill.id); });
    pill.innerText = "";
    pill.append(text, btn);
  });
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

// Brand shown before the short model in the top bar ("Lenovo T14 Gen 1", "HP EliteBook 845 G8").
// Taken from the DMI vendor, falling back to the model string; empty for unknown/placeholder vendors.
const BRAND_PATTERNS = [
  [/lenovo/i, "Lenovo"],
  [/hewlett|^hp\b|\bhp\b/i, "HP"],
  [/dell/i, "Dell"],
  [/asus/i, "ASUS"],
  [/acer/i, "Acer"],
  [/apple/i, "Apple"],
  [/microsoft/i, "Microsoft"],
  [/micro-star|\bmsi\b/i, "MSI"],
  [/samsung/i, "Samsung"],
  [/toshiba|dynabook/i, "Dynabook"],
  [/huawei/i, "Huawei"],
  [/lg electronics/i, "LG"],
];

function detectBrand(vendor, modelStr) {
  for (const text of [vendor || "", modelStr || ""]) {
    for (const [re, name] of BRAND_PATTERNS) {
      if (re.test(text)) return name;
    }
  }
  return "";
}

// Short model with its brand in front. The brand is not repeated if the short name already has it.
function formatModelWithBrand(modelStr, vendor) {
  const short = formatModelShortName(modelStr);
  if (short === "--") return short;
  const brand = detectBrand(vendor, modelStr);
  if (!brand || short.toLowerCase().startsWith(brand.toLowerCase())) return short;
  return `${brand} ${short}`;
}

// FORMAT LAPTOP / DESKTOP MODEL SHORT NAME FOR QUICK STATS HEADER (Dynamic multi-brand engine)
// "6th", "7th Gen", "3rd" -> "Gen 6", "Gen 7", "Gen 3". "Gen 9" is left as is.
function normalizeGeneration(text) {
  return text.replace(/(\d+)(?:st|nd|rd|th)(?:\s+Gen)?/i, "Gen $1").replace(/\s+/g, " ").trim();
}

function formatModelShortName(modelStr) {
  if (!modelStr || ["--", "N/A", "To be filled by O.E.M.", "Default string", "System Product Name"].includes(modelStr.trim())) {
    return "--";
  }

  let s = modelStr.trim();

  // "LENOVO 20S0S1EJ00 (ThinkPad T14 Gen 1)": the part number is outside and the real
  // name inside the parentheses. Keep the name, not the code.
  const codeThenName = s.match(/^(?:LENOVO\s+)?[0-9][0-9A-Z]{6,11}\s*\(([^)]*[A-Za-z]{3,}[^)]*)\)$/i);
  if (codeThenName) s = codeThenName[1].trim();

  // Strip anything in parentheses (e.g. part numbers / SKU codes like "(SBKPFV3)", hardware revs "(1.0)")
  s = s.replace(/\s*\([^)]*\)/g, "").trim();

  // 1. Clean common redundant brand prefixes (including repeated e.g. "HP HP ")
  s = s.replace(/^(?:(LENOVO|HP|Hewlett-Packard|Dell\s+Inc\.?|Dell|ASUSTeK\s+COMPUTER\s+INC\.?|ASUS|Acer|Apple\s+Inc\.?|Apple|Microsoft\s+Corporation|Micro-Star\s+International\s+Co\.,\s+Ltd\.?|MSI|SAMSUNG|Toshiba|Dynabook)\s*[:\-]?\s*)+/i, "");

  // Strip machine type codes before model name (e.g. '21MLCTO1WW ThinkPad T14 Gen 6')
  s = s.replace(/^[0-9A-Z]{4,10}\s+(ThinkPad|ThinkBook|IdeaPad|Legion|Yoga|EliteBook|ProBook|Latitude|Precision|XPS|ZBook)/i, "$1");

  // 2. Lenovo ThinkPad X1 (Carbon / Yoga / Nano / Extreme / Titanium Yoga / Fold / 2-in-1).
  // Generations come as "Gen 9" or, on older firmware, "6th" / "7th Gen": all become "Gen N".
  const tpX1 = s.match(/ThinkPad\s+(X1\s+(?:Carbon|Yoga|Nano|Extreme|Titanium\s+Yoga|Titanium|Fold(?:\s+\d+)?|2-in-1)(?:\s+(?:Gen\s+\d+|\d+(?:st|nd|rd|th)(?:\s+Gen)?))?)/i);
  if (tpX1) {
    return normalizeGeneration(tpX1[1]);
  }

  // 3. Lenovo ThinkPad Series (T14, T14s, T16, T480, L14, E14, P14s, P1, X13, X13 Yoga, Z13...)
  const tpMatch = s.match(/ThinkPad\s+([A-Z]\d+[a-z]?(?:\s+(?:Yoga|Nano|Extreme))?(?:\s+(?:Gen\s+\d+|\d+(?:st|nd|rd|th)(?:\s+Gen)?))?)/i);
  if (tpMatch) {
    return normalizeGeneration(tpMatch[1]);
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
  const hpMatch = s.match(/(Elite\s+Dragonfly|EliteBook|ProBook|ZBook|Dragonfly|Pavilion|Envy|Spectre|Omen|Victus)\s+([^,]+)/i);
  if (hpMatch) {
    const family = hpMatch[1];
    let rest = hpMatch[2];
    if (/^zbook$/i.test(family)) {
      rest = rest.replace(/(\d+(?:\.\d+)?)\s*(?:inch|"|-inch)/gi, "$1");
    } else {
      rest = rest.replace(/\d+(?:\.\d+)?\s*(?:inch|"|-inch)/gi, "");
    }
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
  s = s.replace(/\s+/g, " ").replace(/[\s\/]+$/, "").trim();
  if (/^(Generico|Generic)$/i.test(s)) return "--";

  if (s.length > 24) {
    return s.slice(0, 24).trim();
  }
  return s || "--";
}

// 1. UPDATE SYSTEM IDENTIFICATION & CPU
function updateSystemTab(sys) {
  if (!sys) return;
  lastSystemInfo = sys;

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
  if (quickModelEl) quickModelEl.innerText = formatModelWithBrand(cardModel, sys.vendor);
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
  lastBatteryInfo = bat;

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

  const hasBattery = bat.present !== false;
  const fmt = (v, unit) => (hasBattery && v) ? `${v} ${unit}` : "N/D";
  if (batHealth) batHealth.innerText = (bat.health_percent === null || bat.health_percent === undefined) ? "N/D" : `${bat.health_percent}%`;
  if (batDesign) batDesign.innerText = fmt(bat.design_wh, "Wh");
  if (batFull) batFull.innerText = fmt(bat.full_wh, "Wh");
  if (batCycles) batCycles.innerText = bat.cycle_count || "N/A";
  if (batVoltage) batVoltage.innerText = fmt(bat.voltage_v, "V");

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
          <strong>${(f.rpm === null || f.rpm === undefined) ? f.status : `${f.rpm} RPM (${f.status})`}</strong>
        </div>
      `).join("");
    } else {
      fansContainer.innerHTML = `<div class="sensor-item"><span>Ventilador</span><strong style="color: #94a3b8;">Sin lectura (la BIOS no la expone)</strong></div>`;
    }
  }

  const tempsContainer = document.getElementById("temps-list");
  if (tempsContainer) {
    if (thermal.temperatures && thermal.temperatures.length > 0) {
      tempsContainer.innerHTML = thermal.temperatures.map(t => `
        <div class="sensor-item">
          <span>${t.label}</span>
          <strong style="color: ${temperatureColor(t.temp_c)}">${Math.round(t.temp_c)} °C</strong>
        </div>
      `).join("");
    } else {
      tempsContainer.innerHTML = `<div class="sensor-item"><span>Temperatura</span><strong style="color: #94a3b8;">Sin sensor de temperatura expuesto</strong></div>`;
    }
  }

  updateThermalHealth(thermal.health);
}

// Color for a temperature reading: normal / high / at the cleaning threshold (95 °C).
function temperatureColor(tempC) {
  if (tempC >= 95) return "var(--danger-red)";
  if (tempC >= 85) return "var(--warning-amber)";
  return "var(--success-green)";
}

const THERMAL_LEVEL_TITLES = {
  ok: "Térmica correcta",
  watch: "Térmica: vigilar",
  clean: "Térmica: mantenimiento",
  unknown: "Térmica: sin datos"
};

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// General view: live throttling status and cleaning / thermal paste recommendation.
function updateThermalHealth(health) {
  const box = document.getElementById("thermal-health");
  if (!box || !health) return;

  // Short card: title + one line. Extra detail goes in the tooltip.
  const detail = [];
  if (health.tjmax_c) detail.push(`TjMax ${health.tjmax_c} °C`);
  detail.push(`Mantenimiento si ≥${Math.round(health.hot_threshold_c)} °C sostenido`);

  box.className = `thermal-health level-${health.level}`;
  box.style.display = "block";
  box.title = detail.join(" · ");
  box.innerHTML = `
    <div class="th-title"><span>${THERMAL_LEVEL_TITLES[health.level] || THERMAL_LEVEL_TITLES.unknown}</span></div>
    <div>${escapeHtml(health.message)}</div>
    ${health.prochot_note ? `<div class="th-reco">${escapeHtml(health.prochot_note)}</div>` : ""}
  `;
}

let _lastInternalStorageJson = "";
let _lastUsbStorageJson = "";

// 4. UPDATE STORAGE (INTERNAL SSD/HDD & USB EXTERNAL DRIVES)
function updateStorageTab(storage) {
  if (!storage) return;
  lastStorageInfo = Array.isArray(storage) ? { internal: storage.filter(s => !s.is_usb), usb: storage.filter(s => s.is_usb) } : storage;

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
          // Verdict comes from real SMART data; without it the drive is never shown as healthy.
          const smartText = escapeHtml(s.smart_status || 'SMART no disponible');
          const smartColor = { ok: 'var(--success-green)', warning: '#f59e0b', failed: '#f87171' }[s.smart_health] || '#94a3b8';
          const hasReadTests = Boolean(s.device_read_test && s.nvme_read_test);
          const devReadPassed = s.device_read_test === 'PASSED';
          const nvmeReadPassed = s.nvme_read_test === 'PASSED';
          // Opal only applies to SSDs; on HDDs a failed read is a plain read error.
          const opalApplicable = s.opal_applicable !== false;
          const readFailed = hasReadTests && (!devReadPassed || !nvmeReadPassed);
          const isOpal = opalApplicable && readFailed;

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
          if (readFailed && !opalApplicable) {
            opalAlertHtml = `
              <div class="card-spec-item" style="background: rgba(239, 68, 68, 0.08); border-left: 3px solid #ef4444; border-radius: 4px; padding: 0.45rem 0.6rem; margin-top: 0.35rem;">
                <div class="spec-value spec-value-detail" style="color: #f87171; font-weight: 700; font-size: 0.82rem;">
                  Error de lectura del disco
                </div>
              </div>
            `;
          } else if (isOpal) {
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
              <div class="spec-value spec-value-detail" style="color: ${smartColor}; font-weight: 700;">
                <span title="${escapeHtml(s.smart_detail || '')}">${smartText}</span>
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

  if (bt.present && (bt.hard_blocked || bt.soft_blocked)) {
    // Adapter found but its radio is blocked: not a pass.
    if (textEl) {
      textEl.innerText = bt.status || "Bloqueado";
      textEl.style.color = "var(--warning-amber)";
    }
    if (detailEl) detailEl.innerText = bt.name || "HCI0";
    unmarkCheckpassed("chk-bt", "Bluetooth");
  } else if (bt.present) {
    if (textEl) {
      textEl.innerText = bt.status || "Operativo y alimentado";
      textEl.style.color = bt.is_powered ? "var(--success-green)" : "var(--warning-amber)";
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

    // The Ethernet test only exists while there is a port (built in, or an external adapter plugged in).
    const showEth = eth.present || ethernetTestedPassed;
    const ethChip = document.getElementById("chk-eth");
    const ethCard = document.getElementById("card-ethernet");
    if (ethChip) ethChip.style.display = showEth ? "" : "none";
    if (ethCard) ethCard.style.display = showEth ? "" : "none";
    updateChecklistProgress();

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
    } else if (ethernetTestedPassed) {
      markCheckpassed("chk-eth", "ETHERNET");
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
  // Opal unlock only targets SSDs (no pen drives, HDDs or SD/eMMC).
  driveList = driveList.filter(s => s.opal_applicable !== false);

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
