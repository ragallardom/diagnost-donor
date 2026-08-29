/* ==============================================================================
   DIAGNOSTDONOR - KEYBOARD MATRIX TESTER MODULE (js/keyboard.js)
   Renders the 78-key keyboard grid, handles physical keydown/keyup events,
   manages the 5-color multi-touch cycle, and acquires KeyboardLock API.
   ============================================================================== */

let pressedKeysSet = new Set();
let keyPressCounts = {}; // Track press count per key to cycle colors
let totalKeyPresses = 0;

// 5-Color Multi-touch Cycle: Verde -> Violeta -> Naranjo -> Azul -> Amarillo
const KEY_COLOR_CLASSES = ["color-green", "color-violet", "color-orange", "color-blue", "color-yellow"];

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

// MULTIMEDIA / HOTKEY NORMALIZER (MAPS HARDWARE COMBOS TO F-KEYS & FN)
const mediaKeyMap = {
  "AudioVolumeMute": "F1", "VolumeMute": "F1", "Help": "F1",
  "AudioVolumeDown": "F2", "VolumeDown": "F2",
  "AudioVolumeUp": "F3", "VolumeUp": "F3",
  "MicrophoneMute": "F4", "AudioMicMute": "F4",
  "BrightnessDown": "F5", "MonBrightnessDown": "F5",
  "BrightnessUp": "F6", "MonBrightnessUp": "F6",
  "DisplayToggle": "F7", "LaunchScreenSaver": "F7", "VideoModeCycle": "F7",
  "MediaPlayPause": "F8", "MediaTrackPrevious": "F8", "AirplaneMode": "F8",
  "MediaTrackNext": "F9", "LaunchSettings": "F9", "LaunchApplication1": "F9", "NotificationCenter": "F9", "Notification": "F9",
  "Search": "F10", "BrowserSearch": "F10", "LaunchMail": "F10", "Answer": "F10", "Phone": "F10", "Hangup": "F10",
  // ThinkPad T14 Gen 5 / Gen 6 F11 Star/Favorites / User Defined / Snipping Tool keys:
  "Favorites": "F11", "LaunchFavorites": "F11", "LaunchApplication2": "F11", "LaunchApp2": "F11",
  "Tools": "F11", "LaunchTools": "F11", "XF86Tools": "F11", "ControlPanel": "F11", "LaunchControlPanel": "F11",
  "F23": "F11", "OpenURL": "F11", "Save": "F11", "Select": "F11", "ZoomIn": "F11", "KbdBrightnessUp": "F11", "KbdToggle": "F11",
  "Calculator": "F12", "LaunchCalculator": "F12", "LaunchApplication3": "F12", "ZoomOut": "F12", "F24": "F12"
};

// ACQUIRE KEYBOARD LOCK API FOR F11, ESCAPE, TAB
async function requestKeyboardLock() {
  if (navigator.keyboard && typeof navigator.keyboard.lock === 'function') {
    try {
      await navigator.keyboard.lock([
        "Escape", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
        "Tab", "AltLeft", "AltRight", "MetaLeft", "MetaRight", "ContextMenu"
      ]);
    } catch (err) {
      navigator.keyboard.lock().catch(() => {});
    }
  }
}

