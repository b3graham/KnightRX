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

  // Load the official CrossFit.com WOD (reference only) into the Today-page card.
  // Lazy fetch so the page renders instantly and offline/failure degrades gracefully.
  (function () {
    var card = document.getElementById("cfwod");
    if (!card) return;
    var body = card.querySelector(".cfwod-body");
    fetch("/api/crossfit-wod", { headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.ok && d.body) {
          body.textContent = d.body;          // CSS renders newlines (white-space: pre-line)
          body.removeAttribute("data-loading");
        } else {
          showFallback(body, d && d.url);
        }
      })
      .catch(function () { showFallback(body, "https://www.crossfit.com"); });

    function showFallback(el, url) {
      el.removeAttribute("data-loading");
      el.textContent = "Couldn't load today's CrossFit.com WOD. ";
      var a = document.createElement("a");
      a.href = url || "https://www.crossfit.com";
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "View it on crossfit.com ↗";
      el.appendChild(a);
    }
  })();

  // Register the service worker (offline shell). Best-effort.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () {});
    });
  }
})();
