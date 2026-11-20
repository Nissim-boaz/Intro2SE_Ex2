// Recordings: cards on the course page and the recording page.
// - chapter / transcript click seeks the player (like YouTube)
// - cards show the video length once the file's metadata loads
// - while a recording is processing, its status is polled and the page reloads when it changes
(function () {
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-seek]");
    if (!btn) return;
    const rec = btn.closest(".recording");
    const player = rec && rec.querySelector(".player video, .player audio");
    if (!player) return;
    player.currentTime = Number(btn.dataset.seek);
    player.play().catch(() => {});
    player.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  const fmt = (sec) => {
    sec = Math.round(sec);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    const mm = h ? String(m).padStart(2, "0") : String(m);
    return (h ? h + ":" : "") + mm + ":" + String(s).padStart(2, "0");
  };
  document.querySelectorAll("[data-thumb]").forEach((media) => {
    const badge = media.closest(".rec-card")?.querySelector("[data-duration]");
    const show = () => {
      if (badge && isFinite(media.duration) && media.duration > 0) {
        badge.textContent = fmt(media.duration);
        badge.hidden = false;
      }
    };
    if (media.readyState >= 1) show();
    else media.addEventListener("loadedmetadata", show, { once: true });
  });

  const upload = document.getElementById("upload-form");
  if (upload) {
    upload.addEventListener("submit", () => {
      const btn = document.getElementById("upload-btn");
      btn.disabled = true;
      btn.textContent = "מעלה…";
    });
  }

  const pending = [...document.querySelectorAll("[data-processing][data-status-url]")];
  if (!pending.length) return;
  async function check() {
    for (const el of pending) {
      try {
        const d = await Model.api(el.dataset.statusUrl);
        if (d.status !== el.dataset.status) {
          location.reload();
          return;
        }
      } catch (_) {}
    }
    setTimeout(check, 5000);
  }
  setTimeout(check, 5000);
})();
