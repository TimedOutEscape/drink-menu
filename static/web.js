document.querySelectorAll(".web-drink[data-dialog]").forEach((trigger) => {
  const dialog = document.getElementById(trigger.dataset.dialog);
  if (!dialog) return;
  trigger.addEventListener("click", () => dialog.showModal());
});

document.querySelectorAll(".drink-dialog").forEach((dialog) => {
  const closeBtn = dialog.querySelector(".dialog-close");
  if (closeBtn) closeBtn.addEventListener("click", () => dialog.close());

  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) dialog.close();
  });
});
