/* ==============================================================================
   DIAGNOSTDONOR - REPORT (js/report.js)
   Builds a small self-contained HTML report (checklist, system data, stress test
   and technician comments) and sends it to a phone over Bluetooth.
   ============================================================================== */

let lastSystemInfo = null;
let lastBatteryInfo = null;
let lastStorageInfo = null;
let reportFileName = null;

const REPORT_ITEMS = [
  ["chk-cpu", "CPU", "cpu-test-status"],
  ["chk-ram", "RAM", "ram-test-status"],
  ["chk-ssd", "SSD", null],
  ["chk-screen", "Pantalla", "screen-test-status"],
  ["chk-hdmi", "HDMI", "hdmi-status-text"],
  ["chk-bt", "Bluetooth", "bt-status-text"],
  ["chk-keyboard", "Teclado", null],
  ["chk-touchpad", "Touchpad", null],
  ["chk-camera", "Cámara", "cam-res-info"],
  ["chk-audio", "Parlantes", "audio-status-text"],
  ["chk-mic", "Micrófono", "mic-status-text"],
  ["chk-wifi", "Wi-Fi", "wifi-auto-status"],
  ["chk-eth", "Ethernet", "eth-status-text"],
];

const REPORT_CSS = `
body{font:14px/1.45 system-ui,Segoe UI,Roboto,Arial,sans-serif;margin:0;background:#f4f5f9;color:#1b1f2a}
main{max-width:760px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0}h2{font-size:14px;margin:18px 0 6px;text-transform:uppercase;letter-spacing:.04em;color:#5b3fd0}
.sub{color:#5a6072;font-size:13px}
.box{background:#fff;border:1px solid #e0e3ec;border-radius:8px;padding:4px 12px}
table{width:100%;border-collapse:collapse}td,th{padding:7px 4px;border-bottom:1px solid #eceef5;text-align:left;vertical-align:top;font-size:13px}
tr:last-child td{border-bottom:0}th{color:#5a6072;font-weight:600}
.b{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:700;white-space:nowrap}
.ok{background:#dcf5e8;color:#0a7a45}.fail{background:#fde2e2;color:#b42318}.pending{background:#eceef5;color:#5a6072}.warn{background:#fff0d1;color:#9a5b00}
.sum{display:flex;gap:14px;margin-top:8px;font-weight:600}
pre{white-space:pre-wrap;margin:8px 0;font:inherit}
`;

function reportStatus(pill) {
  if (pill.classList.contains("passed")) return ["ok", "Aprobado"];
  if (pill.classList.contains("failed")) return ["fail", "Falló"];
  return ["pending", "Pendiente"];
}

function reportDetail(id, detailId) {
  if (id === "chk-keyboard") {
    const m = (document.getElementById(id)?.innerText || "").match(/\((\d+\/\d+)\)/);
    return m ? `${m[1]} teclas` : "";
  }
  const el = detailId ? document.getElementById(detailId) : null;
  const text = (el?.innerText || "").trim();
  if (id === "chk-ssd" && lastStorageInfo) {
    const d = (lastStorageInfo.internal || [])[0];
    return d ? `${d.model || d.device} · ${d.smart_status || ""}`.trim() : "";
  }
  return text.length > 90 ? text.slice(0, 87) + "…" : text;
}

