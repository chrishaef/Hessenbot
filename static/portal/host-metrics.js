/**
 * Admin overview: host CPU % / temp sparklines + live refresh.
 */
(function () {
  "use strict";

  var root = document.getElementById("host-metrics");
  if (!root) return;

  var api = root.getAttribute("data-api") || "/api/admin/host-metrics";
  var bootEl = document.getElementById("host-metrics-bootstrap");
  var pollMs = 5000;
  var lastData = null;

  function fmtCpu(v) {
    return v == null || v === "" ? "—" : Number(v).toFixed(1) + " %";
  }
  function fmtTemp(v) {
    return v == null || v === "" ? "—" : Number(v).toFixed(1) + " °C";
  }

  function applyText(data) {
    var map = {
      uptime: data.uptime,
      memory: data.memory,
      disk: data.disk,
      cpu_pct: fmtCpu(data.cpu_pct),
      cpu_temp_c: fmtTemp(data.cpu_temp_c),
    };
    Object.keys(map).forEach(function (key) {
      var el = root.querySelector('[data-host="' + key + '"]');
      if (el && map[key] != null) el.textContent = map[key];
    });
  }

  function sparkColor() {
    var dark =
      document.documentElement.getAttribute("data-bs-theme") === "dark";
    return dark ? "#75b798" : "#198754";
  }

  function drawSpark(canvas, values, fixedMin, fixedMax) {
    if (!canvas || !canvas.getContext) return;
    var dpr = window.devicePixelRatio || 1;
    var cssW = canvas.clientWidth || 320;
    var cssH = canvas.clientHeight || 48;
    canvas.width = Math.max(1, Math.floor(cssW * dpr));
    canvas.height = Math.max(1, Math.floor(cssH * dpr));
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    var nums = (values || []).filter(function (v) {
      return typeof v === "number" && !isNaN(v);
    });
    if (nums.length < 2) {
      ctx.fillStyle = "rgba(108,117,125,0.45)";
      ctx.font = "11px system-ui,sans-serif";
      ctx.fillText("Verlauf wird aufgebaut …", 4, cssH / 2 + 4);
      return;
    }

    var min = fixedMin != null ? fixedMin : Math.min.apply(null, nums);
    var max = fixedMax != null ? fixedMax : Math.max.apply(null, nums);
    if (max - min < 1e-6) {
      min -= 1;
      max += 1;
    }
    var pad = 3;
    var w = cssW - pad * 2;
    var h = cssH - pad * 2;
    var color = sparkColor();

    ctx.beginPath();
    nums.forEach(function (v, i) {
      var x = pad + (i / (nums.length - 1)) * w;
      var y = pad + h - ((v - min) / (max - min)) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.75;
    ctx.lineJoin = "round";
    ctx.stroke();

    ctx.lineTo(pad + w, pad + h);
    ctx.lineTo(pad, pad + h);
    ctx.closePath();
    if (color.charAt(0) === "#") {
      var hex = color.slice(1);
      var r = parseInt(hex.slice(0, 2), 16);
      var g = parseInt(hex.slice(2, 4), 16);
      var b = parseInt(hex.slice(4, 6), 16);
      ctx.fillStyle = "rgba(" + r + "," + g + "," + b + ",0.12)";
    } else {
      ctx.fillStyle = "rgba(25,135,84,0.12)";
    }
    ctx.fill();
  }

  function render(data) {
    lastData = data;
    applyText(data);
    var hist = data.history || [];
    var cpuVals = hist.map(function (h) {
      return h.cpu_pct;
    });
    var tempVals = hist.map(function (h) {
      return h.cpu_temp_c;
    });
    drawSpark(root.querySelector('[data-spark="cpu_pct"]'), cpuVals, 0, 100);
    var tNums = tempVals.filter(function (v) {
      return typeof v === "number";
    });
    var tMin = tNums.length ? Math.min.apply(null, tNums) - 2 : 0;
    var tMax = tNums.length ? Math.max.apply(null, tNums) + 2 : 100;
    drawSpark(
      root.querySelector('[data-spark="cpu_temp_c"]'),
      tempVals,
      tMin,
      tMax
    );
  }

  function poll() {
    fetch(api, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(render)
      .catch(function () {});
  }

  try {
    if (bootEl && bootEl.textContent) {
      var boot = JSON.parse(bootEl.textContent);
      if (boot.sample_sec) {
        pollMs = Math.max(3000, Number(boot.sample_sec) * 1000);
      }
      render(boot);
    }
  } catch (e) {}

  setInterval(poll, pollMs);
  window.addEventListener("resize", function () {
    if (lastData) render(lastData);
  });
})();
