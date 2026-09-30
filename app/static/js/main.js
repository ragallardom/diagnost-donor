/* ==============================================================================
   DIAGNOSTDONOR - MAIN APPLICATION ORCHESTRATOR (js/main.js)
   Initializes all hardware submodules on DOM load and handles global events.
   ============================================================================== */

document.addEventListener("DOMContentLoaded", () => {
  // 1. Initialize Interactive Testing Modules
  buildKeyboardMatrix();
  initTouchpadCanvas();
  initTouchpadButtons();
  initKeyListeners();

  // 2. Request Keyboard Lock API for Escape, F11, Tab capture
  requestKeyboardLock();

  updateChecklistProgress();
  initBrightness();

  // 3. Hardware Data Initial Load & Smart Polling (Fast 1s interval for instant HDMI/Sensor response)
  //    refreshAllData() also auto-launches the baseline CPU, RAM, camera and mic tests.
  refreshAllData(); // Full load once
  startTelemetryLoop(); // Polling dynamic sensors & external displays

  // 4. Unlock AudioContext & enforce Keyboard Lock on first user interaction
  const unlockAudioAndLock = () => {
    requestKeyboardLock();
    if (audioContext && audioContext.state === 'suspended') {
      audioContext.resume();
    } else if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      if (audioContext.state === 'suspended') audioContext.resume();
    }
  };

  document.addEventListener('click', unlockAudioAndLock, { once: false });
  document.addEventListener('keydown', unlockAudioAndLock, { once: false, capture: true });
});
