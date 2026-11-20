// AudioTokenEmitter — plays the rotating attendance code through the lecturer's speakers.
//
//   const emitter = new AudioTokenEmitter();
//   await emitter.start();          // must be called from a click (browser autoplay rules)
//   emitter.setSymbols([3,1,7,0,3]); // from the server, changes every window
//   emitter.stop();
class AudioTokenEmitter {
  constructor({ volume = 0.6 } = {}) {
    this.P = window.AudioProtocol;
    this.volume = volume;
    this.symbols = null;
    this.ctx = null;
    this.timer = null;
    this.nextFrameAt = 0;
  }

  get running() { return !!this.ctx && this.ctx.state === "running"; }

  async start() {
    if (this.ctx) return;
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    await this.ctx.resume();
    this.osc = this.ctx.createOscillator();
    this.gain = this.ctx.createGain();
    this.gain.gain.value = 0;
    this.osc.connect(this.gain).connect(this.ctx.destination);
    this.osc.start();
    this.nextFrameAt = this.ctx.currentTime + 0.1;
    // schedule frames a little ahead of the audio clock
    this.timer = setInterval(() => this._pump(), 100);
  }

  setSymbols(symbols) { this.symbols = symbols ? symbols.slice() : null; }

  setVolume(v) { this.volume = v; }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
    if (this.ctx) { this.ctx.close(); this.ctx = null; }
  }

  _pump() {
    if (!this.ctx) return;
    while (this.nextFrameAt < this.ctx.currentTime + 0.6) {
      const frameSec = this.P.frameMs() / 1000;
      if (this.symbols) this._scheduleFrame(this.nextFrameAt, this.symbols);
      this.nextFrameAt += frameSec;
    }
  }

  _scheduleFrame(t0, symbols) {
    const P = this.P;
    const f = this.osc.frequency;
    const g = this.gain.gain;
    const ramp = 0.006; // short fades so the tone switch does not click
    let t = t0;
    const tone = (freq, ms) => {
      const d = ms / 1000;
      f.setValueAtTime(freq, t);
      g.setValueAtTime(0, t);
      g.linearRampToValueAtTime(this.volume, t + ramp);
      g.setValueAtTime(this.volume, t + d - ramp);
      g.linearRampToValueAtTime(0, t + d);
      t += d;
    };
    tone(P.SYNC_FREQ, P.SYNC_MS);
    symbols.forEach((s) => tone(P.DATA_FREQS[s], P.SYMBOL_MS));
  }
}
window.AudioTokenEmitter = AudioTokenEmitter;
