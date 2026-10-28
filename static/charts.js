// Hand-rolled SVG progress chart (no library). Fetches /api/history?movement=<id> and draws
// a value-over-time line; tested points are filled, estimated points are hollow. Colours come
// from CSS custom properties so the chart re-themes with dark/light.
(function () {
  "use strict";
  var picker = document.getElementById("movePicker");
  var box = document.getElementById("chart");
  var table = document.getElementById("chartTable");
  if (!picker || !box) return;

  var NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }
  function cssVar(name) {
    return getComputedStyle(document.body).getPropertyValue(name).trim() || "#4cc2ff";
  }

  function render(data) {
    box.textContent = "";
    var pts = (data.series || []).filter(function (p) { return p.value != null; });
    if (!pts.length) { box.textContent = "No data yet for " + data.name + "."; drawTable([]); return; }

    var W = 640, H = 260, PAD = 36;
    var xs = pts.map(function (p) { return new Date(p.date).getTime(); });
    var ys = pts.map(function (p) { return +p.value; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    if (y0 === y1) { y0 -= 1; y1 += 1; }
    if (x0 === x1) { x1 = x0 + 1; }
    var fx = function (t) { return PAD + (W - 2 * PAD) * (t - x0) / (x1 - x0); };
    var fy = function (v) { return H - PAD - (H - 2 * PAD) * (v - y0) / (y1 - y0); };

    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: "100%",
      role: "img", "aria-label": data.name + " progress" });
    var line = cssVar("--line"), accent = cssVar("--accent"), ink = cssVar("--ink"), card = cssVar("--card");

    // axes
    svg.appendChild(el("line", { x1: PAD, y1: H - PAD, x2: W - PAD, y2: H - PAD, stroke: line }));
    svg.appendChild(el("line", { x1: PAD, y1: PAD, x2: PAD, y2: H - PAD, stroke: line }));
    [y0, (y0 + y1) / 2, y1].forEach(function (v) {
      var t = el("text", { x: 4, y: fy(v) + 4, fill: cssVar("--muted"), "font-size": 11 });
      t.textContent = Math.round(v); svg.appendChild(t);
    });

    // path
    var d = pts.map(function (p, i) { return (i ? "L" : "M") + fx(xs[i]) + " " + fy(ys[i]); }).join(" ");
    svg.appendChild(el("path", { d: d, fill: "none", stroke: accent, "stroke-width": 2.5 }));

    // points: tested filled, estimated hollow
    pts.forEach(function (p, i) {
      var tested = p.source === "tested";
      svg.appendChild(el("circle", { cx: fx(xs[i]), cy: fy(ys[i]), r: 4.5,
        fill: tested ? accent : card, stroke: accent, "stroke-width": 2 }));
    });

    box.appendChild(svg);
    drawTable(pts);
  }

  function drawTable(pts) {
    if (!table) return;
    table.querySelectorAll("tr:not(:first-child)").forEach(function (r) { r.remove(); });
    pts.slice().reverse().forEach(function (p) {
      var tr = document.createElement("tr");
      tr.className = "src-" + p.source;
      tr.innerHTML = "<td>" + p.date + "</td><td>" + Math.round(p.value * 10) / 10 +
        "</td><td>" + p.kind + "</td><td><span class='tag " + p.source + "'>" + p.source + "</span></td>";
      table.appendChild(tr);
    });
  }

  function load() {
    fetch("/api/history?movement=" + encodeURIComponent(picker.value))
      .then(function (r) { return r.json(); }).then(render)
      .catch(function () { box.textContent = "Could not load history."; });
  }
  picker.addEventListener("change", load);
  load();
})();
