/* ==============================================================================
   DIAGNOSTDONOR - TOUCHPAD & MULTITOUCH TESTER MODULE (js/touchpad.js)
   Calibrated 1:1 drawing canvas, left/right click tiles, 2-finger gesture recognition.
   ============================================================================== */

let touchpadLeftClicked = false;
let touchpadRightClicked = false;
let touchpadDrawn = false;

function checkTouchpadComplete() {
  if (touchpadLeftClicked && touchpadRightClicked && touchpadDrawn) {
    markCheckpassed("chk-touchpad", "TOUCHPAD");
  }
}

// 5-Color Multi-touch Cycle: Verde -> Violeta -> Naranjo -> Azul -> Amarillo (mismo orden que teclado)
const CLICK_COLOR_CLASSES = ["color-green", "color-violet", "color-orange", "color-blue", "color-yellow"];
let leftClickCount = 0;
let rightClickCount = 0;
let lastRightClickTime = 0;

function handleLeftClickEvent() {
  touchpadLeftClicked = true;
  leftClickCount++;
  const tileLeft = document.getElementById("tile-left-click");
  const statusEl = document.getElementById("status-left-click");

  if (tileLeft) {
    tileLeft.classList.add("passed");
    CLICK_COLOR_CLASSES.forEach(cls => tileLeft.classList.remove(cls));
    const colorIndex = (leftClickCount - 1) % CLICK_COLOR_CLASSES.length;
    tileLeft.classList.add(CLICK_COLOR_CLASSES[colorIndex]);

    tileLeft.classList.add("active-down");
    setTimeout(() => tileLeft.classList.remove("active-down"), 120);
  }

  if (statusEl) {
    statusEl.innerText = leftClickCount === 1 ? "Aprobado" : `Aprobado (${leftClickCount})`;
  }
  checkTouchpadComplete();
}

function handleRightClickEvent(extraText = "") {
  const now = Date.now();
  if (now - lastRightClickTime < 200) {
    return; // Prevent duplicate event when mousedown and contextmenu fire together
  }
  lastRightClickTime = now;

  touchpadRightClicked = true;
  rightClickCount++;
  const tileRight = document.getElementById("tile-right-click");
  const statusEl = document.getElementById("status-right-click");

  if (tileRight) {
    tileRight.classList.add("passed");
    CLICK_COLOR_CLASSES.forEach(cls => tileRight.classList.remove(cls));
    const colorIndex = (rightClickCount - 1) % CLICK_COLOR_CLASSES.length;
    tileRight.classList.add(CLICK_COLOR_CLASSES[colorIndex]);

    tileRight.classList.add("active-down");
    setTimeout(() => tileRight.classList.remove("active-down"), 120);
  }

  if (statusEl) {
    if (extraText) {
      statusEl.innerText = `${extraText} (${rightClickCount})`;
    } else {
      statusEl.innerText = rightClickCount === 1 ? "Aprobado" : `Aprobado (${rightClickCount})`;
    }
  }
  checkTouchpadComplete();
}

// 1. INITIALIZE LEFT & RIGHT CLICK PHYSICAL/TAP TILES
function initTouchpadButtons() {
  const tileLeft = document.getElementById("tile-left-click");
  const tileRight = document.getElementById("tile-right-click");

  if (tileLeft) {
    tileLeft.addEventListener("click", () => {
      handleLeftClickEvent();
    });
  }

  if (tileRight) {
    tileRight.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      handleRightClickEvent();
    });

    tileRight.addEventListener("mousedown", (e) => {
      if (e.button === 2) {
        e.preventDefault();
        handleRightClickEvent();
      }
    });
  }
}

// 2. INITIALIZE CALIBRATED TOUCHPAD CANVAS
function initTouchpadCanvas() {
  const canvas = document.getElementById("touchpad-canvas");
  if (!canvas) return;
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

  // Movement is verified by the distance actually traced: one click on the canvas is not a stroke.
  const MIN_STROKE_PX = 150;
  let strokeLength = 0;
  let lastPos = null;
  window.addEventListener("touchpad-reset", () => { strokeLength = 0; lastPos = null; });

  function startDraw(e) {
    isDrawing = true;
    const pos = getPos(e);
    lastPos = pos;
    ctx.beginPath();
    ctx.moveTo(pos.x, pos.y);
    if (log) log.innerText = `Touchpad: Trazo en (${Math.round(pos.x)}, ${Math.round(pos.y)})`;
  }

  function draw(e) {
    if (!isDrawing) return;
    const pos = getPos(e);
    if (lastPos) strokeLength += Math.hypot(pos.x - lastPos.x, pos.y - lastPos.y);
    lastPos = pos;
    if (strokeLength >= MIN_STROKE_PX && !touchpadDrawn) {
      touchpadDrawn = true;
      checkTouchpadComplete();
    }
    ctx.lineTo(pos.x, pos.y);
    ctx.strokeStyle = "#a855f7";
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    ctx.stroke();

    if (e.touches && log) {
      log.innerText = `Multitouch: ${e.touches.length} dedo(s) detectado(s)`;
      if (e.touches.length >= 2) {
        handleRightClickEvent("Aprobado (2 dedos)");
      }
    }
  }

  function stopDraw() {
    isDrawing = false;
  }

  canvas.addEventListener("mousedown", startDraw);
  canvas.addEventListener("mousemove", draw);
  canvas.addEventListener("mouseup", stopDraw);
  canvas.addEventListener("mouseleave", stopDraw);

  canvas.addEventListener("touchstart", startDraw);
  canvas.addEventListener("touchmove", draw);
  canvas.addEventListener("touchend", stopDraw);

  canvas.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    handleRightClickEvent();
  });
}

// 3. CLEAR TOUCHPAD CANVAS
function clearTouchCanvas() {
  const canvas = document.getElementById("touchpad-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

// 4. RESET ALL TOUCHPAD TESTS
function resetTouchpadTest() {
  touchpadLeftClicked = false;
  touchpadRightClicked = false;
  touchpadDrawn = false;
  window.dispatchEvent(new Event("touchpad-reset"));
  leftClickCount = 0;
  rightClickCount = 0;
  lastRightClickTime = 0;

  const tileLeft = document.getElementById("tile-left-click");
  const tileRight = document.getElementById("tile-right-click");
  const statusLeft = document.getElementById("status-left-click");
  const statusRight = document.getElementById("status-right-click");

  if (tileLeft) {
    tileLeft.classList.remove("passed");
    CLICK_COLOR_CLASSES.forEach(cls => tileLeft.classList.remove(cls));
  }
  if (tileRight) {
    tileRight.classList.remove("passed");
    CLICK_COLOR_CLASSES.forEach(cls => tileRight.classList.remove(cls));
  }
  if (statusLeft) statusLeft.innerText = "No presionado";
  if (statusRight) statusRight.innerText = "No presionado";

  clearTouchCanvas();
  unmarkCheckpassed("chk-touchpad", "Touchpad");
}
