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
    // the same message twice in a row (a double tap, two quick saves) shows once
    if ([...box.children].some((x) => x.textContent === text && !x.classList.contains("hide"))) return;
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
  // a hidden picker (like the chat's "your own photo") is opened by its own button, so it stays hidden
  document.querySelectorAll('input[type="file"]:not([hidden])').forEach(enhanceFileInput);

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

  // ---------- live list filter: search box and funnel, both on the same list, without reloading ----------
  // items are the [data-filter-item] elements (or <option>s) inside the target; data-filter-text, when given, is the
  // whole searchable text (so labels like "מרצה" in a dropdown don't match), and data-filter-tags are the funnel's tags
  const norm = (s) => (s || "").toLowerCase().replace(/[֑-ׇ]/g, "").replace(/\s+/g, " ").trim(); // drop niqqud
  const lists = new Map();
  function filterList(selector) {
    const target = document.querySelector(selector);
    if (!target) return null;
    if (lists.has(target)) return lists.get(target);
    // a <select> filters its options; any other list filters its [data-filter-item]s (and not the
    // options of a dropdown that happens to sit inside a row, like the role picker in the users list)
    const items = [...target.querySelectorAll(target.tagName === "SELECT" ? "option" : "[data-filter-item]")];
    const text = (el) => norm(el.dataset.filterText !== undefined ? el.dataset.filterText : el.textContent);
    const list = { words: [], tag: "", noneText: "", views: [] };
    list.refresh = () => {
      let shown = 0;
      items.forEach((el) => {
        const hay = text(el);
        const tagged = !list.tag || (el.dataset.filterTags || "").split(" ").includes(list.tag);
        // a selected option stays visible, so a search never hides what you already picked
        const match = (tagged && list.words.every((w) => hay.includes(w))) || (el.tagName === "OPTION" && el.selected);
        el.hidden = !match;
        if (match) shown++;
      });
      target.querySelectorAll("optgroup").forEach((g) => { g.hidden = ![...g.children].some((o) => !o.hidden); });
      list.views.forEach((view) => view(shown, items.length));
    };
    lists.set(target, list);
    return list;
  }

  // <input data-filter="#list">; [data-filter-empty] shows when nothing matches, [data-filter-count] says "N מתוך M"
  document.querySelectorAll("input[data-filter]").forEach((input) => {
    const list = filterList(input.dataset.filter);
    if (!list) return;
    const empty = document.querySelector(input.dataset.filterEmpty || "#__none");
    const count = document.querySelector(input.dataset.filterCount || "#__none");
    const emptyText = empty ? empty.textContent : "";
    list.views.push((shown, total) => {
      if (empty) {
        empty.hidden = shown > 0;
        empty.textContent = (!list.words.length && list.noneText) || emptyText;
      }
      if (count) count.textContent = list.words.length || list.tag ? `${shown} מתוך ${total}` : "";
    });
    const run = () => { list.words = norm(input.value).split(" ").filter(Boolean); list.refresh(); };
    input.addEventListener("input", run);
    input.addEventListener("keydown", (e) => { if (e.key === "Escape") { input.value = ""; run(); } });
    run();
  });

  // the funnel: a glass button with a small menu. The choice is remembered for this browser tab, so coming back to
  // the list (or a reload after changing something in it) keeps it
  document.querySelectorAll("[data-funnel]").forEach((box) => {
    const list = filterList(box.dataset.funnel);
    if (!list) return;
    const button = box.querySelector(".funnel-btn");
    const menu = box.querySelector(".funnel-menu");
    const options = [...menu.querySelectorAll("[data-tag]")];
    const chip = document.querySelector(`[data-funnel-chip="${box.dataset.funnel}"]`);
    const key = "moodleplus.funnel." + location.pathname + box.dataset.funnel;
    const open = (on) => {
      menu.hidden = !on;
      button.setAttribute("aria-expanded", on ? "true" : "false");
      if (on) (options.find((o) => o.dataset.tag === list.tag) || options[0]).focus();
    };
    const pick = (tag) => {
      const option = options.find((o) => o.dataset.tag === tag) || options[0];
      list.tag = option.dataset.tag;
      list.noneText = option.dataset.none;
      options.forEach((o) => o.setAttribute("aria-checked", o === option ? "true" : "false"));
      button.classList.toggle("on", !!list.tag);
      if (chip) {
        chip.hidden = !list.tag;
        chip.textContent = option.dataset.label + " ✕";
        chip.setAttribute("aria-label", "בטל את הסינון: " + option.dataset.label);
      }
      try { sessionStorage.setItem(key, list.tag); } catch (_) {}
      list.refresh();
    };
    button.addEventListener("click", () => open(menu.hidden));
    options.forEach((o) => o.addEventListener("click", () => {
      pick(o.dataset.tag);
      open(false);
      button.focus();
      if (location.search) history.replaceState(null, "", location.pathname); // the link's filter no longer applies
    }));
    if (chip) chip.addEventListener("click", () => {
      pick("");
      if (location.search) history.replaceState(null, "", location.pathname);
    });
    box.addEventListener("keydown", (e) => {
      if (menu.hidden) return;
      const at = options.indexOf(document.activeElement);
      if (e.key === "Escape") { open(false); button.focus(); }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        options[(at + (e.key === "ArrowDown" ? 1 : -1) + options.length) % options.length].focus();
      }
    });
    document.addEventListener("click", (e) => { if (!menu.hidden && !box.contains(e.target)) open(false); });
    let start = null;
    if (!("explicit" in box.dataset)) { try { start = sessionStorage.getItem(key); } catch (_) {} }
    pick(start === null ? box.dataset.current : start);
  });

  // ---------- [data-keep-scroll]: a form inside the list reloads the page, but it stays where you were ----------
  document.querySelectorAll("[data-keep-scroll]").forEach((el) => {
    const key = "moodleplus.scroll." + location.pathname + "#" + el.id;
    try {
      const saved = JSON.parse(sessionStorage.getItem(key) || "null");
      sessionStorage.removeItem(key);
      if (saved) { window.scrollTo(0, saved.page); el.scrollTop = saved.list; }
    } catch (_) {}
    el.addEventListener("submit", () => {
      try { sessionStorage.setItem(key, JSON.stringify({ page: window.scrollY, list: el.scrollTop })); } catch (_) {}
    });
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
    // the last tab per course, for this browser tab: "back" from the chat lands where you were, not on "content"
    const lastTabKey = "moodleplus.tab." + location.pathname;
    const lastTab = () => { try { return sessionStorage.getItem(lastTabKey) || ""; } catch (_) { return ""; } };
    const show = (id) => {
      if (!ids.includes(id)) id = ids[0];
      ids.forEach((x) => document.getElementById(x).classList.toggle("tab-on", x === id));
      tabs.forEach((t) => {
        const on = t.dataset.tab === id;
        t.classList.toggle("on", on);
        if (on) t.setAttribute("aria-current", "page"); else t.removeAttribute("aria-current");
      });
      tabbar.style.setProperty("--tab-i", all.indexOf(tabs.find((t) => t.dataset.tab === id)));
      try { sessionStorage.setItem(lastTabKey, id); } catch (_) {}
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
      const start = location.hash.slice(1) || lastTab();
      show(start);
      if (start && !location.hash) history.replaceState(null, "", "#" + start);
      document.body.classList.add("tabbed");
    }
    // coming back from the chat with the phone's back button shows the cached page with the old count
    window.addEventListener("pageshow", (e) => {
      if (e.persisted && tabbar.querySelector(".tab-badge")) location.reload();
    });
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

  // ---------- <input type=checkbox data-remember="key">: keep the last choice per browser ----------
  document.querySelectorAll("input[type=checkbox][data-remember]").forEach((box) => {
    try { box.checked = localStorage.getItem(box.dataset.remember) === "1"; } catch (_) {}
    box.addEventListener("change", () => {
      try { localStorage.setItem(box.dataset.remember, box.checked ? "1" : "0"); } catch (_) {}
    });
  });

  setTimeout(() => document.querySelectorAll(".toasts .toast").forEach((t) => t.classList.add("hide")), 4200);
})();
