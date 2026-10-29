document.addEventListener("DOMContentLoaded", () => {
  const score = document.querySelector("#id_score");
  const value = document.querySelector("#score-value");
  const section = document.querySelector("#reason-section");
  const checkboxes = [...document.querySelectorAll('input[name="reasons"]')];
  function updateScore() {
    if (!score || !value) return;
    const n = Number(score.value);
    value.innerHTML = `${Number.isFinite(n) ? n : "—"}<small>/10</small>`;
    if (section) section.classList.toggle("reason-required", Number.isFinite(n) && n < 8);
  }
  score?.addEventListener("input", updateScore);
  updateScore();
  document.querySelectorAll(".sidebar nav a").forEach(a => {
    if (a.pathname === window.location.pathname) a.classList.add("active");
  });
  document.querySelectorAll(".panel, .stat-card, .group-card").forEach((el, i) => {
    el.style.animationDelay = `${Math.min(i * 45, 220)}ms`;
    el.classList.add("fade-up");
  });
});
