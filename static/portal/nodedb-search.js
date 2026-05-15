/**
 * Client-side filter for NodeDB tables (public dashboard + admin).
 */
(function () {
  "use strict";

  function initBlock(block) {
    var input = block.querySelector(".nodedb-search-input");
    if (!input) {
      return;
    }
    var countEl = block.querySelector(".nodedb-search-count");
    var rows = block.querySelectorAll("tbody tr[data-search]");
    var emptyRows = block.querySelectorAll("tr.nodedb-search-empty");
    var total = rows.length;

    function setCount(visible) {
      if (!countEl) {
        return;
      }
      var q = (input.value || "").trim();
      if (!q) {
        countEl.textContent = total ? String(total) : "";
        return;
      }
      countEl.textContent = visible + " / " + total;
    }

    function filter() {
      var q = (input.value || "").trim().toLowerCase();
      var visible = 0;
      rows.forEach(function (tr) {
        var hay = tr.getAttribute("data-search") || "";
        var show = !q || hay.indexOf(q) !== -1;
        tr.hidden = !show;
        if (show) {
          visible += 1;
        }
      });
      emptyRows.forEach(function (tr) {
        tr.hidden = !q || visible > 0;
      });
      setCount(visible);
    }

    input.addEventListener("input", filter);
    input.addEventListener("search", filter);
    filter();
  }

  function boot() {
    document.querySelectorAll(".nodedb-search-block").forEach(initBlock);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