function buildReportHtml(comments, stress) {
  const e = escapeHtml;
  const sys = lastSystemInfo || {};
  const bat = lastBatteryInfo || {};
  const pills = [...document.querySelectorAll(".chk-bar-grid .chk-pill")].filter(p => p.style.display !== "none");
  const byId = Object.fromEntries(pills.map(p => [p.id, p]));

  let ok = 0, fail = 0, pending = 0;
  const rows = REPORT_ITEMS.filter(([id]) => byId[id]).map(([id, label, detailId]) => {
    const [cls, text] = reportStatus(byId[id]);
    if (cls === "ok") ok++; else if (cls === "fail") fail++; else pending++;
    return `<tr><td>${label}</td><td><span class="b ${cls}">${text}</span></td><td>${e(reportDetail(id, detailId))}</td></tr>`;
  }).join("");

  const disks = ((lastStorageInfo && lastStorageInfo.internal) || []).map(d => `${d.model || d.device} (${d.size_gb} GB)`).join(", ");
  const info = [
    ["Modelo", sys.model], ["Serie", sys.serial], ["CPU", sys.cpu],
    ["RAM", sys.ram ? `${sys.ram.total_gb} GB` : ""],
    ["Batería", bat && bat.present !== false ? `Salud ${bat.health_percent ?? "N/D"}${bat.health_percent != null ? "%" : ""} · Ciclos ${bat.cycle_count ?? "N/A"}` : "Sin batería"],
    ["Discos", disks],
  ].filter(([, v]) => v).map(([k, v]) => `<tr><th>${k}</th><td>${e(v)}</td></tr>`).join("");

  let stressHtml = "";
  if (stress && stress.results && Object.keys(stress.results).length) {
    const names = { cpu: "CPU", ram: "RAM", ssd: "SSD", gpu: "GPU" };
    const srows = Object.entries(stress.results).map(([c, r]) => {
      const cls = r.passed === true ? "ok" : (r.passed === false ? "fail" : "warn");
      const txt = r.passed === true ? "OK" : (r.passed === false ? "Falló" : "Sin verificar");
      return `<tr><td>${names[c] || c}</td><td><span class="b ${cls}">${txt}</span></td><td>${e(r.message || "")}</td></tr>`;
    }).join("");
    const t = stress.max_temp_c;
    const tcls = t >= TEMP_HOT_C ? "fail" : (t >= TEMP_WARN_C ? "warn" : "ok");
    const th = stress.thermal_assessment || {};
    const avg = th.sustained_avg_c ?? th.avg_c;
    // Plain wording, no maintenance advice: what happened, not what to do about it.
    const verdict = { ok: "", watch: "Temperaturas altas", clean: "Sobrecalentamiento" }[th.level] || "";
    const thr = th.throttle && th.throttle.supported && th.throttle.events
      ? `Throttling térmico: ${th.throttle.events} ${th.throttle.events === 1 ? "evento" : "eventos"} (${(th.throttle.time_ms / 1000).toFixed(1)} s)` : "";
    stressHtml = `<h2>Prueba de estrés${stress.level ? " · " + e({ quick: "Rápida", medium: "Media", deep: "Profunda" }[stress.level] || "") : ""}</h2>
      <div class="box"><table>${srows}</table></div>
      <div class="sum"><span>Temp. máx: ${t == null ? "N/D" : `<span class="b ${tcls}">${Math.round(t)} °C</span>`}</span>
      <span>Prom.: ${avg == null ? "N/D" : Math.round(avg) + " °C"}</span>
      <span>Estado: ${stress.aborted ? "Interrumpido" : ((stress.failed_components || []).length ? "Con fallos" : "Superado")}</span></div>
      ${verdict || thr ? `<div class="sub" style="margin-top:6px">${[verdict ? `<b>${verdict}</b>` : "", thr].filter(Boolean).join(" · ")}</div>` : ""}`;
  }

  const note = (comments || "").trim();
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Informe ${e(sys.serial || "")}</title><style>${REPORT_CSS}</style></head><body><main>
<h1>Informe de diagnóstico</h1>
<div class="sub">${e(new Date().toLocaleString("es"))}</div>
<h2>Equipo</h2><div class="box"><table>${info}</table></div>
<h2>Checklist</h2>
<div class="sum"><span class="b ok">${ok} aprobadas</span><span class="b fail">${fail} con fallo</span><span class="b pending">${pending} pendientes</span></div>
<div class="box" style="margin-top:8px"><table>${rows}</table></div>
${stressHtml}
${note ? `<h2>Comentarios</h2><div class="box"><pre>${e(note)}</pre></div>` : ""}
</main></body></html>`;
}

// ── Modal ────────────────────────────────────────────────────────────────
function openReportModal() {
  reportFileName = null;
  const modal = document.getElementById("report-modal");
  if (modal) modal.style.display = "flex";
  setReportStatus("");
  const list = document.getElementById("report-devices");
  if (list) list.innerHTML = "";
  const prev = document.getElementById("report-preview");
  if (prev) prev.style.display = "none";
}

function closeReportModal() {
  const modal = document.getElementById("report-modal");
  if (modal) modal.style.display = "none";
}

function setReportStatus(text, kind) {
  const el = document.getElementById("report-status");
  if (!el) return;
  el.innerText = text;
  el.style.color = kind === "ok" ? "var(--success-green)" : (kind === "error" ? "var(--danger-red)" : "var(--text-muted)");
}

async function currentStressStatus() {
  try {
    const res = await fetch("/api/stress/status");
    const data = await res.json();
    return data && data.results && Object.keys(data.results).length ? data : null;
  } catch (e) {
    return null;
  }
}

async function getReportHtml() {
  const comments = document.getElementById("report-comments")?.value || "";
  return buildReportHtml(comments, await currentStressStatus());
}

async function toggleReportPreview() {
  const prev = document.getElementById("report-preview");
  if (!prev) return;
  if (prev.style.display === "block") { prev.style.display = "none"; return; }
  prev.srcdoc = await getReportHtml();
  prev.style.display = "block";
}

async function findPhonesForReport() {
  const list = document.getElementById("report-devices");
  const btn = document.getElementById("btn-report-send");
  if (btn) btn.disabled = true;
  if (list) list.innerHTML = "";
  try {
    setReportStatus("Preparando informe...");
    const saved = await (await apiPost("/api/report/save", { html: await getReportHtml(), serial: (lastSystemInfo && lastSystemInfo.serial) || "" })).json();
    if (!saved.success) throw new Error(saved.message || "No se pudo crear el informe");
    reportFileName = saved.name;

    setReportStatus("Buscando celulares (8 s)... activa Bluetooth en el celular y déjalo visible");
    const found = await (await apiPost("/api/bluetooth/scan", {})).json();
    if (!found.devices || found.devices.length === 0) {
      setReportStatus(found.message || "No se encontró ningún dispositivo. Reintenta.", "error");
      return;
    }
    setReportStatus("Elige el celular:");
    list.innerHTML = found.devices.map(d =>
      `<button class="btn btn-secondary btn-sm report-device" data-addr="${escapeHtml(d.address)}">${d.phone ? "📱 " : ""}${escapeHtml(d.name)}</button>`).join("");
    list.querySelectorAll(".report-device").forEach(b => b.addEventListener("click", () => sendReportTo(b.dataset.addr, b.innerText)));
  } catch (err) {
    setReportStatus(`Error: ${err.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function sendReportTo(address, label) {
  const list = document.getElementById("report-devices");
  list?.querySelectorAll("button").forEach(b => { b.disabled = true; });
  setReportStatus(`Enviando a ${label.replace("📱 ", "")}... acepta el archivo en el celular`);
  try {
    const res = await (await apiPost("/api/bluetooth/send", { address, name: reportFileName })).json();
    setReportStatus(res.success ? "Informe enviado ✓" : (res.message || "No se pudo enviar"), res.success ? "ok" : "error");
  } catch (err) {
    setReportStatus(`Error: ${err.message}`, "error");
  } finally {
    list?.querySelectorAll("button").forEach(b => { b.disabled = false; });
  }
}
