(function () {
  const panel = document.getElementById("push-panel");
  if (!panel) return;
  const button = document.getElementById("push-toggle");
  const status = document.getElementById("push-status");
  if (!button || !status) return;
  // CSRF cookie HttpOnly bo'lgani uchun token formadan olinadi.
  const token = document.querySelector("input[name=csrfmiddlewaretoken]")?.value || "";
  const say = (key, fallback) => panel.dataset[key] || fallback;

  function b64ToBytes(b64) {
    const pad = "=".repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }
  async function post(url, body) {
    const response = await fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error("server");
    return response;
  }
  // Service worker tayyor bo'lmasa (masalan, ro'yxatdan o'tmagan), tugma cheksiz kutib qolmasin.
  function ready() {
    return Promise.race([
      navigator.serviceWorker.ready,
      new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 8000)),
    ]);
  }
  function setBusy(busy) {
    button.classList.toggle("is-loading", busy);
    button.disabled = busy;
    if (busy) button.setAttribute("aria-busy", "true"); else button.removeAttribute("aria-busy");
  }

  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    status.textContent = say("unsupportedText", "Brauzeringiz push bildirishnomalarni qo‘llamaydi.");
    button.hidden = true;
    return;
  }

  const onLabel = button.textContent;
  const offLabel = button.dataset.offLabel || "Push bildirishnomalarni o‘chirish";
  const offText = status.textContent;
  const onText = status.dataset.onText || "Push bildirishnomalar yoqilgan.";

  async function refresh() {
    const reg = await ready();
    const sub = await reg.pushManager.getSubscription();
    button.textContent = sub ? offLabel : onLabel;
    status.textContent = sub ? onText : offText;
  }
  function fail() {
    status.textContent = say("errorText", "Amal bajarilmadi. Internet aloqasini tekshirib, qayta urinib ko‘ring.");
  }

  button.addEventListener("click", async () => {
    setBusy(true);
    try {
      const reg = await ready();
      const existing = await reg.pushManager.getSubscription();
      if (existing) {
        await post(panel.dataset.unsubscribeUrl, { endpoint: existing.endpoint });
        await existing.unsubscribe();
      } else {
        if (Notification.permission === "denied" || (await Notification.requestPermission()) !== "granted") {
          status.textContent = say("deniedText", "Ruxsat berilmadi. Brauzer sozlamalarida bildirishnomalarga ruxsat bering.");
          return;
        }
        const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(panel.dataset.vapid) });
        try {
          await post(panel.dataset.subscribeUrl, sub.toJSON());
        } catch (error) {
          await sub.unsubscribe(); // serverda saqlanmagan obuna brauzerda qolib ketmasin
          throw error;
        }
      }
      await refresh();
    } catch (error) {
      fail();
    } finally {
      setBusy(false);
    }
  });
  refresh().catch(() => {});
})();
