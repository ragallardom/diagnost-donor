/* ==============================================================================
   DIAGNOSTDONOR - HARDWARE STRESS TESTING MODULE (js/stress.js)
   - Real-time CPU, RAM, SSD, and WebGL GPU telemetry & load coordination.
   - Dynamic 3D WebGL Fragment Shader Raymarching / Fractal loop.
   - Comprehensive final health & thermal report generator.
   ============================================================================== */

let currentStressLevel = "quick";
let stressPollingInterval = null;
let gpuStressAnimId = null;
let gpuStressStartTime = null;
let gpuStressFrameCount = 0;

function openStressModal() {
  const modal = document.getElementById("stress-modal");
  if (modal) modal.style.display = "flex";

  // Check if test is currently running in backend
  pollStressStatus();
}

function closeStressModal() {
  const modal = document.getElementById("stress-modal");
  if (modal) modal.style.display = "none";
}

function selectStressLevel(level) {
  currentStressLevel = level;
  const levels = ["quick", "medium", "deep"];
  levels.forEach(lvl => {
    const btn = document.getElementById(`btn-lvl-${lvl}`);
    if (btn) {
      if (lvl === level) btn.classList.add("active");
      else btn.classList.remove("active");
    }
  });
}

function setStressUiState(isRunning) {
  const startBtn = document.getElementById("btn-start-stress");
  const stopBtn = document.getElementById("btn-stop-stress");
  const configBox = document.getElementById("stress-config-container");
  const livePanel = document.getElementById("stress-live-panel");
  const reportPanel = document.getElementById("stress-results-report");

  if (isRunning) {
    if (startBtn) startBtn.style.display = "none";
    if (stopBtn) stopBtn.style.display = "inline-block";
    if (configBox) configBox.style.display = "none";
    if (livePanel) livePanel.style.display = "block";
    if (reportPanel) reportPanel.style.display = "none";
  } else {
    if (startBtn) startBtn.style.display = "inline-block";
    if (stopBtn) stopBtn.style.display = "none";
    if (configBox) configBox.style.display = "block";
  }
}

function startStressPolling() {
  if (stressPollingInterval) clearInterval(stressPollingInterval);
  stressPollingInterval = setInterval(pollStressStatus, 1000);
  pollStressStatus();
}

function stopStressPolling() {
  if (stressPollingInterval) {
    clearInterval(stressPollingInterval);
    stressPollingInterval = null;
  }
}

async function pollStressStatus() {
  try {
    const res = await fetch("/api/stress/status");
    if (!res.ok) return;
    const data = await res.json();

    const badge = document.getElementById("stress-current-badge");
    const timeDisplay = document.getElementById("stress-time-display");
    const tempVal = document.getElementById("stress-temp-val");
    const maxTempVal = document.getElementById("stress-max-temp-val");
    const fill = document.getElementById("stress-progress-fill");
    const logConsole = document.getElementById("stress-log-console");

    const fmtTemp = v => (v === null || v === undefined) ? "N/D" : `${Math.round(Number(v))} °C`;

    if (tempVal) tempVal.innerText = fmtTemp(data.current_temp_c);
    if (maxTempVal) maxTempVal.innerText = fmtTemp(data.max_temp_c);

    if (data.is_running) {
      setStressUiState(true);

      const compNames = { cpu: "CPU", ram: "RAM", ssd: "SSD", gpu: "GPU" };
      if (badge) badge.innerText = compNames[data.current_component] || "Ejecutando...";

      const elMin = String(Math.floor(data.elapsed_sec / 60)).padStart(2, '0');
      const elSec = String(data.elapsed_sec % 60).padStart(2, '0');
      const totMin = String(Math.floor(data.total_duration_sec / 60)).padStart(2, '0');
      const totSec = String(data.total_duration_sec % 60).padStart(2, '0');
      if (timeDisplay) timeDisplay.innerText = `${elMin}:${elSec} / ${totMin}:${totSec}`;

      if (fill) fill.style.width = `${data.progress_percent}%`;

      // Coordinate WebGL 3D Shader load during GPU phase
      if (data.current_component === "gpu") {
        startGpu3DStress();
      } else {
        stopGpu3DStress();
      }

      // Populate live logs
      if (logConsole && data.logs && data.logs.length > 0) {
        logConsole.innerHTML = data.logs.map(l => {
          let colClass = "info";
          if (l.type === "success") colClass = "success";
          if (l.type === "warning") colClass = "warning";
          if (l.type === "error") colClass = "error";
          return `<div class="log-line ${colClass}"><span class="log-time">[${l.time}]</span> ${l.message}</div>`;
        }).join("");
        logConsole.scrollTop = logConsole.scrollHeight;
      }
    } else {
      stopGpu3DStress();

      if (data.results && Object.keys(data.results).length > 0) {
        renderStressFinalReport(data);
        stopStressPolling();
        setStressUiState(false);
      }
    }
  } catch (e) {
    console.warn("Error consultando estado de estrés:", e);
  }
}

