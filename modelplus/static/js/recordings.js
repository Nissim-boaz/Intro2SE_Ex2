// Recordings: chapter click seeks the player (like YouTube), and processing status is polled.
(function () {
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-seek]");
    if (!btn) return;
    const rec = btn.closest(".recording");
    const player = rec && rec.querySelector("video, audio");
    if (!player) return;
    player.currentTime = Number(btn.dataset.seek);
    player.play().catch(() => {});
    player.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  const upload = document.getElementById("upload-form");
  if (upload) {
    upload.addEventListener("submit", () => {
      const btn = document.getElementById("upload-btn");
      btn.disabled = true;
      btn.textContent = "מעלה…";
    });
  }

  const pending = [...document.querySelectorAll(".recording[data-processing]")];
  if (!pending.length) return;
  async function check() {
    for (const el of pending) {
      try {
        const d = await Model.api(el.dataset.statusUrl);
        if (d.status !== el.dataset.status) {
          location.hash = "recordings";
          location.reload();
          return;
        }
      } catch (_) {}
    }
    setTimeout(check, 5000);
  }
  setTimeout(check, 5000);
})();
