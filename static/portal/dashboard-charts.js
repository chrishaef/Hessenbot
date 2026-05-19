(function () {
  function readChartData() {
    var el = document.getElementById("dash-chart-data");
    if (!el || !el.textContent) {
      return {
        cmdLabels: [],
        cmdValues: [],
        activityLabels: [],
        activityValues: [],
      };
    }
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      console.error("dashboard-charts: invalid JSON", e);
      return {
        cmdLabels: [],
        cmdValues: [],
        activityLabels: [],
        activityValues: [],
      };
    }
  }

  function tickColor() {
    return (
      getComputedStyle(document.documentElement)
        .getPropertyValue("--text-secondary")
        .trim() || "#6c757d"
    );
  }

  function initCharts() {
    if (typeof Chart === "undefined") {
      console.warn("dashboard-charts: Chart.js not loaded");
      return;
    }
    var data = readChartData();
    var gridColor = "rgba(128,128,128,0.15)";
    var ticks = tickColor();
    var legend = { labels: { color: ticks } };

    var cmdEl = document.getElementById("cmdChart");
    if (cmdEl && data.cmdLabels && data.cmdLabels.length) {
      new Chart(cmdEl, {
        type: "bar",
        data: {
          labels: data.cmdLabels,
          datasets: [
            {
              label: "Befehle",
              data: data.cmdValues,
              backgroundColor: "rgba(46, 125, 94, 0.65)",
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: legend },
          scales: {
            x: { ticks: { color: ticks }, grid: { color: gridColor } },
            y: { ticks: { color: ticks }, grid: { color: gridColor }, beginAtZero: true },
          },
        },
      });
    }

    var activityEl = document.getElementById("activityChart");
    if (activityEl && data.activityLabels && data.activityLabels.length) {
      new Chart(activityEl, {
        type: "line",
        data: {
          labels: data.activityLabels,
          datasets: [
            {
              label: "Log-Zeilen / Stunde",
              data: data.activityValues,
              borderColor: "rgba(46, 125, 94, 1)",
              backgroundColor: "rgba(46, 125, 94, 0.15)",
              fill: true,
              tension: 0.25,
              pointRadius: 2,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: legend },
          scales: {
            x: {
              ticks: { color: ticks, maxRotation: 45, minRotation: 0 },
              grid: { color: gridColor },
            },
            y: { ticks: { color: ticks }, grid: { color: gridColor }, beginAtZero: true },
          },
        },
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCharts);
  } else {
    initCharts();
  }
})();
