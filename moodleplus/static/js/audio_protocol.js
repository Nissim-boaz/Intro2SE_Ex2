// Shared constants for the ultrasonic attendance code.
// One frame = SYNC tone, then 5 symbols (4 data + 1 check), then a short silence.
(function () {
  const DATA_FREQS = [];
  for (let i = 0; i < 8; i++) DATA_FREQS.push(17500 + (i * 2000) / 7); // 17.5k .. 19.5k
  window.AudioProtocol = {
    SYNC_FREQ: 17200,
    DATA_FREQS,
    SYNC_MS: 220,
    SYMBOL_MS: 130,
    GAP_MS: 120,
    SYMBOLS_PER_FRAME: 5,
    frameMs() { return this.SYNC_MS + this.SYMBOL_MS * this.SYMBOLS_PER_FRAME + this.GAP_MS; },
    decodeSymbols(symbols) {
      if (symbols.length !== 5) return null;
      const data = symbols.slice(0, 4);
      if (data.reduce((a, b) => a + b, 0) % 8 !== symbols[4]) return null;
      return data.reduce((code, s) => (code << 3) | s, 0);
    },
  };
})();
