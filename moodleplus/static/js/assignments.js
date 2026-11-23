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

// A grade that already exists: "השתמש במשוב של ה-AI" puts the AI's feedback in the form, to edit before saving.
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-fill-feedback]");
  if (!b) return;
  const form = b.closest(".grade-box").querySelector("form.grade-form:not(.appeal-resolve)");
  if (!form) return;
  const text = form.querySelector("textarea[name=feedback]");
  text.value = b.dataset.fillFeedback;
  text.rows = 8;
  text.dispatchEvent(new Event("input", { bubbles: true })); // wakes the save button
  text.focus();
});
