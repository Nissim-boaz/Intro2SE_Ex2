// Student check-in: listen for the audio code (10s max), then submit.
// If the mic is missing, denied, or decoding fails, we still submit with QR only
// (the server marks it "suspicious" and the lecturer approves it by hand).
(function () {
  const root = document.getElementById("attend");
  const submitUrl = root.dataset.submitUrl;
  const TIMEOUT = 10000;
  let submitted = false;
  let countdown = null;

  function show(step) {
    root.querySelectorAll("[data-step]").forEach((el) => (el.hidden = el.dataset.step !== step));
  }

  const listener = new AudioTokenListener({ timeoutMs: TIMEOUT });
  listener.onLevel = (info) => {
    const pct = Math.min(100, (info.snr / 40) * 100);
    document.getElementById("level-bar").style.transform = `scaleX(${pct / 100})`;
  };
  listener.onCode = (code) => submit({ audio_code: code });
  listener.onFail = () => submit({ audio_failed: true });

  async function submit(body) {
    if (submitted) return;
    submitted = true;
    clearInterval(countdown);
    listener.stop();
    show("sending");
    try {
      const d = await Model.api(submitUrl, { json: body });
      document.getElementById("done-note").textContent =
        d.status === "ok" ? "הנוכחות נקלטה" : "הנוכחות נשמרה, והמרצה יאשר אותה (" + d.reasons.join(", ") + ")";
      show("done");
      navigator.vibrate?.(40);
    } catch (err) {
      document.getElementById("fail-msg").textContent = err.message;
      show("failed");
    }
  }

  document.getElementById("listen-btn").addEventListener("click", async () => {
    show("listening");
    let left = TIMEOUT / 1000;
    const leftEl = document.getElementById("listen-left");
    countdown = setInterval(() => { left = Math.max(0, left - 1); leftEl.textContent = left; }, 1000);
    await listener.start();
  });
  document.getElementById("skip-btn").addEventListener("click", () => submit({ audio_failed: true }));
})();
