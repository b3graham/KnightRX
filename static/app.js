// Backyard Box — minimal vanilla JS: live range outputs, destructive-form confirm,
// a brief PR celebration, and service-worker registration for offline use.
(function () {
  "use strict";

  // Range sliders mirror their value into a linked <output>.
  document.addEventListener("input", function (e) {
    var el = e.target;
    if (el.type === "range" && el.dataset.output) {
      var out = document.getElementById(el.dataset.output);
      if (out) out.textContent = el.value;
    }
  });

  // Confirm destructive / finalizing forms before submit.
  document.addEventListener("submit", function (e) {
    var msg = e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // Celebrate a new PR when the flash says so.
  try {
    var flash = document.querySelector(".flash.ok");
    if (flash && /new pr/i.test(flash.textContent)) {
      flash.textContent = "🎉 " + flash.textContent;
      flash.style.transition = "transform .2s";
      flash.style.transform = "scale(1.03)";
      setTimeout(function () { flash.style.transform = "scale(1)"; }, 220);
    }
  } catch (_) {}

  // Register the service worker (offline shell). Best-effort.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () {});
    });
  }
})();
