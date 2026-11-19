// Shared UI helpers: toasts, confirm buttons, JSON fetch.
(function () {
  const Model = (window.Model = window.Model || {});

  Model.toast = function (text, kind) {
    let box = document.querySelector(".toasts");
    if (!box) {
      box = document.createElement("div");
      box.className = "toasts";
      box.setAttribute("role", "status");
      document.body.appendChild(box);
    }
    const t = document.createElement("div");
    t.className = "toast" + (kind === "error" ? " toast-error" : "");
    t.textContent = text;
    box.appendChild(t);
    setTimeout(() => t.classList.add("hide"), 3600);
    setTimeout(() => t.remove(), 4000);
  };

  Model.api = async function (url, options = {}) {
    const opts = { credentials: "same-origin", headers: {}, ...options };
    if (opts.json !== undefined) {
      opts.method = opts.method || "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    const res = await fetch(url, opts);
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok || data.ok === false) {
      const err = new Error(data.error || "משהו השתבש. נסה שוב");
      err.status = res.status;
      throw err;
    }
    return data;
  };

  Model.escape = function (s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  };

  document.addEventListener("submit", (e) => {
    const msg = e.target.dataset.confirm;
    if (msg && !confirm(msg)) e.preventDefault();
  });

  document.addEventListener("click", (e) => {
    const opener = e.target.closest("[data-open-dialog]");
    if (opener) document.getElementById(opener.dataset.openDialog)?.showModal();
    const closer = e.target.closest("[data-close-dialog]");
    if (closer) closer.closest("dialog")?.close();
  });

  // close the account menu on outside click
  document.addEventListener("click", (e) => {
    document.querySelectorAll("details.account[open]").forEach((d) => {
      if (!d.contains(e.target)) d.removeAttribute("open");
    });
  });

  setTimeout(() => document.querySelectorAll(".toasts .toast").forEach((t) => t.classList.add("hide")), 4200);
})();
