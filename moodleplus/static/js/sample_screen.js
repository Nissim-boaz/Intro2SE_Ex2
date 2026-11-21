// Lecturer sample screen: polls the server every second for the audio code, the timer and who checked in.
// The code changes on the server's clock; we ask again right after each change and hand it to the emitter.
(function () {
  const stage = document.getElementById("stage");
  const liveUrl = stage.dataset.liveUrl;
  const timer = document.getElementById("timer");
  const count = document.getElementById("count");
  const enrolled = document.getElementById("enrolled");
  const names = document.getElementById("names");
  const namesEmpty = document.getElementById("names-empty");
  const soundState = document.getElementById("sound-state");
  const soundToggle = document.getElementById("sound-toggle");
  const emitter = new AudioTokenEmitter();
  const shown = new Map(); // student id -> <li>
  let lastWindow = null;
  let pollTimer = null;
  let closed = false;
  let firstRender = true;

  function fmt(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function setSound(on) {
    soundState.textContent = on ? "הצליל פועל" : "הצליל כבוי";
    soundState.className = "pill " + (on ? "pill-ok" : "pill-warn");
    soundToggle.textContent = on ? "השתק" : "הפעל צליל";
  }

  async function startSound({ chime = false } = {}) {
    try {
      await emitter.start();
    } catch (e) {}
    if (!emitter.running) {
      emitter.stop(); // let the next click build a fresh AudioContext inside its own gesture
      setSound(false);
      Model.toast("הדפדפן חסם את הצליל. לחץ על ״הפעל צליל״", "error");
      return;
    }
    if (chime) emitter.chime();
    lastWindow = null; // hand the current code to the new emitter on the next poll
    setSound(true);
  }

  soundToggle.addEventListener("click", () => {
    if (emitter.running) { emitter.stop(); setSound(false); } else startSound({ chime: true }).then(poll);
  });

  document.getElementById("start-btn").addEventListener("click", async () => {
    document.getElementById("start-overlay").hidden = true;
    // audio first, while the click still allows it; fullscreen would use that permission up
    const sound = startSound({ chime: true });
    try { await document.documentElement.requestFullscreen?.(); } catch (_) {}
    await sound;
    poll();
  });

  function renderNames(list) {
    const ids = new Set(list.map((a) => a.id));
    shown.forEach((li, id) => { if (!ids.has(id)) { li.remove(); shown.delete(id); } });
    // the list arrives newest first; add the new ones at the top, oldest of them first
    list.slice().reverse().forEach((a) => {
      if (shown.has(a.id)) return;
      const li = document.createElement("li");
      li.className = "name-chip" + (firstRender ? "" : " name-new") + (a.manual ? " name-manual" : "");
      li.textContent = a.name;
      names.prepend(li);
      shown.set(a.id, li);
    });
    namesEmpty.hidden = list.length > 0;
    firstRender = false;
  }

  function showClosed(n) {
    closed = true;
    emitter.stop();
    setSound(false);
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
      enrolled.textContent = d.enrolled ? `מתוך ${d.enrolled}` : "";
      renderNames(d.attendees);
      timer.textContent = fmt(d.seconds_left);
      timer.classList.toggle("ending", d.seconds_left <= 15);
      if (!d.open) return showClosed(d.count);
      if (d.window !== lastWindow) {
        lastWindow = d.window;
        emitter.setSymbols(d.audio_symbols);
      }
      // ask again right after the code changes, and at least once a second for the names and the timer
      pollTimer = setTimeout(poll, Math.min(1000, d.window_ms_left + 60));
    } catch (e) {
      pollTimer = setTimeout(poll, 1500);
    }
  }

  setSound(false);
  poll();
})();