// RESOLVE EXACT KEY CODE FROM ANY EVENT
function normalizeKeyCode(e) {
  const rawCode = e.code || "";
  const rawKey = e.key || "";
  const keyCode = e.keyCode || e.which || 0;

  // 1. Function Keys (F1 - F12) by keycode 112-123 or direct string
  if (keyCode >= 112 && keyCode <= 123) {
    return `F${keyCode - 111}`;
  }
  const fMatch = (rawCode.match(/^F([1-9]|1[0-2])$/i) || rawKey.match(/^F([1-9]|1[0-2])$/i));
  if (fMatch) {
    return `F${fMatch[1]}`;
  }

  // 2. Multimedia / OEM hardware hotkeys (HP, ThinkPad, Dell)
  if (mediaKeyMap[rawKey]) return mediaKeyMap[rawKey];
  if (mediaKeyMap[rawCode]) return mediaKeyMap[rawCode];

  // 3. Modifiers and special keys
  if (rawKey === "Escape" || rawCode === "Escape" || keyCode === 27) return "Escape";
  if (rawKey === "Tab" || rawCode === "Tab" || keyCode === 9) return "Tab";
  if (rawKey === "CapsLock" || rawCode === "CapsLock" || keyCode === 20) return "CapsLock";
  if (rawKey === "Shift" || rawCode === "ShiftLeft" || keyCode === 16) return rawCode === "ShiftRight" ? "ShiftRight" : "ShiftLeft";
  if (rawKey === "Control" || rawCode === "ControlLeft" || keyCode === 17) return rawCode === "ControlRight" ? "ControlRight" : "ControlLeft";
  if (rawKey === "Alt" || rawCode === "AltLeft" || keyCode === 18) return rawCode === "AltRight" ? "AltRight" : "AltLeft";
  if (rawKey === "Meta" || rawCode === "MetaLeft" || rawCode === "MetaRight" || keyCode === 91 || keyCode === 92) return "MetaLeft";
  if (rawKey === "Fn" || rawCode === "Fn" || rawKey === "FnLock" || rawCode === "FnLock" || keyCode === 255 || keyCode === 143) return "Fn";
  if (rawKey === "Enter" || rawCode === "Enter" || keyCode === 13) return "Enter";
  if (rawKey === "Backspace" || rawCode === "Backspace" || keyCode === 8) return "Backspace";
  if (rawKey === "Delete" || rawCode === "Delete" || keyCode === 46) return "Delete";
  if (rawKey === " " || rawCode === "Space" || keyCode === 32) return "Space";

  // 4. Arrow keys
  if (rawKey === "ArrowLeft" || rawCode === "ArrowLeft" || keyCode === 37) return "ArrowLeft";
  if (rawKey === "ArrowUp" || rawCode === "ArrowUp" || keyCode === 38) return "ArrowUp";
  if (rawKey === "ArrowRight" || rawCode === "ArrowRight" || keyCode === 39) return "ArrowRight";
  if (rawKey === "ArrowDown" || rawCode === "ArrowDown" || keyCode === 40) return "ArrowDown";

  // 5. Alphanumeric by code (KeyA..KeyZ, Digit0..Digit9)
  if (rawCode.startsWith("Key") || rawCode.startsWith("Digit")) return rawCode;

  // 6. Direct fallback
  return rawCode || rawKey;
}

// BUILD KEYBOARD MATRIX DOM (ALL KEYS CLICKABLE AS MANUAL BACKUP)
function buildKeyboardMatrix() {
  const container = document.getElementById("keyboard-matrix");
  if (!container) return;
  container.innerHTML = "";

  keyboardLayout.forEach(row => {
    const rowEl = document.createElement("div");
    rowEl.className = "kb-row";

    row.forEach(code => {
      const tile = document.createElement("div");
      tile.className = "key-tile";
      tile.setAttribute("data-code", code);

      let label = keyDisplayNames[code] || code.replace("Key", "").replace("Digit", "");
      tile.innerText = label;
      tile.title = `${label}: Presiona la tecla física o haz clic para marcarla`;

      // Allow clicking any key in the matrix as a failsafe
      tile.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        totalKeyPresses++;
        markKeyPassed(code);
        const lastKeyEl = document.getElementById("last-key-code");
        if (lastKeyEl) lastKeyEl.innerText = `${label} (Validado)`;
        setTimeout(() => handleKeyRelease(code), 150);
      });

      rowEl.appendChild(tile);
    });

    container.appendChild(rowEl);
  });
}

// MARK KEY PASSED WITH 5-COLOR CYCLE
function markKeyPassed(code) {
  if (!code) return;
  pressedKeysSet.add(code);

  keyPressCounts[code] = (keyPressCounts[code] || 0) + 1;
  const colorIndex = (keyPressCounts[code] - 1) % KEY_COLOR_CLASSES.length;
  const activeColorClass = KEY_COLOR_CLASSES[colorIndex];

  const totalKeys = keyboardLayout.flat().length;
  const count = pressedKeysSet.size;

  const keyCountEl = document.getElementById("key-count");
  if (keyCountEl) keyCountEl.innerText = totalKeyPresses;

  if (count >= totalKeys) {
    markCheckpassed("chk-keyboard", "TECLADO");
  } else {
    unmarkCheckpassed("chk-keyboard", `Teclado (${count}/${totalKeys})`);
  }

  const tile = document.querySelector(`.key-tile[data-code="${code}"]`);
  if (tile) {
    tile.classList.add("pressed");
    KEY_COLOR_CLASSES.forEach(cls => tile.classList.remove(cls));
    tile.classList.add(activeColorClass);
  }
}

