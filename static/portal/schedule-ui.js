/**
 * Adaptive schedule fields for MOTD / News / Scheduler admin forms.
 * Shows interval vs clock based on mode/value; keeps posting the same field names.
 */
(function () {
  "use strict";

  var WEEKDAYS = {
    mon: "montags",
    tue: "dienstags",
    wed: "mittwochs",
    thu: "donnerstags",
    fri: "freitags",
    sat: "samstags",
    sun: "sonntags",
  };

  /** @type {Record<string, {interval?: string, time?: boolean, label: string}>} */
  var META = {
    day: { interval: "Tage", time: true, label: "tage" },
    hour: { interval: "Stunden", time: false, label: "stunden" },
    min: { interval: "Minuten", time: false, label: "minuten" },
    mon: { time: true, label: "weekday" },
    tue: { time: true, label: "weekday" },
    wed: { time: true, label: "weekday" },
    thu: { time: true, label: "weekday" },
    fri: { time: true, label: "weekday" },
    sat: { time: true, label: "weekday" },
    sun: { time: true, label: "weekday" },
    link: { interval: "Stunden", time: false, label: "job-hours" },
    news: { interval: "Stunden", time: false, label: "job-hours" },
    readrss: { interval: "Stunden", time: false, label: "job-hours" },
    sysinfo: { interval: "Stunden", time: false, label: "job-hours" },
    weather: { time: true, label: "job-daily" },
    solar: { time: true, label: "job-daily" },
    custom: { label: "custom" },
  };

  function metaFor(mode) {
    var key = String(mode || "").trim().toLowerCase();
    if (META[key]) return META[key];
    // substring fallbacks for odd scheduler values
    if (key.indexOf("hour") >= 0) return META.hour;
    if (key.indexOf("min") >= 0) return META.min;
    if (key.indexOf("day") >= 0) return META.day;
    for (var d in WEEKDAYS) {
      if (key.indexOf(d) >= 0) return META[d];
    }
    return { label: "unknown" };
  }

  function buildSummary(mode, interval, time) {
    var m = metaFor(mode);
    var n = parseInt(interval, 10);
    if (isNaN(n) || n < 1) n = 1;
    var t = (time || "").trim();
    var key = String(mode || "").trim().toLowerCase();

    if (m.label === "weekday") {
      var day = WEEKDAYS[key] || key;
      return t
        ? "Sendet " + day + " um " + t + "."
        : "Sendet " + day + " — bitte Uhrzeit angeben.";
    }
    if (m.label === "tage") {
      if (n === 1) {
        return t
          ? "Sendet täglich um " + t + "."
          : "Sendet täglich — bitte Uhrzeit angeben.";
      }
      return t
        ? "Sendet alle " + n + " Tage um " + t + "."
        : "Sendet alle " + n + " Tage — bitte Uhrzeit angeben.";
    }
    if (m.label === "stunden" || m.label === "job-hours") {
      return "Sendet alle " + n + " Stunde" + (n === 1 ? "" : "n") + ".";
    }
    if (m.label === "minuten") {
      return "Sendet alle " + n + " Minute" + (n === 1 ? "" : "n") + ".";
    }
    if (m.label === "job-daily") {
      return t
        ? "Job läuft täglich um " + t + "."
        : "Job täglich — bitte Uhrzeit angeben.";
    }
    if (m.label === "custom") {
      return "Eigene Logik in modules/custom_scheduler.py.";
    }
    return "Zeitplan prüfen — Typ „" + (mode || "?") + "“.";
  }

  function bindRoot(root) {
    if (!root || root.getAttribute("data-schedule-bound") === "1") return;
    root.setAttribute("data-schedule-bound", "1");

    var modeEl = root.querySelector("[data-schedule-mode]");
    var intervalRow = root.querySelector("[data-schedule-interval-row]");
    var intervalInput = root.querySelector("[data-schedule-interval]");
    var unitEl = root.querySelector("[data-schedule-unit]");
    var timeRow = root.querySelector("[data-schedule-time-row]");
    var timeInput = root.querySelector("[data-schedule-time]");
    var summaryEl = root.querySelector("[data-schedule-summary]");
    if (!modeEl) return;

    function refresh() {
      var mode = modeEl.value;
      var m = metaFor(mode);
      var showInterval = !!m.interval;
      var showTime = !!m.time;

      if (intervalRow) {
        intervalRow.hidden = !showInterval;
        if (intervalInput) {
          intervalInput.disabled = !showInterval;
          if (showInterval && (!intervalInput.value || intervalInput.value === "0")) {
            intervalInput.value = "1";
          }
        }
      }
      if (unitEl && m.interval) {
        unitEl.textContent = m.interval;
      }
      if (timeRow) {
        timeRow.hidden = !showTime;
        if (timeInput) {
          timeInput.disabled = !showTime;
          timeInput.required = showTime;
        }
      }
      if (summaryEl) {
        summaryEl.textContent = buildSummary(
          mode,
          intervalInput ? intervalInput.value : "1",
          timeInput ? timeInput.value : ""
        );
      }
    }

    modeEl.addEventListener("change", refresh);
    if (intervalInput) intervalInput.addEventListener("input", refresh);
    if (timeInput) timeInput.addEventListener("input", refresh);
    refresh();
  }

  function init() {
    document.querySelectorAll("[data-schedule-ui]").forEach(bindRoot);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
