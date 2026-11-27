/**
 * Admin overview: live hardware / MQTT link status (polls /api/admin/link-status).
 */
(function () {
  "use strict";

  var root = document.getElementById("link-status");
  if (!root) return;

  var api = root.getAttribute("data-api") || "/api/admin/link-status";
  var rows = root.querySelector("[data-link-rows]");
  var note = root.querySelector("[data-link-updated]");
  var baseNote = note ? note.textContent : "";
  var pollMs = 5000;

  function clock() {
    var d = new Date();
    function p(n) {
      return (n < 10 ? "0" : "") + n;
    }
    return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }

  function setNote(suffix) {
    if (note) note.textContent = baseNote.trim() + " " + suffix;
  }

  function poll() {
    if (document.hidden) return;
    fetch(api, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (rows && typeof data.html === "string") rows.innerHTML = data.html;
        setNote("Aktualisiert " + clock() + ".");
      })
      .catch(function () {
        setNote("Aktualisierung fehlgeschlagen (" + clock() + ").");
      });
  }

  setInterval(poll, pollMs);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) poll();
  });
})();
