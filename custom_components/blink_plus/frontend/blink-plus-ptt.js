// Native Home Assistant picture-element and card for Blink Plus push-to-talk.
class BlinkPlusPTT extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: "open"});
    this.shadowRoot.innerHTML = '<style>' +
      ':host{display:block;width:max-content;max-width:90vw;font-family:var(--paper-font-body1_-_font-family,inherit)}' +
      'button{display:flex;align-items:center;gap:6px;min-height:44px;border-radius:22px;padding:8px 14px;' +
      'border:1px solid var(--divider-color,#657080);background:var(--ha-card-background,#202734);' +
      'color:var(--primary-text-color,white);font:inherit;cursor:pointer;touch-action:none;user-select:none;-webkit-user-select:none}' +
      'button[aria-pressed=true]{outline:2px solid var(--primary-color,#03a9f4)}' +
      'button:disabled{opacity:.65;cursor:default}ha-icon{width:22px;height:22px}' +
      '.status{display:block;max-width:25ch;font-size:12px;padding:4px 6px;border-radius:8px;' +
      'background:var(--ha-card-background,#202734);color:var(--primary-text-color,white)}' +
      '.status:empty{display:none}</style>' +
      '<button type="button" aria-pressed="false"><ha-icon icon="mdi:microphone"></ha-icon><span>Hold to talk</span></button>' +
      '<span class="status" role="status"></span>';
    this.button = this.shadowRoot.querySelector("button");
    this.label = this.shadowRoot.querySelector("button span");
    this.status = this.shadowRoot.querySelector(".status");
    this.current = null;
    this.supported = !!(window.isSecureContext && navigator.mediaDevices?.getUserMedia &&
      window.AudioContext && window.AudioWorkletNode);
    this.release = () => this.end();
    this.visibilityChanged = () => { if (document.hidden) this.end(); };
    this.button.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      this.button.setPointerCapture(event.pointerId);
      this.begin();
    });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture", "blur"]) {
      this.button.addEventListener(type, this.release);
    }
    this.button.addEventListener("click", (event) => { event.preventDefault(); event.stopPropagation(); });
    this.button.addEventListener("contextmenu", (event) => event.preventDefault());
    this.button.addEventListener("keydown", (event) => {
      if ((event.code === "Space" || event.code === "Enter") && !event.repeat) {
        event.preventDefault(); event.stopPropagation(); this.begin();
      }
    });
    this.button.addEventListener("keyup", (event) => {
      if (event.code === "Space" || event.code === "Enter") {
        event.preventDefault(); event.stopPropagation(); this.end();
      }
    });
  }
  setConfig(config) {
    if (typeof config.entity !== "string" || !config.entity.startsWith("camera.")) {
      throw new Error("Choose a Blink Plus camera entity");
    }
    if (this.config?.entity !== config.entity) this.end();
    this.config = config;
    this.paint();
  }
  set hass(hass) {
    if (this._hass && this._hass.connection !== hass.connection) this.end();
    this._hass = hass;
    const state = hass.states[this.config?.entity];
    if (this.current && (!state || state.state === "unavailable")) this.end("Camera is unavailable");
    this.paint();
  }
  connectedCallback() {
    this.disposed = false;
    window.addEventListener("blur", this.release);
    window.addEventListener("pagehide", this.release);
    document.addEventListener("visibilitychange", this.visibilityChanged);
    this.paint();
  }
  disconnectedCallback() {
    this.disposed = true;
    this.end();
    window.removeEventListener("blur", this.release);
    window.removeEventListener("pagehide", this.release);
    document.removeEventListener("visibilitychange", this.visibilityChanged);
  }
  getCardSize() { return 1; }
  paint(message) {
    if (message !== undefined) this.message = message;
    const available = this._hass?.states[this.config?.entity];
    this.button.disabled = !this.supported || !available || available.state === "unavailable" || !!this.closing;
    this.button.setAttribute("aria-pressed", this.current ? "true" : "false");
    this.label.textContent = this.current ? "Release to stop" : this.closing ? "Finishing..." : "Hold to talk";
    this.status.textContent = !window.isSecureContext ? "Open HA over HTTPS to use the microphone" :
      !this.supported ? "Microphone capture is unavailable in this browser" : this.message || "";
  }
  end(message = "") {
    const press = this.current;
    if (!press) return;
    this.current = null;
    clearTimeout(press.limit);
    if (press.node) { press.node.port.onmessage = null; press.node.disconnect(); }
    if (press.source) press.source.disconnect();
    if (press.stream) press.stream.getTracks().forEach((track) => track.stop());
    if (press.context) press.context.close().catch(() => {});
    this.closing = true;
    Promise.resolve(press.opening).catch(() => null).then((opened) => {
      const ident = press.id || opened?.session;
      return press.pending.then(() => {
        if (ident) return press.hass.callWS({type:"blink_plus/talk/stop",session:ident}).catch(() => {});
      });
    }).finally(() => {
      this.closing = false;
      this.paint(message);
    });
    this.paint(message);
  }
  async begin() {
    if (this.current || this.button.disabled || this.disposed) return;
    const press = {hass:this._hass,pending:Promise.resolve(),queued:0,sequence:0};
    this.current = press;
    this.paint("Allow microphone access if asked...");
    try {
      press.context = new AudioContext({sampleRate:16000});
      await press.context.resume();
      press.stream = await navigator.mediaDevices.getUserMedia({
        audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}
      });
      if (this.current !== press) {
        press.stream.getTracks().forEach((track) => track.stop());
        if (!this.disposed && !this.current) this.paint("Microphone ready. Hold again to talk.");
        return;
      }
      await press.context.audioWorklet.addModule("/blink_plus/frontend/microphone-worklet.js");
      if (this.current !== press) return;
      press.opening = press.hass.callWS({type:"blink_plus/talk/start",entity_id:this.config.entity});
      const result = await press.opening;
      press.id = result.session;
      if (this.current !== press) return;
      press.source = press.context.createMediaStreamSource(press.stream);
      press.node = new AudioWorkletNode(press.context,"camera-microphone");
      press.node.port.onmessage = (event) => {
        if (this.current !== press) return;
        if (press.queued >= 4) { this.end("Connection is too slow for live talk"); return; }
        let binary = "";
        for (const byte of new Uint8Array(event.data)) binary += String.fromCharCode(byte);
        const command = {type:"blink_plus/talk/audio",session:press.id,
          sequence:press.sequence++,samples:btoa(binary)};
        press.queued++;
        press.pending = press.pending.then(() => press.hass.callWS(command)).then(() => {
          press.queued--;
        }).catch((error) => {
          press.queued--;
          if (this.current === press) this.end(error.message || "Talk session ended");
        });
      };
      press.source.connect(press.node);
      press.node.connect(press.context.destination);
      press.limit = setTimeout(() => this.end("Talk stopped after one minute"),60000);
      this.paint("Talking...");
    } catch (error) {
      if (this.current !== press) return;
      const message = error.name === "NotAllowedError" ? "Microphone permission was denied" :
        error.name === "NotFoundError" ? "No microphone was found" :
        error.message || "Couldn't start talk";
      this.end(message);
    }
  }
}
if (!customElements.get("blink-plus-ptt")) customElements.define("blink-plus-ptt",BlinkPlusPTT);
window.customCards = window.customCards || [];
window.customCards.push({type:"blink-plus-ptt",name:"Blink Plus push to talk",
  description:"Hold to speak through a Blink Plus camera with live video open"});
