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

  // ---------- edit mode (lecturer) ----------
  const editForm = document.getElementById("rec-edit");
  if (editForm) {
    // the live "save" button listens to input events; adding/removing rows must tell it too
    const changed = () => editForm.dispatchEvent(new Event("input", { bubbles: true }));
    const player = document.querySelector(".player video, .player audio");

    editForm.addEventListener("click", (e) => {
      const add = e.target.closest("[data-add-row]");
      if (add) {
        const tpl = document.getElementById("tpl-" + add.dataset.addRow);
        add.insertAdjacentHTML("beforebegin", tpl.innerHTML);
        const row = add.previousElementSibling;
        if (add.dataset.addRow === "chapter" && player) row.querySelector(".time-input").value = fmt(player.currentTime || 0);
        row.querySelector('input[type="text"]:not(.time-input)')?.focus();
        changed();
        return;
      }
      const remove = e.target.closest("[data-remove-row]");
      if (remove) { remove.closest(".edit-row").remove(); changed(); return; }
      const take = e.target.closest("[data-take-time]");
      if (take && player) {
        take.closest(".edit-row").querySelector(".time-input").value = fmt(player.currentTime || 0);
        changed();
      }
    });

    // transcript boxes grow with their text
    const grow = (ta) => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; };
    editForm.querySelectorAll(".seg-row textarea").forEach(grow);
    editForm.addEventListener("input", (e) => { if (e.target.matches(".seg-row textarea")) grow(e.target); });

    // don't lose edits by navigating away by mistake
    let submitting = false;
    editForm.addEventListener("submit", () => { submitting = true; });
    window.addEventListener("beforeunload", (e) => {
      const save = editForm.querySelector("button:not([type=button])");
      if (!submitting && save && !save.disabled) { e.preventDefault(); e.returnValue = ""; }
    });
  }

  const upload = document.getElementById("upload-form");
  if (upload) {
    upload.addEventListener("submit", () => {
      const btn = document.getElementById("upload-btn");
      btn.disabled = true;
      btn.textContent = "מעלה…";
    });
  }

  // private feedback is written in the background: reload once it is ready
  const fbPending = document.querySelector("[data-feedback-pending]");
  if (fbPending) {
    const poll = async () => {
      try {
        const d = await Model.api(fbPending.dataset.feedbackUrl);
        if (d.status !== "pending") { location.hash = "feedback"; location.reload(); return; }
      } catch (_) {}
      setTimeout(poll, 4000);
    };
    setTimeout(poll, 4000);
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
