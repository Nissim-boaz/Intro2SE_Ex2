// Grades screens: live total of the weights, and a warning before leaving with unsaved typing.
(function () {
  const form = document.querySelector("[data-weights]");
  if (form) {
    const total = form.querySelector("[data-weights-total]");
    const button = form.querySelector("button");
    const inputs = [...form.querySelectorAll("input[type=number]")];
    const initial = inputs.map((i) => i.value).join("|");
    const sync = () => {
      const sum = Math.round(inputs.reduce((s, i) => s + (parseFloat(i.value) || 0), 0) * 100) / 100;
      const over = sum > 100;
      total.textContent = over ? `סך הכול ${sum}%. אפשר לחלק עד 100%` : `סך הכול ${sum}% מתוך 100%`;
      total.classList.toggle("is-over", over);
      button.disabled = over || inputs.map((i) => i.value).join("|") === initial;
      button.classList.toggle("is-idle", button.disabled);
    };
    form.addEventListener("input", sync);
    sync();
  }

  // a wrong grade in a row the search hides: show the row again, otherwise saving just does nothing
  document.addEventListener("invalid", (e) => {
    if (!e.target.closest("[data-filter-item][hidden]")) return;
    document.querySelectorAll("input[data-filter]").forEach((i) => {
      i.value = "";
      i.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }, true);

  document.querySelectorAll("form[data-warn-unsaved]").forEach((f) => {
    let dirty = false;
    f.addEventListener("input", () => { dirty = true; });
    f.addEventListener("submit", () => { dirty = false; });
    window.addEventListener("beforeunload", (e) => { if (dirty) e.preventDefault(); });
  });
})();
