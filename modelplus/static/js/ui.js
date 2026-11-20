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

  // <form data-confirm="question" data-confirm-ok="button text"> asks in an in-page dialog,
  // not with the browser's confirm() box
  document.addEventListener("submit", (e) => {
    const form = e.target;
    const msg = form.dataset.confirm;
    if (!msg || form.dataset.confirmed === "1") return;
    e.preventDefault();
    const dialog = document.getElementById("confirm-dialog");
    const ok = document.getElementById("confirm-ok");
    document.getElementById("confirm-text").textContent = msg;
    ok.textContent = form.dataset.confirmOk || "מחק";
    ok.onclick = () => {
      dialog.close();
      form.dataset.confirmed = "1";
      form.requestSubmit ? form.requestSubmit() : form.submit();
    };
    dialog.showModal();
    ok.focus();
  });

  document.addEventListener("click", (e) => {
    const opener = e.target.closest("[data-open-dialog]");
    if (opener) document.getElementById(opener.dataset.openDialog)?.showModal();
    const closer = e.target.closest("[data-close-dialog]");
    if (closer) closer.closest("dialog")?.close();
    // a click on the dim backdrop closes "light" dialogs (not forms, so a stray click never loses typing)
    if (e.target.tagName === "DIALOG" && e.target.hasAttribute("data-light-dismiss")) {
      const r = e.target.getBoundingClientRect();
      const outside = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
      if (outside) e.target.close();
    }
  });

  // close the account menu on outside click
  document.addEventListener("click", (e) => {
    document.querySelectorAll("details.account[open]").forEach((d) => {
      if (!d.contains(e.target)) d.removeAttribute("open");
    });
  });

  // ---------- file pickers: show the chosen file name, with an ✕ to clear it before uploading ----------
  function enhanceFileInput(input) {
    if (input.dataset.enhanced) return;
    input.dataset.enhanced = "1";
    const wrap = document.createElement("div");
    wrap.className = "file-pick";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    wrap.insertAdjacentHTML("beforeend",
      '<button type="button" class="file-pick-btn">בחר קובץ</button>' +
      '<span class="file-pick-name">לא נבחר קובץ</span>' +
      '<button type="button" class="file-pick-clear" aria-label="הסר את הקובץ" title="הסר את הקובץ" hidden>✕</button>');
    const name = wrap.querySelector(".file-pick-name");
    const clear = wrap.querySelector(".file-pick-clear");
    const sync = () => {
      const f = input.files && input.files[0];
      name.textContent = f ? f.name : "לא נבחר קובץ";
      name.classList.toggle("chosen", !!f);
      clear.hidden = !f;
    };
    wrap.querySelector(".file-pick-btn").addEventListener("click", () => input.click());
    clear.addEventListener("click", () => {
      input.value = "";
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    input.addEventListener("change", sync);
    sync();
  }
  document.querySelectorAll('input[type="file"]').forEach(enhanceFileInput);

  // ---------- <form data-live-submit>: the button wakes up only when something changed ----------
  // compares the form to how it looked when the page loaded, so undoing an edit greys it out again
  function snapshot(form) {
    return JSON.stringify([...new FormData(form)].map(([k, v]) => [k, v instanceof File ? v.name + ":" + v.size : v]));
  }
  document.querySelectorAll("form[data-live-submit]").forEach((form) => {
    const button = form.querySelector("button:not([type=button])");
    if (!button) return;
    const initial = snapshot(form);
    const sync = () => {
      const changed = snapshot(form) !== initial;
      button.disabled = !changed;
      button.classList.toggle("is-idle", !changed);
    };
    form.addEventListener("input", sync);
    form.addEventListener("change", sync);
    sync();
  });

  // ---------- <form data-once>: lock the button on the first click so a double click sends one request ----------
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!form.hasAttribute("data-once") || e.defaultPrevented) return;
    if (form.dataset.sent) { e.preventDefault(); return; }
    form.dataset.sent = "1";
    // disable after the browser has read the form, otherwise the click would not submit at all
    setTimeout(() => form.querySelectorAll("button").forEach((b) => {
      b.disabled = true;
      if (!b.classList.contains("icon-btn")) b.innerHTML = '<span class="spinner" aria-hidden="true"></span> ' + b.textContent;
    }), 0);
  });

  // ---------- <details data-fold="name">: remember collapsed sections per browser ----------
  document.querySelectorAll("details[data-fold]").forEach((d) => {
    const key = "modelplus.fold." + d.dataset.fold;
    try { if (localStorage.getItem(key) === "closed") d.removeAttribute("open"); } catch (_) {}
    d.addEventListener("toggle", () => {
      try { d.open ? localStorage.removeItem(key) : localStorage.setItem(key, "closed"); } catch (_) {}
    });
  });

  // ---------- sticky rows: mark them "stuck" once they reach the top (shows the compact back arrow) ----------
  document.querySelectorAll("[data-stuck-watch]").forEach((bar) => {
    const sentinel = bar.previousElementSibling;
    if (!sentinel || !sentinel.classList.contains("nav-sentinel")) return;
    new IntersectionObserver(([entry]) => bar.classList.toggle("stuck", !entry.isIntersecting),
      { rootMargin: "-60px 0px 0px 0px" }).observe(sentinel);
  });

  // ---------- theme: auto (follow the device) / light / dark, remembered per browser ----------
  const THEME_KEY = "modelplus.theme";
  function savedTheme() {
    try { return localStorage.getItem(THEME_KEY) || "auto"; } catch (_) { return "auto"; }
  }
  function applyTheme(choice) {
    const html = document.documentElement;
    html.classList.add("theme-anim");
    setTimeout(() => html.classList.remove("theme-anim"), 350);
    if (choice === "light" || choice === "dark") document.documentElement.setAttribute("data-theme", choice);
    else document.documentElement.removeAttribute("data-theme");
    try {
      if (choice === "auto") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, choice);
    } catch (_) {}
  }
  document.querySelectorAll("[data-theme-choice]").forEach((radio) => {
    radio.checked = radio.value === savedTheme();
    radio.addEventListener("change", () => applyTheme(radio.value));
  });

  setTimeout(() => document.querySelectorAll(".toasts .toast").forEach((t) => t.classList.add("hide")), 4200);
})();
