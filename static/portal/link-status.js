/**
 * Admin overview: live hardware / MQTT link status (polls /api/admin/link-status).
 */
(function () {
  "use strict";

  var root = document.getElementById("link-status");
  if (!root) return;

  var api = root.getAttribute("data-api") || "/api/admin/link-status";
  var rows = root.querySelector("[data-link-rows]");
  var errEl = root.querySelector("[data-link-error]");
  var pollMs = 5000;

  function setError(msg) {
    if (!errEl) return;
    errEl.textContent = msg;
    errEl.hidden = !msg;
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
        setError("");
      })
      .catch(function () {
        setError("Statusabfrage fehlgeschlagen.");
      });
  }

  setInterval(poll, pollMs);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) poll();
  });
})();
