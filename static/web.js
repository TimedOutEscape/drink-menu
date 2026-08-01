let lockedScrollY = 0;
let modalOpenCount = 0;

function lockScroll() {
  if (modalOpenCount === 0) {
    lockedScrollY = window.scrollY || window.pageYOffset;
    document.body.classList.add("modal-open");
    document.body.style.top = `-${lockedScrollY}px`;
  }
  modalOpenCount += 1;
}

function unlockScroll() {
  modalOpenCount = Math.max(0, modalOpenCount - 1);
  if (modalOpenCount !== 0) return;

  document.body.classList.remove("modal-open");
  document.body.style.top = "";
  window.scrollTo(0, lockedScrollY);
}

document.querySelectorAll(".web-drink[data-dialog]").forEach((trigger) => {
  const dialog = document.getElementById(trigger.dataset.dialog);
  if (!dialog) return;
  trigger.addEventListener("click", () => {
    if (!dialog.open) {
      dialog.showModal();
      lockScroll();
    }
  });
});

document.querySelectorAll(".drink-dialog").forEach((dialog) => {
  const closeBtn = dialog.querySelector(".dialog-close");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      if (dialog.open) dialog.close();
    });
  }

  dialog.addEventListener("close", () => {
    unlockScroll();
  });

  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) dialog.close();
  });
});
