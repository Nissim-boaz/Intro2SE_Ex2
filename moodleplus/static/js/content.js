// Content blocks: inline edit toggle and the "add content" dialog.
(function () {
  document.addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit-block]");
    if (edit) document.getElementById("block-" + edit.dataset.editBlock).classList.add("editing");
    const cancel = e.target.closest("[data-cancel-edit]");
    if (cancel) cancel.closest(".block").classList.remove("editing");
  });

  const form = document.getElementById("add-block-form");
  if (!form) return;
  function sync() {
    const kind = form.querySelector("input[name=kind]:checked").value;
    form.querySelectorAll("[data-kind]").forEach((el) => (el.hidden = el.dataset.kind !== kind));
    form.querySelector("[data-label-text]").textContent = kind === "text" ? "טקסט" : "תיאור קצר (לא חובה)";
    form.querySelector("textarea").rows = kind === "text" ? 5 : 2;
    form.querySelector("input[name=url]").required = kind === "link";
    form.querySelector("input[name=file]").required = kind === "file";
  }
  form.addEventListener("change", sync);
  sync();
})();
