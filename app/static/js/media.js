/* ==============================================================================
   DIAGNOSTDONOR - MULTIMEDIA DIAGNOSTIC MODULE (js/media.js)
   - HD Camera with real-time video resolution detector and auto-pass.
   - Stereo Speaker testing via WebAudio API logarithmic frequency sweep (100-3500 Hz).
   - Microphone live VU Meter, auto-pass, and 3-second recording/playback loop.
   ============================================================================== */

let audioContext = null;
let cameraStream = null;
let micStream = null;
let micAnalyser = null;
let micAnimId = null;

let audioLeftTested = false;
let audioRightTested = false;
let audioBothTested = false;

// ─────────────────────────────────────────────────────────────────
// 1. HD CAMERA PIPELINE
// ─────────────────────────────────────────────────────────────────
async function startCamera() {
  const video = document.getElementById("camera-video");
  const overlay = document.getElementById("cam-overlay");
  const resInfo = document.getElementById("cam-res-info");
  if (!video || !overlay || !resInfo) return;

  try {
    if (cameraStream) {
      cameraStream.getTracks().forEach(t => t.stop());
      cameraStream = null;
    }

    overlay.style.display = "block";
    overlay.innerText = "Iniciando cámara...";

    const constraints = {
      video: {
        width: { ideal: 1920, min: 640 },
        height: { ideal: 1080, min: 480 },
        facingMode: "user"
      },
      audio: false
    };

    try {
      cameraStream = await navigator.mediaDevices.getUserMedia(constraints);
    } catch (e1) {
      console.warn("Fallo con resolución ideal, reintentando básico:", e1);
      const constraints2 = { video: true, audio: false };
      cameraStream = await navigator.mediaDevices.getUserMedia(constraints2);
    }

    const setCamPassed = () => {
      if (video.videoWidth && video.videoHeight) {
        resInfo.innerText = `Res: ${video.videoWidth}x${video.videoHeight}`;
        const container = video.closest(".camera-preview-container");
        if (container) {
          container.style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`;
        }
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
      overlay.innerText = "No se detectó cámara web integrada.";
    } else if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
      overlay.innerText = "Permiso de cámara bloqueado.";
    } else {
      overlay.innerText = `Error: ${err.message || 'Sin señal de video'}`;
    }
    resInfo.innerText = "Res: --";
    unmarkCheckpassed("chk-camera", "Cámara");
  }
}

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach(t => t.stop());
    cameraStream = null;
  }
  const video = document.getElementById("camera-video");
  if (video) {
    video.srcObject = null;
    const container = video.closest(".camera-preview-container");
    if (container) container.style.aspectRatio = "16 / 9";
  }
  const overlay = document.getElementById("cam-overlay");
  if (overlay) {
    overlay.style.display = "block";
    overlay.innerText = "Cámara inactiva";
  }
  const resInfo = document.getElementById("cam-res-info");
  if (resInfo) resInfo.innerText = "Res: --";
}

// ─────────────────────────────────────────────────────────────────
// 2. SPEAKER STEREO & FREQUENCY SWEEP (100 Hz - 3500 Hz)
// ─────────────────────────────────────────────────────────────────
async function updateSpeakerVolume(val) {
  const volVal = document.getElementById("speaker-vol-val");
  if (volVal) volVal.innerText = `${val}%`;
  try {
    await apiPost("/api/volume", { volume: parseInt(val) });
  } catch (e) {
    console.warn("No se pudo fijar volumen en ALSA:", e);
  }
}

async function playFrequencySweep(channel) {
  const statusEl = document.getElementById("audio-status-text");
  const btnId = channel === "left" ? "btn-audio-left" : (channel === "right" ? "btn-audio-right" : "btn-audio-both");
  const btn = document.getElementById(btnId);

  try {
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioContext.state === "suspended") {
      await audioContext.resume().catch(() => { });
    }

    const duration = 2.5; // seconds
    const startFreq = 100;
    const endFreq = 3500;
    const now = audioContext.currentTime;

    const channelNames = {
      left: "izquierdo (canal L)",
      right: "derecho (canal R)",
      both: "estéreo (ambos canales)"
    };

    if (btn) {
      btn.style.borderColor = "#f59e0b";
      btn.style.color = "#f59e0b";
      btn.innerText = "Reproduciendo...";
    }

    if (statusEl) {
      statusEl.innerText = `Reproduciendo barrido ${channelNames[channel] || channel} (100 Hz - 3500 Hz)...`;
      statusEl.style.color = "#f59e0b";
    }

    const osc = audioContext.createOscillator();
    const gain = audioContext.createGain();

    osc.type = "sine";
    osc.frequency.setValueAtTime(startFreq, now);
    osc.frequency.exponentialRampToValueAtTime(endFreq, now + duration);

    gain.gain.setValueAtTime(0.01, now);
    gain.gain.linearRampToValueAtTime(0.4, now + 0.15);
    gain.gain.setValueAtTime(0.4, now + duration - 0.2);
    gain.gain.linearRampToValueAtTime(0.001, now + duration);

    if (audioContext.createStereoPanner) {
      const panner = audioContext.createStereoPanner();
      if (channel === "left") panner.pan.setValueAtTime(-1, now);
      else if (channel === "right") panner.pan.setValueAtTime(1, now);
      else panner.pan.setValueAtTime(0, now);

      osc.connect(gain);
      gain.connect(panner);
      panner.connect(audioContext.destination);
    } else {
      osc.connect(gain);
      gain.connect(audioContext.destination);
    }

    osc.start(now);
    osc.stop(now + duration);

    setTimeout(() => {
      if (channel === "left") {
        audioLeftTested = true;
        if (btn) {
          btn.innerText = "1. Barrido izquierda";
          btn.style.backgroundColor = "rgba(16, 185, 129, 0.18)";
          btn.style.borderColor = "var(--success-green)";
          btn.style.color = "var(--success-green)";
        }
      } else if (channel === "right") {
        audioRightTested = true;
        if (btn) {
          btn.innerText = "2. Barrido derecha";
          btn.style.backgroundColor = "rgba(16, 185, 129, 0.18)";
          btn.style.borderColor = "var(--success-green)";
          btn.style.color = "var(--success-green)";
        }
      } else if (channel === "both") {
        audioBothTested = true;
        if (btn) {
          btn.innerText = "3. Barrido ambos";
          btn.style.backgroundColor = "rgba(16, 185, 129, 0.18)";
          btn.style.borderColor = "var(--success-green)";
          btn.style.color = "var(--success-green)";
        }
      }

      const count = (audioLeftTested ? 1 : 0) + (audioRightTested ? 1 : 0) + (audioBothTested ? 1 : 0);

      if (count === 3) {
        if (statusEl) {
          statusEl.innerText = "Prueba completada (3/3): Parlantes estéreo 100% operativos";
          statusEl.style.color = "var(--success-green)";
        }
        markCheckpassed("chk-audio", "PARLANTES");
        markCheckpassed("chk-speakers", "PARLANTES");
      } else {
        if (statusEl) {
          statusEl.innerText = `Barrido finalizado. Progreso: ${count}/3 canales probados`;
          statusEl.style.color = "var(--text-main)";
        }
        unmarkCheckpassed("chk-audio", `Parlantes (${count}/3)`);
        unmarkCheckpassed("chk-speakers", `Parlantes (${count}/3)`);
      }
    }, duration * 1000);

  } catch (err) {
    console.error("Error reproduciendo barrido de audio:", err);
    if (statusEl) {
      statusEl.innerText = `Error: ${err.message}`;
      statusEl.style.color = "var(--danger-red)";
    }
  }
}

// ─────────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────
// 3. MICROPHONE VU METER & RECORDING
// ─────────────────────────────────────────────────────────────────
let micSilentGain = null;

async function startMicTest() {
  const statusEl = document.getElementById("mic-status-text");
  if (statusEl) {
    statusEl.innerText = "Iniciando micrófono...";
    statusEl.style.color = "var(--text-main)";
  }

  try {
    if (micStream) {
      micStream.getTracks().forEach(t => t.stop());
      micStream = null;
    }

    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioContext.state === "suspended") {
      await audioContext.resume().catch(() => { });
    }

    // Standard hardware audio capture
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (e1) {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    }

    const source = audioContext.createMediaStreamSource(micStream);
    micAnalyser = audioContext.createAnalyser();
    micAnalyser.fftSize = 256;
    micAnalyser.smoothingTimeConstant = 0.75;
    source.connect(micAnalyser);

    // Keep audio graph alive in Chromium by connecting to a muted gain node
    if (!micSilentGain) {
      micSilentGain = audioContext.createGain();
      micSilentGain.gain.value = 0.0;
      micSilentGain.connect(audioContext.destination);
    }
    source.connect(micSilentGain);

    if (statusEl) {
      statusEl.innerText = "Micrófono activo (Habla o produce sonido para probar)";
      statusEl.style.color = "var(--success-green)";
    }

    const bufferLength = micAnalyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    const vuFill = document.getElementById("mic-vu-bar") || document.getElementById("mic-vu-fill");
    let smoothedMeter = 0;

    function updateVu() {
      if (!micAnalyser) return;
      micAnalyser.getByteFrequencyData(dataArray);

      // 1. Calculate average frequency energy across human vocal spectrum
      let sum = 0;
      for (let i = 0; i < bufferLength; i++) {
        sum += dataArray[i];
      }
      const avgEnergy = sum / bufferLength;

      // 2. Noise Gate: in silence, avgEnergy is 0-5. Normal speaking is 20-80.
      const NOISE_GATE = 5;
      let targetPercent = 0;

      if (avgEnergy > NOISE_GATE) {
        // Scaled to 0-100%
        const normalized = (avgEnergy - NOISE_GATE) / (75 - NOISE_GATE);
        targetPercent = Math.min(100, Math.max(0, Math.round(normalized * 100)));
      }

      // 3. Fast attack, smooth visual decay
      if (targetPercent > smoothedMeter) {
        smoothedMeter = targetPercent;
      } else {
        smoothedMeter = Math.max(0, smoothedMeter - 4);
      }

      if (vuFill) {
        vuFill.style.width = `${smoothedMeter}%`;
      }

      if (smoothedMeter >= 15) {
        markCheckpassed("chk-mic", "MICRÓFONO");
      }

      micAnimId = requestAnimationFrame(updateVu);
    }

    if (micAnimId) cancelAnimationFrame(micAnimId);
    updateVu();
  } catch (err) {
    if (statusEl) {
      statusEl.innerText = `Error: ${err.message || 'Sin acceso al micrófono'}`;
      statusEl.style.color = "var(--danger-red)";
    }
    unmarkCheckpassed("chk-mic", "Micrófono");
  }
}

function stopMicTest() {
  if (micAnimId) {
    cancelAnimationFrame(micAnimId);
    micAnimId = null;
  }
  if (micStream) {
    micStream.getTracks().forEach(t => t.stop());
    micStream = null;
  }
  const vuFill = document.getElementById("mic-vu-bar") || document.getElementById("mic-vu-fill");
  if (vuFill) vuFill.style.width = "0%";
  const statusEl = document.getElementById("mic-status-text");
  if (statusEl) {
    statusEl.innerText = "Micrófono inactivo";
    statusEl.style.color = "var(--text-muted)";
  }
}

let micMediaRecorder = null;
let micAudioChunks = [];
let micRecTimer = null;

async function recordAndPlayMic() {
  const statusEl = document.getElementById("mic-status-text");
  const btn = document.getElementById("btn-rec-loop") || document.getElementById("btn-mic-rec");

  try {
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioContext.state === "suspended") {
      await audioContext.resume().catch(() => { });
    }

    if (!micStream || !micStream.active) {
      await startMicTest();
    }

    if (!micStream || !micStream.active) {
      throw new Error("No se pudo iniciar el stream de micrófono");
    }

    if (btn) btn.disabled = true;
    let secondsLeft = 3;
    if (btn) btn.innerText = `Grabando (${secondsLeft}s)...`;
    if (statusEl) {
      statusEl.innerText = "Grabando audio...";
      statusEl.style.color = "#f59e0b";
    }

    micAudioChunks = [];

    // Select optimal supported audio container
    let options = {};
    if (typeof MediaRecorder !== 'undefined' && typeof MediaRecorder.isTypeSupported === 'function') {
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
        options = { mimeType: 'audio/webm;codecs=opus' };
      } else if (MediaRecorder.isTypeSupported('audio/webm')) {
        options = { mimeType: 'audio/webm' };
      } else if (MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')) {
        options = { mimeType: 'audio/ogg;codecs=opus' };
      }
    }

    micMediaRecorder = new MediaRecorder(micStream, options);

    micMediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        micAudioChunks.push(e.data);
      }
    };

    micMediaRecorder.onstop = async () => {
      if (micRecTimer) clearInterval(micRecTimer);

      if (micAudioChunks.length === 0) {
        if (btn) {
          btn.disabled = false;
          btn.innerText = "Grabar 3s y escuchar";
        }
        if (statusEl) {
          statusEl.innerText = "Error: no se capturaron datos de audio";
          statusEl.style.color = "var(--danger-red)";
        }
        unmarkCheckpassed("chk-mic", "Micrófono");
        return;
      }

      const mime = (options && options.mimeType) ? options.mimeType : 'audio/webm';
      const audioBlob = new Blob(micAudioChunks, { type: mime });

      // Decode audio and calculate peak and RMS to detect silence / VM dummy device
      let isSilence = false;
      try {
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
        console.warn("Análisis de buffer de audio omitido:", decErr);
      }

      if (isSilence) {
        if (btn) {
          btn.disabled = false;
          btn.innerText = "Grabar 3s y escuchar";
        }
        if (statusEl) {
          statusEl.innerText = "No se detectó audio (micrófono mudo o sin señal)";
          statusEl.style.color = "var(--danger-red)";
        }
        unmarkCheckpassed("chk-mic", "Micrófono");
        return;
      }

      if (btn) btn.innerText = "Reproduciendo...";
      if (statusEl) {
        statusEl.innerText = "Reproduciendo audio grabado...";
        statusEl.style.color = "var(--success-green)";
      }

      const audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(audioUrl);
      audio.volume = 1.0;

      audio.onended = () => {
        if (btn) {
          btn.disabled = false;
          btn.innerText = "Grabar 3s y escuchar";
        }
        if (statusEl) {
          statusEl.innerText = "Prueba de audio completada";
          statusEl.style.color = "var(--success-green)";
        }
        markCheckpassed("chk-mic", "MICRÓFONO");
        URL.revokeObjectURL(audioUrl);
      };

      audio.onerror = () => {
        if (btn) {
          btn.disabled = false;
          btn.innerText = "Grabar 3s y escuchar";
        }
        if (statusEl) {
          statusEl.innerText = "Error reproduciendo audio grabado";
          statusEl.style.color = "var(--danger-red)";
        }
        unmarkCheckpassed("chk-mic", "Micrófono");
        URL.revokeObjectURL(audioUrl);
      };

      audio.play().catch(e => {
        if (btn) {
          btn.disabled = false;
          btn.innerText = "Grabar 3s y escuchar";
        }
        if (statusEl) {
          statusEl.innerText = `Error al reproducir: ${e.message}`;
          statusEl.style.color = "var(--danger-red)";
        }
        unmarkCheckpassed("chk-mic", "Micrófono");
      });
    };

    // Collect audio slices every 200ms
    micMediaRecorder.start(200);

    micRecTimer = setInterval(() => {
      secondsLeft--;
      if (secondsLeft > 0) {
        if (btn) btn.innerText = `Grabando (${secondsLeft}s)...`;
      } else {
        clearInterval(micRecTimer);
      }
    }, 1000);

    setTimeout(() => {
      if (micMediaRecorder && micMediaRecorder.state === "recording") {
        micMediaRecorder.stop();
      }
    }, 3200);

  } catch (err) {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "Grabar 3s y escuchar";
    }
    if (statusEl) {
      statusEl.innerText = `Error: ${err.message}`;
      statusEl.style.color = "var(--danger-red)";
    }
  }
}

// 4. RESET AUDIO SWEEP & SPEAKER TESTS
function resetAudioTest() {
  audioLeftTested = false;
  audioRightTested = false;
  audioBothTested = false;

  ["btn-audio-left", "btn-audio-right", "btn-audio-both"].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) {
      btn.style.backgroundColor = "";
      btn.style.borderColor = "";
      btn.style.color = "";
    }
  });

  const statusEl = document.getElementById("audio-status-text");
  if (statusEl) {
    statusEl.innerText = "Prueba requerida: 0/3 completados";
    statusEl.style.color = "var(--text-muted)";
  }
  unmarkCheckpassed("chk-audio", "Parlantes");
  unmarkCheckpassed("chk-speakers", "Parlantes");
}

// ─────────────────────────────────────────────────────────────────
// 5. SCREEN / DISPLAY PIXEL & UNIFORMITY TESTER
// ─────────────────────────────────────────────────────────────────
const SCREEN_TEST_COLORS = [
  { name: "1. Rojo puro (#FF0000)", bg: "#ff0000" },
  { name: "2. Verde puro (#00FF00)", bg: "#00ff00" },
  { name: "3. Azul puro (#0000FF)", bg: "#0000ff" },
  { name: "4. Blanco puro (#FFFFFF)", bg: "#ffffff" },
  { name: "5. Negro puro (#000000)", bg: "#000000" },
  { name: "6. Amarillo (#FFFF00)", bg: "#ffff00" },
  { name: "7. Magenta (#FF00FF)", bg: "#ff00ff" },
  { name: "8. Cian (#00FFFF)", bg: "#00ffff" },
  { name: "9. Escala de grises / Gradiente", bg: "linear-gradient(to right, #000000 0%, #333333 25%, #666666 50%, #999999 75%, #ffffff 100%)" }
];
let currentScreenColorIndex = 0;
let screenTestCompleted = false;

function openScreenTestModal() {
  const modal = document.getElementById("screen-test-modal");
  if (!modal) return;
  currentScreenColorIndex = 0;
  modal.style.display = "flex";

  document.body.style.overflow = "hidden";
  document.documentElement.style.overflow = "hidden";

  if (document.documentElement.requestFullscreen) {
    document.documentElement.requestFullscreen().catch(() => {});
  }
  applyScreenColor();
}

function applyScreenColor() {
  const modal = document.getElementById("screen-test-modal");
  const label = document.getElementById("screen-color-label");
  const bar = document.getElementById("screen-test-bar");
  if (!modal || currentScreenColorIndex >= SCREEN_TEST_COLORS.length) return;

  const col = SCREEN_TEST_COLORS[currentScreenColorIndex];
  modal.style.background = col.bg;
  if (label) {
    label.innerText = `Color ${currentScreenColorIndex + 1}/${SCREEN_TEST_COLORS.length}: ${col.name}`;
  }

  if (bar) {
    bar.style.background = "transparent";
    bar.style.backgroundColor = "transparent";
    bar.style.backdropFilter = "none";
    if (col.bg === "#ffffff" || col.bg === "#ffff00" || col.bg === "#00ffff") {
      bar.style.color = "#000000";
      bar.style.textShadow = "0 1px 2px rgba(255, 255, 255, 0.9)";
    } else {
      bar.style.color = "#ffffff";
      bar.style.textShadow = "0 1px 3px rgba(0, 0, 0, 0.85), 0 0 6px rgba(0, 0, 0, 0.7)";
    }
  }
}

function nextScreenTestColor(event) {
  if (event) {
    if (event.target && (event.target.tagName === "BUTTON" || event.target.closest("button"))) return;
    event.preventDefault();
    event.stopPropagation();
  }

  currentScreenColorIndex++;
  if (currentScreenColorIndex >= SCREEN_TEST_COLORS.length) {
    finishScreenTest();
  } else {
    applyScreenColor();
  }
}

function prevScreenTestColor(event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  if (currentScreenColorIndex > 0) {
    currentScreenColorIndex--;
    applyScreenColor();
  }
}

function finishScreenTest() {
  screenTestCompleted = true;
  closeScreenTestModal();
  const statusEl = document.getElementById("screen-test-status");
  if (statusEl) {
    statusEl.innerText = "Pantalla: Aprobada";
    statusEl.style.color = "var(--success-green)";
  }
  markCheckpassed("chk-screen", "PANTALLA");
}

function closeScreenTestModal(event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  const modal = document.getElementById("screen-test-modal");
  if (modal) modal.style.display = "none";

  document.body.style.overflow = "";
  document.documentElement.style.overflow = "";

  if (document.fullscreenElement && document.exitFullscreen) {
    document.exitFullscreen().catch(() => {});
  }
  if (currentScreenColorIndex >= 3 && !screenTestCompleted) {
    finishScreenTest();
  }
}

function resetScreenTest() {
  currentScreenColorIndex = 0;
  screenTestCompleted = false;
  const statusEl = document.getElementById("screen-test-status");
  if (statusEl) {
    statusEl.innerText = "Pantalla: Pendiente";
    statusEl.style.color = "var(--text-muted)";
  }
  unmarkCheckpassed("chk-screen", "Pantalla");
}
