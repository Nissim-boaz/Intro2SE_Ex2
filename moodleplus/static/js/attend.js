// Student check-in on the course page.
// - Every few seconds we reload the attendance panel, so the "check in" button shows up as soon as
//   the lecturer opens a sample (and goes away when it closes), without refreshing the page.
// - "Check in" asks for the microphone (the browser remembers the answer), listens for the audio
//   code for up to 10 seconds and sends it. No valid code means no check-in; the student can retry.
(function () {
  const wrap = document.getElementById("attend-student");
  if (!wrap) return;
  const panelUrl = wrap.dataset.panelUrl;
  const LISTEN_MS = 10000;
  const REFRESH_MS = 3000;
  let busy = false; // listening or sending: don't swap the panel under the student's finger
  let listener = null;
  let countdown = null;

  const FAIL_TEXT = {
    denied: "צריך לאשר גישה למיקרופון. אפשר לשנות את זה בהגדרות האתר בדפדפן, ואז לנסות שוב",
    unsupported: window.isSecureContext
      ? "הדפדפן לא מאפשר גישה למיקרופון. נסה Chrome או Safari מעודכן"
      : "המיקרופון עובד רק בחיבור מאובטח (https). פתח את האתר בכתובת המאובטחת",
    low_rate: "המיקרופון של המכשיר לא קולט את הצליל. נסה מטלפון אחר או פנה למרצה",
    timeout: "לא נקלט צליל מהכיתה. התקרב לרמקול, ודא שהמרצה הפעיל את הצליל, ונסה שוב",
  };

  const panel = () => wrap.firstElementChild;

  function show(step) {
    panel().querySelectorAll("[data-step]").forEach((el) => (el.hidden = el.dataset.step !== step));
  }

  function fail(text) {
    busy = false;
    clearInterval(countdown);
    panel().querySelector("[data-fail-msg]").textContent = text;
    show("failed");
  }

  async function refresh() {
    if (busy || document.hidden) return;
    try {
      const res = await fetch(panelUrl, { credentials: "same-origin" });
      if (!res.ok) return;
      const tpl = document.createElement("template");
      tpl.innerHTML = (await res.text()).trim();
      const next = tpl.content.firstElementChild;
      // a failed attempt stays on screen until the student retries or the sample changes
      const sameSample = next && panel() && next.dataset.key === panel().dataset.key;
      if (!busy && next && !sameSample) wrap.replaceChildren(next);
    } catch (_) {}
  }

  async function submit(code) {
    clearInterval(countdown);
    show("sending");
    const url = panel().dataset.submitUrl;
    try {
      await Model.api(url, { json: { audio_code: code } });
      navigator.vibrate?.(40);
      busy = false;
      await refresh(); // the server now shows "you're checked in"
    } catch (err) {
      fail(err.message);
      // closed, already checked in or blocked: the panel itself should change
      if ([409, 410, 429].includes(err.status)) setTimeout(() => { busy = false; refresh(); }, 2500);
    }
  }

  async function listen() {
    if (busy) return;
    busy = true;
    show("listening");
    const leftEl = panel().querySelector("[data-left]");
    const levelEl = panel().querySelector("[data-level]");
    let left = LISTEN_MS / 1000;
    leftEl.textContent = left;
    countdown = setInterval(() => { left = Math.max(0, left - 1); leftEl.textContent = left; }, 1000);

    listener = new AudioTokenListener({ timeoutMs: LISTEN_MS });
    listener.onLevel = (info) => { levelEl.style.transform = `scaleX(${Math.min(1, info.snr / 40)})`; };
    listener.onCode = (code) => submit(code);
    listener.onFail = (reason) => fail(FAIL_TEXT[reason] || FAIL_TEXT.timeout);
    await listener.start(); // the permission prompt appears here the first time
  }

  wrap.addEventListener("click", (e) => {
    if (e.target.closest('[data-action="listen"]')) listen();
  });

  setInterval(refresh, REFRESH_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
})();