// HANDLE KEY UP RELEASE
function handleKeyRelease(code) {
  const tile = document.querySelector(`.key-tile[data-code="${code}"]`);
  if (tile) {
    tile.classList.remove("active-down");
  }
  const fnTile = document.querySelector(`.key-tile[data-code="Fn"]`);
  if (fnTile && code !== "Fn") {
    fnTile.classList.remove("active-down");
  }
}

// INITIALIZE KEYBOARD EVENT LISTENERS (STRICT BROWSER HOTKEY BLOCKING)
function initKeyListeners() {
  const handleKeyDown = (e) => {
    const targetTag = e.target ? e.target.tagName : "";
    const isInput = targetTag === "INPUT" || targetTag === "TEXTAREA" || targetTag === "SELECT" || (e.target && e.target.isContentEditable);

    if (isInput) {
      if (e.key === "Escape") {
        const confirmModal = document.getElementById("opal-confirm-modal");
        if (confirmModal && confirmModal.style.display !== "none") {
          closeOpalConfirmModal();
          return;
        }
        closeOpalModal();
        if (typeof closePowerModal === "function") closePowerModal();
      } else if (e.key === "Enter" && e.target.id === "opal-psid-input") {
        e.preventDefault();
        submitOpalRevert();
      }
      return;
    }

    const screenModal = document.getElementById("screen-test-modal");
    if (screenModal && screenModal.style.display !== "none") {
      if (e.key === "Escape") {
        closeScreenTestModal(e);
      } else if (e.key === " " || e.key === "ArrowRight" || e.key === "Enter" || e.key === "PageDown") {
        nextScreenTestColor(e);
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
        prevScreenTestColor(e);
      }
      return;
    }

    // STRICTLY BLOCK BROWSER DEFAULT ACTIONS (F1 Help, F3 Search, F5 Reload, F11 Fullscreen, Alt, Tab, Ctrl)
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();

    requestKeyboardLock();

    const code = normalizeKeyCode(e);

    totalKeyPresses++;
    const keyCountEl = document.getElementById("key-count");
    const lastKeyEl = document.getElementById("last-key-code");
    if (keyCountEl) keyCountEl.innerText = totalKeyPresses;
    if (lastKeyEl) lastKeyEl.innerText = `${e.key || e.code} -> ${code}`;

    markKeyPassed(code);

    const tile = document.querySelector(`.key-tile[data-code="${code}"]`);
    if (tile) {
      tile.classList.add("active-down");
    }
  };

  const handleKeyUp = (e) => {
    const targetTag = e.target ? e.target.tagName : "";
    const isInput = targetTag === "INPUT" || targetTag === "TEXTAREA" || targetTag === "SELECT" || (e.target && e.target.isContentEditable);
    if (isInput) return;

    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();

    const code = normalizeKeyCode(e);
    handleKeyRelease(code);
  };

  window.addEventListener("keydown", handleKeyDown, { capture: true, passive: false });
  window.addEventListener("keyup", handleKeyUp, { capture: true, passive: false });
  document.addEventListener("keydown", handleKeyDown, { capture: true, passive: false });
  document.addEventListener("keyup", handleKeyUp, { capture: true, passive: false });
}

// RESET KEYBOARD TEST
function resetKeyboardTest() {
  pressedKeysSet.clear();
  keyPressCounts = {};
  totalKeyPresses = 0;

  const keyCountEl = document.getElementById("key-count");
  const lastKeyEl = document.getElementById("last-key-code");
  if (keyCountEl) keyCountEl.innerText = "0";
  if (lastKeyEl) lastKeyEl.innerText = "Ninguna";

  document.querySelectorAll(".key-tile").forEach(t => {
    t.classList.remove("pressed");
    t.classList.remove("active-down");
    KEY_COLOR_CLASSES.forEach(cls => t.classList.remove(cls));
  });
  unmarkCheckpassed("chk-keyboard", `Teclado (0/${keyboardLayout.flat().length})`);
}
