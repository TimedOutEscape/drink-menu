function buildToastMessage(form, formData) {
  const field = form.dataset.toastField;
  if (field) {
    const verb = form.dataset.toastVerb || "saved";
    const value = (formData.get(field) || "").toString().trim();
    return value ? `${value} ${verb}` : null;
  }
  return form.dataset.toastMessage || null;
}

function showToast(message, isError) {
  const container = document.getElementById("toast-container");
  if (!container || !message) return;
  const toast = document.createElement("div");
  toast.className = "toast" + (isError ? " toast-error" : "");
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("toast-show"));
  setTimeout(() => {
    toast.classList.remove("toast-show");
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}

function showPendingToast(message) {
  const container = document.getElementById("toast-container");
  if (!container || !message) return null;
  const toast = document.createElement("div");
  toast.className = "toast toast-saving";
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("toast-show"));
  return toast;
}

function settleToast(toast, message, isError) {
  if (!toast) return;
  toast.classList.remove("toast-saving", "toast-error");
  if (isError) {
    toast.classList.add("toast-error");
  } else {
    toast.classList.add("toast-saved");
  }
  toast.textContent = message;
  setTimeout(() => {
    toast.classList.remove("toast-show");
    setTimeout(() => toast.remove(), 300);
  }, 1400);
}

async function handleAjaxSubmit(e) {
  const form = e.target;
  if (!form.classList.contains("ajax-form")) return;
  e.preventDefault();

  if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
    return;
  }

  const formData = new FormData(form);
  const toastMessage = buildToastMessage(form, formData);
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;
  const pendingToast = showPendingToast("saving...");

  try {
    const response = await fetch(form.action, { method: "POST", body: formData });
    const html = await response.text();
    const parsed = new DOMParser().parseFromString(html, "text/html");
    const newRoot = parsed.getElementById("app-root");
    const currentRoot = document.getElementById("app-root");
    if (newRoot && currentRoot) {
      currentRoot.innerHTML = newRoot.innerHTML;
      bindAjaxForms(currentRoot);
    }
    window.scrollTo(scrollX, scrollY);
    settleToast(pendingToast, toastMessage || "saved", false);
  } catch (err) {
    settleToast(pendingToast, "Something went wrong — try again", true);
  }
}

function bindAjaxForms(root) {
  root.querySelectorAll("form.ajax-form").forEach((form) => {
    form.addEventListener("submit", handleAjaxSubmit);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindAjaxForms(document.getElementById("app-root"));
});