function renderStressFinalReport(data) {
  const reportPanel = document.getElementById("stress-results-report");
  const livePanel = document.getElementById("stress-live-panel");
  if (!reportPanel) return;

  if (livePanel) livePanel.style.display = "none";
  reportPanel.style.display = "block";

  const results = data.results || {};
  let itemsHtml = "";

  const compIcons = {
    cpu: "Procesador (CPU)",
    ram: "Memoria RAM",
    ssd: "Almacenamiento (SSD)",
    gpu: "Gráficos (GPU 3D)"
  };

  for (const [comp, info] of Object.entries(results)) {
    const isOk = info.passed === true;
    const isSkipped = info.passed === null || info.passed === undefined;
    const title = compIcons[comp] || comp.toUpperCase();
    itemsHtml += `
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 0.75rem; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; margin-bottom: 0.4rem;">
        <div>
          <strong style="color: #ffffff; font-size: 0.85rem;">${title}</strong>
          <div style="font-size: 0.75rem; color: #94a3b8;">${escapeHtml(info.message || 'Prueba finalizada')}</div>
        </div>
        <div>
          <span class="badge-purple" style="background: ${isSkipped ? 'rgba(245,158,11,0.2)' : (isOk ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)')}; border-color: ${isSkipped ? '#f59e0b' : (isOk ? 'var(--success-green)' : 'var(--danger-red)')}; color: ${isSkipped ? '#fcd34d' : (isOk ? 'var(--success-green)' : '#fca5a5')}; font-size: 0.75rem;">
            ${isSkipped ? 'SIN VERIFICAR' : (isOk ? 'ESTABLE' : 'FALLÓ')}
          </span>
        </div>
      </div>
    `;
  }

  reportPanel.innerHTML = `
    <h4 style="color: #ffffff; margin-bottom: 0.6rem; font-size: 0.95rem; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 0.4rem;">
      Informe de Estabilidad y Estrés Térmico
    </h4>
    <div style="margin-top: 0.5rem;">
      ${itemsHtml || '<p style="color: #94a3b8; font-size: 0.8rem;">No se completaron componentes.</p>'}
    </div>
    <div style="margin-top: 0.75rem; font-size: 0.8rem; color: #c4b5fd; display: flex; justify-content: space-between;">
      <span>Temperatura máxima alcanzada: <strong>${data.max_temp_c === null || data.max_temp_c === undefined ? 'N/D' : Math.round(Number(data.max_temp_c)) + ' °C'}</strong></span>
      <span>Estado: <strong>${data.aborted ? 'Interrumpido' : ((data.failed_components || []).length ? 'Con fallos' : 'Superado')}</strong></span>
    </div>
    ${renderThermalAssessment(data.thermal_assessment)}
  `;
}

