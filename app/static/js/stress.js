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

    const curTempInt = Math.round(Number(data.current_temp_c) || 0);
    const maxTempInt = Math.round(Number(data.max_temp_c) || 0);

    if (tempVal) tempVal.innerText = `${curTempInt} °C`;
    if (maxTempVal) maxTempVal.innerText = `${maxTempInt} °C`;

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
    const isOk = info.passed;
    const title = compIcons[comp] || comp.toUpperCase();
    itemsHtml += `
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 0.75rem; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; margin-bottom: 0.4rem;">
        <div>
          <strong style="color: #ffffff; font-size: 0.85rem;">${title}</strong>
          <div style="font-size: 0.75rem; color: #94a3b8;">${info.message || 'Prueba finalizada'}</div>
        </div>
        <div>
          <span class="badge-purple" style="background: ${isOk ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)'}; border-color: ${isOk ? 'var(--success-green)' : 'var(--danger-red)'}; color: ${isOk ? 'var(--success-green)' : '#fca5a5'}; font-size: 0.75rem;">
            ${isOk ? 'ESTABLE' : 'FALLÓ'}
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
      <span>Temperatura máxima alcanzada: <strong>${Math.round(Number(data.max_temp_c) || 0)} °C</strong></span>
      <span>Estado: <strong>${data.aborted ? 'Interrumpido' : 'Superado'}</strong></span>
    </div>
  `;
}

// ─────────────────────────────────────────────────────────────────
// WEBGL 3D RAYMARCHING SHADER STRESS ENGINE (GPU)
// ─────────────────────────────────────────────────────────────────
function startGpu3DStress() {
  const container = document.getElementById("stress-gpu-canvas-container");
  const canvas = document.getElementById("stress-webgl-canvas");
  if (!container || !canvas) return;

  container.style.display = "block";
  if (gpuStressAnimId) return; // already active

  const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
  if (!gl) {
    document.getElementById("stress-gpu-fps").innerText = "WebGL no soportado";
    return;
  }

  const vsSource = `
    attribute vec2 position;
    void main() {
      gl_Position = vec4(position, 0.0, 1.0);
    }
  `;

  // Heavy procedural raymarching volumetric shader to stress GPU ALUs
  const fsSource = `
    precision mediump float;
    uniform float u_time;
    uniform vec2 u_resolution;

    float map(vec3 p) {
      vec3 q = fract(p) * 2.0 - 1.0;
      return length(q) - 0.28;
    }

    void main() {
      vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution.xy) / u_resolution.y;
      vec3 ro = vec3(0.0, 0.0, -u_time * 0.8);
      vec3 rd = normalize(vec3(uv, -1.0));
      
      float t = 0.0;
      for (int i = 0; i < 48; i++) {
        vec3 p = ro + rd * t;
        float d = map(p);
        t += d * 0.5;
        if (d < 0.002 || t > 18.0) break;
      }
      
      vec3 col = vec3(0.08, 0.02, 0.15) + vec3(0.65, 0.33, 0.96) * (1.0 / (1.0 + t * t * 0.1));
      gl_FragColor = vec4(col, 1.0);
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
      const fpsEl = document.getElementById("stress-gpu-fps");
      if (fpsEl) fpsEl.innerText = `GPU 3D Shader: ${fps} FPS`;
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
