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

  // ---------- live list search: <input data-filter="#list"> hides the items that do not match ----------
  // items are the [data-filter-item] elements (or <option>s) inside the target; data-filter-text adds hidden text
  // such as an email. A [data-filter-empty] element next to the list shows when nothing matches.
  const norm = (s) => (s || "").toLowerCase().replace(/[֑-ׇ]/g, "").replace(/\s+/g, " ").trim(); // drop niqqud
  document.querySelectorAll("input[data-filter]").forEach((input) => {
    const target = document.querySelector(input.dataset.filter);
    if (!target) return;
    // a <select> filters its options; any other list filters its [data-filter-item]s (and not the
    // options of a dropdown that happens to sit inside a row, like the role picker in the users list)
    const items = [...target.querySelectorAll(target.tagName === "SELECT" ? "option" : "[data-filter-item]")];
    const empty = document.querySelector(input.dataset.filterEmpty || "#__none");
    const count = document.querySelector(input.dataset.filterCount || "#__none");
    // data-filter-text, when given, is the whole searchable text (so labels like "מרצה" in a dropdown don't match)
    const text = (el) => norm(el.dataset.filterText !== undefined ? el.dataset.filterText : el.textContent);
    const run = () => {
      const words = norm(input.value).split(" ").filter(Boolean);
      let shown = 0;
      items.forEach((el) => {
        const hay = text(el);
        // a selected option stays visible, so a search never hides what you already picked
        const match = !words.length || words.every((w) => hay.includes(w)) || (el.tagName === "OPTION" && el.selected);
        el.hidden = !match;
        if (match) shown++;
      });
      target.querySelectorAll("optgroup").forEach((g) => { g.hidden = ![...g.children].some((o) => !o.hidden); });
      if (empty) empty.hidden = shown > 0;
      if (count) count.textContent = words.length ? `${shown} מתוך ${items.length}` : "";
    };
    input.addEventListener("input", run);
    input.addEventListener("keydown", (e) => { if (e.key === "Escape") { input.value = ""; run(); } });
    run();
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
    const key = "moodleplus.fold." + d.dataset.fold;
    try { if (localStorage.getItem(key) === "closed") d.removeAttribute("open"); } catch (_) {}
    d.addEventListener("toggle", () => {
      try { d.open ? localStorage.removeItem(key) : localStorage.setItem(key, "closed"); } catch (_) {}
    });
  });

  // ---------- back link: full text at the top, a small floating arrow as soon as you scroll ----------
  const backLink = document.querySelector(".back-link");
  if (backLink) {
    // a class toggle is cheap enough to run on every scroll event; no frame throttling needed
    const syncBack = () => backLink.classList.toggle("compact", window.scrollY > 24);
    window.addEventListener("scroll", syncBack, { passive: true });
    syncBack();
  }

  // ---------- bottom tab bar: each tab shows its own section, like switching screens in an app ----------
  // the hash keeps the tab (#attendance after a form redirects back here); tapping the current tab scrolls to top
  const tabbar = document.querySelector("[data-tabbar]");
  if (tabbar) {
    const tabs = [...tabbar.querySelectorAll("a[data-tab]")].filter((t) => document.getElementById(t.dataset.tab));
    const ids = tabs.map((t) => t.dataset.tab);
    const all = [...tabbar.querySelectorAll("a")];
    document.body.classList.add("has-tabbar");
    tabbar.style.setProperty("--tab-n", all.length);
    const show = (id) => {
      if (!ids.includes(id)) id = ids[0];
      ids.forEach((x) => document.getElementById(x).classList.toggle("tab-on", x === id));
      tabs.forEach((t) => {
        const on = t.dataset.tab === id;
        t.classList.toggle("on", on);
        if (on) t.setAttribute("aria-current", "page"); else t.removeAttribute("aria-current");
      });
      tabbar.style.setProperty("--tab-i", all.indexOf(tabs.find((t) => t.dataset.tab === id)));
    };
    tabs.forEach((t) => t.addEventListener("click", (e) => {
      e.preventDefault();
      if (t.classList.contains("on")) { window.scrollTo({ top: 0, behavior: "smooth" }); return; }
      history.replaceState(null, "", "#" + t.dataset.tab); // tabs are not history steps: "back" leaves the course
      show(t.dataset.tab);
      window.scrollTo(0, 0);
    }));
    window.addEventListener("hashchange", () => show(location.hash.slice(1)));
    if (ids.length) {
      show(location.hash.slice(1));
      document.body.classList.add("tabbed");
    }
    requestAnimationFrame(() => tabbar.classList.add("ready")); // the glow slides only after the first paint
  }

  // ---------- theme: auto (follow the device) / light / dark, remembered per browser ----------
  const THEME_KEY = "moodleplus.theme";
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
