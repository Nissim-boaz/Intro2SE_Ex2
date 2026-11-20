// Lecturer sample screen: polls the server every second for the QR, the audio symbols and the count.
(function () {
  const stage = document.getElementById("stage");
  const liveUrl = stage.dataset.liveUrl;
  const qr = document.getElementById("qr");
  const timer = document.getElementById("timer");
  const count = document.getElementById("count");
  const enrolled = document.getElementById("enrolled");
  const rotateBar = document.getElementById("rotate-bar");
  const soundState = document.getElementById("sound-state");
  const soundToggle = document.getElementById("sound-toggle");
  const emitter = new AudioTokenEmitter();
  let lastToken = null;
  let pollTimer = null;
  let closed = false;

  function fmt(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function setSound(on) {
    soundState.textContent = on ? "האות הקולי פועל" : "האות הקולי כבוי";
    soundState.className = "pill " + (on ? "pill-ok" : "pill-warn");
    soundToggle.textContent = on ? "השתק" : "הפעל צליל";
  }

  async function startSound() {
    try {
      await emitter.start();
      setSound(true);
    } catch (e) {
      Model.toast("לא הצלחתי להפעיל את הרמקול", "error");
    }
  }

  soundToggle.addEventListener("click", () => {
    if (emitter.running) { emitter.stop(); setSound(false); } else startSound().then(poll);
  });

  function hideOverlay() { document.getElementById("start-overlay").hidden = true; }
  document.getElementById("start-btn").addEventListener("click", async () => {
    hideOverlay();
    try { await document.documentElement.requestFullscreen?.(); } catch (_) {}
    await startSound();
    poll();
  });
  document.getElementById("start-silent").addEventListener("click", hideOverlay);

  function animateRotation(msLeft, windowMs) {
    rotateBar.style.transition = "none";
    rotateBar.style.transform = `scaleX(${msLeft / windowMs})`;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      rotateBar.style.transition = `transform ${msLeft}ms linear`;
      rotateBar.style.transform = "scaleX(0)";
    }));
  }

  function showClosed(n) {
    closed = true;
    emitter.stop();
    document.getElementById("final-count").textContent = n;
    document.getElementById("closed-overlay").hidden = false;
    document.getElementById("start-overlay").hidden = true;
    if (document.fullscreenElement) document.exitFullscreen?.();
  }

  async function poll() {
    clearTimeout(pollTimer);
    if (closed) return;
    try {
      const d = await Model.api(liveUrl);
      count.textContent = d.count;
      enrolled.textContent = d.enrolled ? ` מתוך ${d.enrolled}` : "";
      timer.textContent = fmt(d.seconds_left);
      timer.classList.toggle("ending", d.seconds_left <= 15);
      if (!d.open) return showClosed(d.count);
      if (d.token !== lastToken) {
        lastToken = d.token;
        qr.innerHTML = d.qr_svg;
        qr.classList.remove("flip"); void qr.offsetWidth; qr.classList.add("flip");
        emitter.setSymbols(d.audio_symbols);
        animateRotation(d.window_ms_left, 6000);
      }
      // poll right after the next rotation, and at least once a second for the counter
      pollTimer = setTimeout(poll, Math.min(1000, d.window_ms_left + 60));
    } catch (e) {
      pollTimer = setTimeout(poll, 1500);
    }
  }

  setSound(false);
  poll();
})();