// Cooling verdict from the CPU phase: cleaning / thermal paste recommendation.
function renderThermalAssessment(a) {
  if (!a) return "";
  const titles = {
    ok: "Enfriamiento correcto",
    watch: "Temperatura elevada: vigilar",
    clean: "Mantenimiento recomendado: limpieza y cambio de pasta térmica",
    unknown: "Evaluación térmica no disponible"
  };
  const metrics = [];
  if (a.sustained_avg_c !== null && a.sustained_avg_c !== undefined) metrics.push(`Promedio sostenido: <strong>${a.sustained_avg_c} °C</strong>`);
  if (a.sustained_hot_pct !== null && a.sustained_hot_pct !== undefined) metrics.push(`Tiempo ≥${Math.round(a.hot_threshold_c)} °C: <strong>${a.sustained_hot_pct}%</strong>`);
  if (a.throttle && a.throttle.supported) metrics.push(`Throttling térmico: <strong>${a.throttle.events ? `${a.throttle.events} eventos (${(a.throttle.time_ms / 1000).toFixed(1)} s)` : 'No'}</strong>`);
  if (a.tjmax_c) metrics.push(`TjMax: <strong>${a.tjmax_c} °C</strong>`);
  if (a.avg_mhz) metrics.push(`Frecuencia sostenida: <strong>${a.avg_mhz} MHz</strong>${a.base_mhz ? ` (base ${a.base_mhz})` : ''}`);

  return `
    <div class="thermal-health level-${a.level}" style="margin-top: 0.75rem;">
      <div class="th-title"><span>${titles[a.level] || titles.unknown}</span>${a.preliminary ? '<span style="font-weight: 500; color: #94a3b8;">Preliminar</span>' : ''}</div>
      ${a.recommendation ? `<div class="th-reco">${escapeHtml(a.recommendation)}</div>` : ''}
      <ul>${(a.reasons || []).map(r => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
      ${metrics.length ? `<div class="th-meta">${metrics.join(" · ")}</div>` : ''}
    </div>
  `;
}

// ─────────────────────────────────────────────────────────────────
// WEBGL 3D RAYMARCHING SHADER STRESS ENGINE (GPU)
// ─────────────────────────────────────────────────────────────────
// The canvas is shown small but rendered at 1280x720, and several full-screen
// passes are drawn per frame, so the GPU is loaded well beyond one vsync frame.
// Stats (frames, FPS, context loss, shader errors) are posted to the backend
// every few seconds, which turns them into the GPU verdict.
const GPU_RENDER_W = 1280;
const GPU_RENDER_H = 720;
const GPU_DRAWS_PER_FRAME = 4;
const GPU_REPORT_INTERVAL_MS = 2000;

let gpuStats = null;

function newGpuStats() {
  return { frames: 0, avg_fps: 0, min_fps: 0, context_lost: false, error: "", renderer: "", _start: performance.now(), _minFps: Infinity };
}

function postGpuReport() {
  if (!gpuStats) return;
  const s = gpuStats;
  const elapsed = Math.max(1, performance.now() - s._start);
  s.avg_fps = (s.frames * 1000) / elapsed;
  s.min_fps = s._minFps === Infinity ? 0 : s._minFps;
  const { _start, _minFps, ...payload } = s;
  apiPost("/api/stress/gpu-report", payload).catch(() => {});
}

