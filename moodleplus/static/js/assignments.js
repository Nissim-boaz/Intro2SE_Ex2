// Assignment page (lecturer): while the AI is checking, update the progress and reload when it's done.
(function () {
  const panel = document.querySelector("[data-ai-running]");
  if (!panel) return;
  const done = panel.querySelector("[data-ai-done]");
  const bar = panel.querySelector("[data-ai-bar]");
  const tick = async () => {
    try {
      const s = await Model.api(panel.dataset.aiStatusUrl);
      if (s.status !== "running") { location.reload(); return; }
      if (done) done.textContent = s.done;
      if (bar && s.total) bar.style.transform = `scaleX(${s.done / s.total})`;
    } catch (_) {}
    setTimeout(tick, 3000);
  };
  setTimeout(tick, 3000);
})();
