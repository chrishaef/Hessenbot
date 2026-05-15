(function () {
  var STORAGE_KEY = "hessenbot-dash-view";
  var VALID_VIEWS = ["stats", "bbs", "nodedb"];

  function panels() {
    return document.querySelectorAll("[data-dash-panel]");
  }

  function buttons() {
    return document.querySelectorAll(".dash-view-btn[data-dash-view]");
  }

  function normalizeView(view) {
    return VALID_VIEWS.indexOf(view) >= 0 ? view : "stats";
  }

  function resizeCharts() {
    if (typeof Chart === "undefined") return;
    document.querySelectorAll("canvas").forEach(function (canvas) {
      var chart = Chart.getChart(canvas);
      if (chart) chart.resize();
    });
  }

  function setView(view) {
    var target = normalizeView(view);
    panels().forEach(function (panel) {
      var show = panel.getAttribute("data-dash-panel") === target;
      panel.hidden = !show;
    });
    buttons().forEach(function (btn) {
      var active = btn.getAttribute("data-dash-view") === target;
      btn.classList.toggle("dash-view-btn--active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
    try {
      localStorage.setItem(STORAGE_KEY, target);
    } catch (e) {
      /* ignore */
    }
    window.setTimeout(resizeCharts, 50);
  }

  function init() {
    if (!panels().length) return;
    buttons().forEach(function (btn) {
      btn.addEventListener("click", function () {
        setView(btn.getAttribute("data-dash-view"));
      });
    });
    var saved = "stats";
    try {
      var v = localStorage.getItem(STORAGE_KEY);
      if (VALID_VIEWS.indexOf(v) >= 0) saved = v;
    } catch (e) {
      /* ignore */
    }
    var hash = (window.location.hash || "").replace("#", "");
    if (VALID_VIEWS.indexOf(hash) >= 0) saved = hash;
    setView(saved);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
