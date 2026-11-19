/* TA'LIM PRO — oboi rejimi (kunduzgi / tungi).
   <head> ichida yuklanadi, shuning uchun sahifa ochilganda fon "miltillamaydi".
   Tanlov brauzerda saqlanadi; tanlanmagan bo'lsa tizim rejimi ishlaydi. */
(function () {
  var KEY = "tp-oboi";
  var root = document.documentElement;
  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) {}
  if (saved === "kunduzgi" || saved === "tungi") root.setAttribute("data-oboi", saved);

  function current() {
    var v = root.getAttribute("data-oboi");
    if (v) return v;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "tungi" : "kunduzgi";
  }

  var SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  var MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
  var uz = (root.lang || "uz").indexOf("ru") !== 0;

  function paint(btn) {
    var night = current() === "tungi";
    btn.innerHTML = night ? SUN : MOON;
    var label = night
      ? (uz ? "Kunduzgi rejimga oʻtish" : "Включить дневной режим")
      : (uz ? "Tungi rejimga oʻtish" : "Включить ночной режим");
    btn.setAttribute("aria-label", label);
    btn.title = label;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "oboi-toggle";
    paint(btn);
    btn.addEventListener("click", function () {
      var next = current() === "tungi" ? "kunduzgi" : "tungi";
      root.setAttribute("data-oboi", next);
      try { localStorage.setItem(KEY, next); } catch (e) {}
      paint(btn);
    });
    document.body.appendChild(btn);
    if (window.matchMedia) {
      var mq = window.matchMedia("(prefers-color-scheme: dark)");
      var onChange = function () { paint(btn); };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
    }
  });
})();