function startGpu3DStress() {
  const container = document.getElementById("stress-gpu-canvas-container");
  const canvas = document.getElementById("stress-webgl-canvas");
  if (!container || !canvas) return;

  container.style.display = "block";
  if (gpuStressAnimId) return; // already active

  canvas.width = GPU_RENDER_W;
  canvas.height = GPU_RENDER_H;
  gpuStats = newGpuStats();

  const gl = canvas.getContext("webgl", { powerPreference: "high-performance" }) || canvas.getContext("experimental-webgl");
  if (!gl) {
    document.getElementById("stress-gpu-fps").innerText = "WebGL no soportado";
    gpuStats.error = "WebGL no soportado por el navegador";
    postGpuReport();
    return;
  }
  const dbg = gl.getExtension("WEBGL_debug_renderer_info");
  if (dbg) gpuStats.renderer = String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) || "");

  canvas.addEventListener("webglcontextlost", (e) => {
    e.preventDefault();
    if (gpuStats) gpuStats.context_lost = true;
    postGpuReport();
  }, { once: true });

  const vsSource = `
    attribute vec2 position;
    void main() {
      gl_Position = vec4(position, 0.0, 1.0);
    }
  `;

  // Heavy procedural raymarching shader with a per-pixel normal + soft shadow
  // march to stress GPU ALUs / texture-less shading throughput.
  const fsSource = `
    precision highp float;
    uniform float u_time;
    uniform vec2 u_resolution;

    float map(vec3 p) {
      vec3 q = fract(p) * 2.0 - 1.0;
      float d = length(q) - 0.28;
      float w = length(fract(p * 2.0 + 0.5) * 2.0 - 1.0) - 0.12;
      return min(d, w);
    }

    vec3 normal(vec3 p) {
      vec2 e = vec2(0.002, 0.0);
      return normalize(vec3(
        map(p + e.xyy) - map(p - e.xyy),
        map(p + e.yxy) - map(p - e.yxy),
        map(p + e.yyx) - map(p - e.yyx)));
    }

    void main() {
      vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution.xy) / u_resolution.y;
      vec3 ro = vec3(0.0, 0.0, -u_time * 0.8);
      vec3 rd = normalize(vec3(uv, -1.0));

      float t = 0.0;
      for (int i = 0; i < 128; i++) {
        vec3 p = ro + rd * t;
        float d = map(p);
        t += d * 0.5;
        if (d < 0.002 || t > 24.0) break;
      }

      vec3 p = ro + rd * t;
      vec3 n = normal(p);
      vec3 l = normalize(vec3(0.6, 0.7, -0.4));
      float sh = 1.0;
      float st = 0.05;
      for (int j = 0; j < 32; j++) {
        float h = map(p + l * st);
        sh = min(sh, 8.0 * h / st);
        st += clamp(h, 0.02, 0.4);
        if (sh < 0.01 || st > 6.0) break;
      }
      float diff = max(dot(n, l), 0.0) * clamp(sh, 0.0, 1.0);

      vec3 col = vec3(0.08, 0.02, 0.15) + vec3(0.65, 0.33, 0.96) * (1.0 / (1.0 + t * t * 0.1)) * (0.4 + diff);
      gl_FragColor = vec4(col, 1.0);
    }
  `;

  function createShader(gl, type, source) {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, source);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      gpuStats.error = "Error compilando shader: " + (gl.getShaderInfoLog(sh) || "").slice(0, 120);
    }
    return sh;
  }

  const vs = createShader(gl, gl.VERTEX_SHADER, vsSource);
  const fs = createShader(gl, gl.FRAGMENT_SHADER, fsSource);
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS) && !gpuStats.error) {
    gpuStats.error = "Error enlazando shader: " + (gl.getProgramInfoLog(program) || "").slice(0, 120);
  }
  if (gpuStats.error) {
    postGpuReport();
    return;
  }
  gl.useProgram(program);

  const posBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, posBuffer);
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
  gpuStats._start = gpuStressStartTime;
  gpuStressFrameCount = 0;
  let lastFpsUpdate = performance.now();
  let lastReport = lastFpsUpdate;

  function renderLoop(now) {
    if (gl.isContextLost()) {
      gpuStats.context_lost = true;
      postGpuReport();
      return;
    }
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(resLoc, canvas.width, canvas.height);
    for (let k = 0; k < GPU_DRAWS_PER_FRAME; k++) {
      gl.uniform1f(timeLoc, (now - gpuStressStartTime) * 0.001 + k * 0.37);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    }
    gpuStressFrameCount++;
    gpuStats.frames++;

    if (now - lastFpsUpdate >= 500) {
      const fps = Math.round((gpuStressFrameCount * 1000) / (now - lastFpsUpdate));
      const fpsEl = document.getElementById("stress-gpu-fps");
      if (fpsEl) fpsEl.innerText = `GPU 3D Shader: ${fps} FPS (${GPU_RENDER_W}x${GPU_RENDER_H} x${GPU_DRAWS_PER_FRAME})`;
      // Ignore the first second (shader warm-up) for the minimum.
      if (now - gpuStressStartTime > 1000 && fps < gpuStats._minFps) gpuStats._minFps = fps;
      gpuStressFrameCount = 0;
      lastFpsUpdate = now;
    }
    if (now - lastReport >= GPU_REPORT_INTERVAL_MS) {
      lastReport = now;
      postGpuReport();
    }

    gpuStressAnimId = requestAnimationFrame(renderLoop);
  }

  gpuStressAnimId = requestAnimationFrame(renderLoop);
}

function stopGpu3DStress() {
  if (gpuStressAnimId) {
    cancelAnimationFrame(gpuStressAnimId);
    gpuStressAnimId = null;
    postGpuReport();
  }
  const container = document.getElementById("stress-gpu-canvas-container");
  if (container) container.style.display = "none";
}
