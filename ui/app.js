/**
 * Nabih Desktop Assistant - Frontend Logic & PyWebView Bridge
 * Handles real-time Orb animation state changes and synchronized live subtitles.
 */

class AssistantApp {
  constructor() {
    this.appCard = document.getElementById("appCard");
    this.statusLabel = document.getElementById("statusLabel");
    this.statusDot = document.getElementById("statusDot");
    this.subtitleText = document.getElementById("subtitleText");
    this.hotkeyBadge = document.getElementById("hotkeyBadge");

    this.currentState = "IDLE";
    this._initBridge();
  }

  _initBridge() {
    console.log("[NABIH UI] Initializing PyWebView Bridge...");

    // Wait for pywebview initialization event
    window.addEventListener("pywebviewready", () => {
      console.log("[NABIH UI] PyWebView API is ready!");
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.get_initial_config().then((cfg) => {
          if (cfg && cfg.hotkey) {
            this.hotkeyBadge.innerText = cfg.hotkey.toUpperCase();
          }
        }).catch(err => console.log("Config fetch err:", err));
      }
    });
  }

  /**
   * Called directly by Python to update assistant state and animations.
   * @param {string} state - "IDLE" | "LISTENING" | "THINKING" | "SPEAKING"
   * @param {string} [customLabel] - Optional descriptive label
   */
  setState(state, customLabel = null) {
    const validStates = ["IDLE", "LISTENING", "THINKING", "SPEAKING"];
    if (!validStates.includes(state)) return;

    this.currentState = state;
    this.appCard.className = `widget-card state-${state.toLowerCase()}`;

    // Update status badge styling and text
    switch (state) {
      case "IDLE":
        this.statusLabel.innerText = customLabel || "جاهز ومستعد • IDLE";
        break;

      case "LISTENING":
        this.statusLabel.innerText = customLabel || "سامعك يا برنس... • LISTENING";
        this.subtitleText.innerHTML = '<span class="speaker-pill speaker-user">🎙️ استماع</span><span class="speech-content">سامع صوتك، اتكلم براحتك...</span>';
        break;

      case "THINKING":
        this.statusLabel.innerText = customLabel || "المخ شغال... • THINKING";
        this.subtitleText.innerHTML = '<span class="speaker-pill speaker-bot">⚡ معالجة</span><span class="speech-content">نبيه بيفكر وينفذ الأدوات...</span>';
        break;

      case "SPEAKING":
        this.statusLabel.innerText = customLabel || "نبيه بيتكلم • SPEAKING";
        break;
    }
  }

  /**
   * Called by Python to render synchronized real-time live subtitles.
   * @param {string} text - The sentence or transcript text
   * @param {boolean} isUser - Whether this is the user's input or Nabih's reply
   */
  updateSubtitles(text, isUser = false) {
    if (!text) return;

    if (isUser) {
      this.subtitleText.innerHTML = `<span class="speaker-pill speaker-user">👤 أنت</span><span class="speech-content">${text}</span>`;
    } else {
      this.subtitleText.innerHTML = `<span class="speaker-pill speaker-bot">✨ نبيه</span><span class="speech-content">${text}</span>`;
    }

    // Auto-scroll to bottom of subtitles panel
    const panel = document.getElementById("subtitlesPanel");
    if (panel) {
      panel.scrollTop = panel.scrollHeight;
    }
  }

  /**
   * Closes the desktop assistant application via the Python bridge.
   */
  closeWidget() {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.close_app();
    } else {
      window.close();
    }
  }

  /**
   * Triggers an immediate interrupt/cancellation of any active task or speech.
   */
  triggerInterrupt() {
    console.log("[NABIH UI] 🛑 User triggered interrupt.");
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.interrupt();
    }
  }

  /**
   * Fallback click on the Orb to trigger listening or cancel.
   */
  toggleListening() {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.on_orb_clicked();
    }
  }
}

// Global instance exposed for Python calls
window.assistantApp = new AssistantApp();

// Global Escape key listener inside webview
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    window.assistantApp.triggerInterrupt();
  }
});

// Bridge aliases directly on window for simple Python evaluate_js
window.setAssistantState = (state, label) => window.assistantApp.setState(state, label);
window.updateSubtitles = (text, isUser) => window.assistantApp.updateSubtitles(text, isUser);
