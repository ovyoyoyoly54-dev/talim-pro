(function () {
  "use strict";

  const body = document.body;
  const text = (key, fallback) => (body && body.dataset[key]) || fallback;

  /* ── Baho kiritish: ball ko'rsatkichi ── */
  function initScore() {
    const score = document.querySelector("#id_score");
    const value = document.querySelector("#score-value");
    if (!score || !value) return;
    const update = () => {
      const raw = score.value.trim();
      const n = raw === "" ? Number.NaN : Number(raw);
      value.textContent = Number.isFinite(n) ? String(n) : "—";
      const suffix = document.createElement("small");
      suffix.textContent = "/10";
      value.append(suffix);
      // 8 yoki undan past baho sabab talab qiladi (server tekshiruvi bilan bir xil chegara).
      value.classList.toggle("score-value-low", Number.isFinite(n) && n <= 8);
    };
    score.addEventListener("input", update);
    update();
  }

  /* ── Yon menyu: joriy bo'limni belgilash ── */
  function initNav() {
    const links = Array.from(document.querySelectorAll(".sidebar nav a"));
    const here = window.location.pathname;
    let best = null;
    links.forEach((a) => {
      const label = a.querySelector("span");
      if (label && !a.title) a.title = label.textContent.trim();
      if (a.hash) return; // sahifa ichidagi havola (masalan, Davomatim)
      const path = a.pathname;
      const match = path === here || (path !== "/" && path !== "/dashboard/" && here.startsWith(path));
      if (match && (!best || path.length > best.pathname.length)) best = a;
    });
    if (best) {
      links.forEach((a) => { if (a !== best && !a.hash) { a.classList.remove("active"); a.removeAttribute("aria-current"); } });
      best.classList.add("active");
      best.setAttribute("aria-current", "page");
      if (best.scrollIntoView && window.matchMedia("(max-width: 768px)").matches) {
        best.scrollIntoView({ block: "nearest", inline: "center" });
      }
    }
  }

  function initAnimations() {
    document.querySelectorAll(".panel, .stat-card, .group-card").forEach((el, i) => {
      el.style.animationDelay = `${Math.min(i * 45, 220)}ms`;
      el.classList.add("fade-up");
    });
  }

  /* ── Xabarlar: yopish tugmasi va ekranga olib kelish ── */
  function initMessages() {
    const messages = document.querySelectorAll(".content > .message");
    messages.forEach((message) => {
      if (!message.getAttribute("role")) message.setAttribute("role", message.classList.contains("error") ? "alert" : "status");
      const close = document.createElement("button");
      close.type = "button";
      close.className = "message-close";
      close.setAttribute("aria-label", text("closeLabel", "Yopish"));
      close.textContent = "×";
      close.addEventListener("click", () => message.remove());
      message.append(close);
    });
    // Forma xatosi sahifaning pastida bo'lsa, foydalanuvchi javobni ko'rishi uchun o'sha joyga o'tamiz.
    if (!messages.length && !window.location.hash) {
      const error = document.querySelector(".content .message.error, .field-error, .error-text, .errorlist");
      if (error && error.getBoundingClientRect().top > window.innerHeight) {
        error.scrollIntoView({ block: "center" });
      }
    }
  }

  /* ── Oynalar (dialog) ── */
  function openDialog(dialog) {
    if (typeof dialog.showModal === "function") {
      if (!dialog.open) dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
    const focusTarget = dialog.querySelector("[autofocus], input:not([type=hidden]), select, textarea");
    if (focusTarget) focusTarget.focus();
  }
  function closeDialog(dialog) {
    if (typeof dialog.close === "function" && dialog.open) dialog.close();
    else dialog.removeAttribute("open");
  }
  function initDialogs() {
    document.addEventListener("click", (event) => {
      const opener = event.target.closest("[data-dialog-open]");
      if (opener) {
        const dialog = document.getElementById(opener.dataset.dialogOpen);
        if (dialog) { event.preventDefault(); openDialog(dialog); }
        return;
      }
      const closer = event.target.closest("[data-dialog-close]");
      if (closer) {
        const dialog = closer.closest("dialog");
        if (dialog) { event.preventDefault(); closeDialog(dialog); }
        return;
      }
      // Oynadan tashqariga (fon) bosilsa yopiladi.
      if (event.target instanceof HTMLDialogElement && event.target.classList.contains("app-dialog")) {
        closeDialog(event.target);
      }
    });
    // Server xato qaytarganda forma joylashgan oyna qayta ochiladi.
    document.querySelectorAll("dialog[data-open-on-load]").forEach(openDialog);
  }

  let confirmDialog = null;
  function askConfirm(message, onAccept) {
    if (typeof HTMLDialogElement === "undefined" || typeof HTMLDialogElement.prototype.showModal !== "function") {
      if (window.confirm(message)) onAccept();
      return;
    }
    if (!confirmDialog) {
      confirmDialog = document.createElement("dialog");
      confirmDialog.className = "app-dialog confirm-dialog";
      const box = document.createElement("div");
      box.className = "app-dialog-body";
      const title = document.createElement("h3");
      title.textContent = text("confirmTitle", "Amalni tasdiqlang");
      const copy = document.createElement("p");
      copy.className = "confirm-dialog-text";
      const actions = document.createElement("div");
      actions.className = "app-dialog-actions";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "button button-outline";
      cancel.textContent = text("cancelLabel", "Bekor qilish");
      cancel.addEventListener("click", () => confirmDialog.close("cancel"));
      const accept = document.createElement("button");
      accept.type = "button";
      accept.className = "button button-primary";
      accept.textContent = text("confirmLabel", "Tasdiqlash");
      accept.addEventListener("click", () => confirmDialog.close("ok"));
      actions.append(cancel, accept);
      box.append(title, copy, actions);
      confirmDialog.append(box);
      document.body.append(confirmDialog);
    }
    confirmDialog.querySelector(".confirm-dialog-text").textContent = message;
    confirmDialog.returnValue = "";
    confirmDialog.onclose = () => { if (confirmDialog.returnValue === "ok") onAccept(); };
    confirmDialog.showModal();
  }

  /* ── Formalar: tasdiqlash, takroriy bosishdan himoya va «yuklanmoqda» holati ── */
  function submitButton(form, submitter) {
    return submitter || form.querySelector('button[type="submit"], button:not([type])');
  }
  function release(form) {
    form.dataset.submitting = "";
    form.querySelectorAll(".is-loading").forEach((button) => {
      button.classList.remove("is-loading");
      button.removeAttribute("aria-busy");
    });
  }
  function initForms() {
    document.addEventListener("submit", (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
      const submitter = event.submitter || null;
      const question = (submitter && submitter.dataset.confirm) || form.dataset.confirm;
      if (question && form.dataset.confirmed !== "1") {
        event.preventDefault();
        askConfirm(question, () => {
          form.dataset.confirmed = "1";
          if (typeof form.requestSubmit === "function") form.requestSubmit(submitter || undefined);
          else form.submit();
        });
        return;
      }
      form.dataset.confirmed = "";
      const isPost = (form.getAttribute("method") || "get").toLowerCase() === "post";
      if (isPost && form.dataset.submitting === "1") {
        event.preventDefault(); // ikki marta bosilganda so'rov takrorlanmaydi
        return;
      }
      const button = submitButton(form, submitter);
      if (isPost) form.dataset.submitting = "1";
      if (button) {
        button.classList.add("is-loading");
        button.setAttribute("aria-busy", "true");
      }
      // Fayl yuklab olish (hisobotlar) sahifani almashtirmaydi: tugma holati qaytariladi.
      window.setTimeout(() => release(form), isPost ? 15000 : 2500);
    });
    // Orqaga qaytilganda (bfcache) tugmalar «yuklanmoqda» holatida qolib ketmasin.
    window.addEventListener("pageshow", () => document.querySelectorAll("form").forEach(release));
  }

  /* ── Orqaga tugmasi (xato sahifalari: data-history-back) ── */
  function initHistoryBack() {
    document.addEventListener("click", (event) => {
      const back = event.target.closest("[data-history-back]");
      if (!back) return;
      event.preventDefault();
      if (window.history.length > 1) window.history.back();
      else window.location.href = "/";
    });
  }

  function init() {
    initHistoryBack();
    initScore();
    initNav();
    initAnimations();
    initMessages();
    initDialogs();
    initForms();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
