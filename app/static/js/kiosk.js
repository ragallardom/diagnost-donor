/* ==============================================================================
   DIAGNOSTDONOR - KIOSK GUARD & BACKEND REQUEST HELPER (js/kiosk.js)
   Loaded first. Provides apiPost() (adds the per-boot session token required by
   the backend on every POST) and blocks browser actions that could navigate
   away from the diagnostic UI (drag & drop, context menu, browser shortcuts).
   Chrome enterprise policies enforce the same restrictions; this is a second layer.
   ============================================================================== */

const DIAG_SESSION_TOKEN = (() => {
  const meta = document.querySelector('meta[name="diag-session-token"]');
  return meta ? meta.getAttribute("content") : "";
})();

// POST JSON to the local backend with the session token header.
function apiPost(url, payload) {
  const options = {
    method: "POST",
    headers: { "X-Diag-Token": DIAG_SESSION_TOKEN }
  };
  if (payload !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(payload);
  }
  return fetch(url, options);
}

// Scales the whole UI to the screen. The layout was designed for ~1600x900: on smaller screens
// (1366x768, 1280x720...) everything looked too big and crowded, so it is shrunk proportionally.
const UI_ZOOM_MIN = 0.72;

// Small screens shrink the UI (design size ~1600x900, never above 1.0 up to Full HD);
// 2K / 4K screens enlarge it so it does not look tiny.
function computeUiZoom(width, height) {
  const big = Math.min(width / 1920, height / 1080);
  if (big > 1) return Math.round(Math.min(1.5, big) * 100) / 100;
  const small = Math.min(width / 1600, height / 900);
  return Math.round(Math.max(UI_ZOOM_MIN, Math.min(1, small)) * 100) / 100;
}

function applyUiScale() {
  // screen.* does not change with the page zoom, so this cannot feed back on itself.
  const w = window.screen.width || window.innerWidth;
  const h = window.screen.height || window.innerHeight;
  const z = computeUiZoom(w, h);
  document.documentElement.style.zoom = z;
  document.documentElement.style.setProperty("--ui-zoom", z);
}

applyUiScale();
window.addEventListener("resize", applyUiScale);

(() => {
  // Dropping a file or link on the window would navigate to it.
  for (const type of ["dragover", "drop"]) {
    window.addEventListener(type, (e) => e.preventDefault(), true);
  }
  // No dragging of links/images out of the page.
  window.addEventListener("dragstart", (e) => e.preventDefault(), true);

  // Browser context menu offers Back/Reload/Print/Save. The touchpad test
  // listens for contextmenu on its own elements; preventDefault keeps it working.
  window.addEventListener("contextmenu", (e) => e.preventDefault(), true);

  // Middle-click / back-forward mouse buttons.
  window.addEventListener("auxclick", (e) => e.preventDefault(), true);
  window.addEventListener("mouseup", (e) => {
    if (e.button === 3 || e.button === 4) e.preventDefault();
  }, true);

  // Browser shortcuts that open dialogs, windows or navigate. Only the default
  // action is cancelled, so the keyboard test still sees every key press.
  const BLOCKED_CTRL_KEYS = new Set([
    "o", "p", "s", "u", "n", "t", "w", "h", "j", "d", "f", "g", "l", "k",
    "e", "r", "q", "i", "m", "b", "+", "-", "=", "0"
  ]);
  const BLOCKED_KEYS = new Set([
    "F1", "F3", "F5", "F6", "F7", "F10", "F11", "F12",
    "BrowserBack", "BrowserForward", "BrowserRefresh", "BrowserHome", "BrowserSearch"
  ]);

  window.addEventListener("keydown", (e) => {
    const key = (e.key || "").toLowerCase();
    if ((e.ctrlKey || e.metaKey) && BLOCKED_CTRL_KEYS.has(key)) {
      e.preventDefault();
    } else if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "Home")) {
      e.preventDefault();
    } else if (BLOCKED_KEYS.has(e.key) || BLOCKED_KEYS.has(e.code)) {
      e.preventDefault();
    }
  }, true);
})();
