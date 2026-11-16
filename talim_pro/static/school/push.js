(function () {
  const panel = document.getElementById("push-panel");
  if (!panel) return;
  const button = document.getElementById("push-toggle");
  const status = document.getElementById("push-status");
  const csrf = document.cookie.split("; ").find((c) => c.startsWith("csrftoken="));
  // CSRF cookie HttpOnly bo'lgani uchun token formadan olinadi.
  const token = document.querySelector("input[name=csrfmiddlewaretoken]")?.value || (csrf ? csrf.split("=")[1] : "");

  function b64ToBytes(b64) {
    const pad = "=".repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }
  async function post(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": token }, body: JSON.stringify(body) });
  }
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    status.textContent = "Brauzeringiz push bildirishnomalarni qo‘llamaydi.";
    button.hidden = true;
    return;
  }
  async function refresh() {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    button.dataset.on = sub ? "1" : "0";
    button.textContent = sub ? button.dataset.offLabel : button.dataset.onLabel;
    status.textContent = sub ? status.dataset.onText : status.dataset.offText;
  }
  button.dataset.onLabel = button.textContent;
  button.dataset.offLabel = button.dataset.offLabel || "Push bildirishnomalarni o‘chirish";
  status.dataset.offText = status.textContent;
  status.dataset.onText = status.dataset.onText || "Push bildirishnomalar yoqilgan.";
  button.addEventListener("click", async () => {
    const reg = await navigator.serviceWorker.ready;
    const existing = await reg.pushManager.getSubscription();
    if (existing) {
      await post(panel.dataset.unsubscribeUrl, { endpoint: existing.endpoint });
      await existing.unsubscribe();
    } else {
      if ((await Notification.requestPermission()) !== "granted") { status.textContent = "Ruxsat berilmadi."; return; }
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(panel.dataset.vapid) });
      await post(panel.dataset.subscribeUrl, sub.toJSON());
    }
    refresh();
  });
  refresh();
})();
