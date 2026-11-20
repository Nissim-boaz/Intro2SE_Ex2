// AudioTokenListener — listens on the phone microphone and decodes the attendance code.
//
//   const listener = new AudioTokenListener({ timeoutMs: 10000 });
//   listener.onCode = (code) => ...;      // decoded twice in a row, parity OK
//   listener.onLevel = (info) => ...;     // ~10 times a second: {snr, peakHz, levels, symbol}
//   listener.onFail = (reason) => ...;    // "denied" | "unsupported" | "timeout" | "low_rate"
//   await listener.start();               // call from a tap (iOS needs a user gesture)
//   listener.stop();
//
// Decoding: we watch for the SYNC tone. Its onset (which follows a silent gap, so
// room echo does not blur it) anchors the frame. After SYNC_MS come 5 symbol slots;
// for each slot we sum the energy of the 8 data tones over the middle of the slot
// and take the strongest. Echo from the previous tone is weaker than the direct
// tone, so it loses. Parity + two identical reads guard against mistakes.
class AudioTokenListener {
  constructor({ timeoutMs = 10000, thresholdDb = 14, confirmations = 2 } = {}) {
    this.P = window.AudioProtocol;
    this.timeoutMs = timeoutMs;
    this.thresholdDb = thresholdDb;
    this.confirmations = confirmations;
    this.keepListening = false;
    this.onCode = () => {};
    this.onLevel = () => {};
    this.onFail = () => {};
    this._reset();
  }

  _reset() {
    this.history = [];          // [{t, levels}] for the last ~1.5s
    this.syncOn = null;         // time the current sync tone started
    this.inSync = false;
    this.pendingFrame = null;   // start time of the data slots we are waiting for
    this.lastCandidate = null;
    this.streak = 0;
    this.done = false;
  }

  get running() { return !!this.ctx; }

  async start() {
    this._reset();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return this._fail("unsupported");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
    } catch (err) {
      return this._fail(err && err.name === "NotAllowedError" ? "denied" : "unsupported");
    }
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    await this.ctx.resume();
    if (this.ctx.sampleRate < 40000) return this._fail("low_rate");

    const src = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.analyser.smoothingTimeConstant = 0;
    src.connect(this.analyser);
    this.spectrum = new Float32Array(this.analyser.frequencyBinCount);

    const binHz = this.ctx.sampleRate / this.analyser.fftSize;
    this.binHz = binHz;
    this.targets = [this.P.SYNC_FREQ, ...this.P.DATA_FREQS].map((f) => Math.round(f / binHz));
    this.noiseRange = [Math.round(16000 / binHz), Math.round(20500 / binHz)];
    // the FFT window looks back fftSize samples; its centre is half of that ago
    this.lagMs = (this.analyser.fftSize / this.ctx.sampleRate) * 1000 / 2;

    this.lastLevelAt = 0;
    this.timer = setInterval(() => this._tick(), 12);
    if (this.timeoutMs) this.timeout = setTimeout(() => this._fail("timeout"), this.timeoutMs);
  }

  stop() {
    clearInterval(this.timer);
    clearTimeout(this.timeout);
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    if (this.ctx) this.ctx.close();
    this.stream = this.ctx = null;
  }

  _fail(reason) {
    if (this.done) return;
    this.done = true;
    this.stop();
    this.onFail(reason);
  }

  _tick() {
    if (!this.analyser || this.done) return;
    const s = this.spectrum;
    this.analyser.getFloatFrequencyData(s);

    const band = Array.from(s.subarray(this.noiseRange[0], this.noiseRange[1])).sort((a, b) => a - b);
    const floor = band[Math.floor(band.length / 2)];
    const levels = this.targets.map((bin) => Math.max(s[bin - 1], s[bin], s[bin + 1]) - floor);
    let best = 0;
    for (let i = 1; i < levels.length; i++) if (levels[i] > levels[best]) best = i;
    const symbol = levels[best] >= this.thresholdDb ? best - 1 : null; // -1 sync, 0..7 data, null silence

    const t = performance.now() - this.lagMs;
    this.history.push({ t, levels });
    while (this.history.length && this.history[0].t < t - 1500) this.history.shift();

    this._trackSync(symbol === -1, t);
    this._maybeDecode(t);

    const now = performance.now();
    if (now - this.lastLevelAt > 100) {
      this.lastLevelAt = now;
      let peakBin = this.noiseRange[0];
      for (let i = this.noiseRange[0]; i < this.noiseRange[1]; i++) if (s[i] > s[peakBin]) peakBin = i;
      this.onLevel({ snr: Math.max(0, levels[best]), peakHz: Math.round(peakBin * this.binHz), levels, symbol });
    }
  }

  _trackSync(isSync, t) {
    if (isSync && !this.inSync) { this.inSync = true; this.syncOn = t; }
    if (!isSync && this.inSync) {
      this.inSync = false;
      const dur = t - this.syncOn;
      if (dur >= this.P.SYNC_MS * 0.55 && this.pendingFrame === null) {
        this.pendingFrame = this.syncOn + this.P.SYNC_MS; // anchor on the onset, not the (echo-stretched) end
      }
    }
  }

  _maybeDecode(t) {
    const P = this.P;
    const T = this.pendingFrame;
    if (T === null || t < T + P.SYMBOLS_PER_FRAME * P.SYMBOL_MS + 10) return;
    this.pendingFrame = null;

    const symbols = [];
    for (let i = 0; i < P.SYMBOLS_PER_FRAME; i++) {
      const a = T + (i + 0.2) * P.SYMBOL_MS;
      const b = T + (i + 0.8) * P.SYMBOL_MS;
      const acc = new Array(8).fill(0);
      let n = 0;
      for (const h of this.history) {
        if (h.t < a || h.t > b) continue;
        for (let k = 0; k < 8; k++) acc[k] += Math.max(0, h.levels[k + 1]);
        n++;
      }
      if (!n) return;
      let best = 0;
      for (let k = 1; k < 8; k++) if (acc[k] > acc[best]) best = k;
      symbols.push(best);
    }
    const code = P.decodeSymbols(symbols);
    if (code === null) return;

    this.streak = code === this.lastCandidate ? this.streak + 1 : 1;
    this.lastCandidate = code;
    if (this.streak < this.confirmations) return;
    this.streak = 0;
    if (!this.keepListening) {
      this.done = true;
      clearTimeout(this.timeout);
      this.stop();
    }
    this.onCode(code);
  }
}
window.AudioTokenListener = AudioTokenListener;
