(function () {
  "use strict";

  const cfg = window.__MESH_CHAT__;
  if (!cfg) return;

  const feed = document.getElementById("mesh-chat-feed");
  const form = document.getElementById("mesh-chat-form");
  const input = document.getElementById("mesh-chat-input");
  const statusEl = document.getElementById("mesh-chat-status");
  const destSelect = document.getElementById("mesh-chat-dest");
  const ifaceSelect = document.getElementById("mesh-chat-iface");
  const sendBtn = document.getElementById("mesh-chat-send");

  let lastIso = "";
  let known = new Set();
  let polling = true;

  function setStatus(msg, isErr) {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.classList.toggle("text-danger", !!isErr);
    statusEl.classList.toggle("text-muted", !isErr);
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderBubble(m) {
    const out = m.dir === "out";
    const kind = m.kind || "channel";
    const peer = m.peer || "?";
    const text = m.text || "";
    const time = m.time_short || "";
    const metaParts = [time];
    if (kind === "channel" && m.channel_label) {
      metaParts.push(m.channel_label);
    } else if (kind === "dm") {
      metaParts.push("DM");
    }
    if (out) {
      metaParts.push("→ gesendet");
    } else {
      metaParts.push("← " + peer);
    }
    const meta = metaParts.join(" · ");
    const cls = out ? "mesh-chat-bubble mesh-chat-bubble--out" : "mesh-chat-bubble mesh-chat-bubble--in";
    const div = document.createElement("div");
    div.className = "mesh-chat-row " + (out ? "mesh-chat-row--out" : "mesh-chat-row--in");
    div.dataset.mid = m.mid || "";
    div.innerHTML =
      '<div class="' +
      cls +
      '">' +
      '<div class="mesh-chat-text">' +
      escapeHtml(text || "—") +
      "</div>" +
      '<div class="mesh-chat-meta">' +
      escapeHtml(meta) +
      "</div></div>";
    return div;
  }

  function scrollFeed(force) {
    if (!feed) return;
    const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
    if (force || nearBottom) {
      feed.scrollTop = feed.scrollHeight;
    }
  }

  function appendMessages(messages, replace) {
    if (!feed || !messages || !messages.length) return;
    if (replace) {
      feed.innerHTML = "";
      known.clear();
    }
    let added = false;
    messages.forEach(function (m) {
      if (!m.mid || known.has(m.mid)) return;
      known.add(m.mid);
      feed.appendChild(renderBubble(m));
      added = true;
      if (m.time && m.time > lastIso) lastIso = m.time;
    });
    if (added) scrollFeed(false);
  }

  function buildQuery(initial) {
    const q = new URLSearchParams();
    q.set("kind", cfg.kind);
    if (cfg.filterChannel != null) q.set("channel", String(cfg.filterChannel));
    if (!initial && lastIso) q.set("after", lastIso);
    q.set("limit", initial ? "80" : "120");
    return q.toString();
  }

  function poll(initial) {
    if (!polling) return;
    const url = cfg.apiMessages + "?" + buildQuery(!!initial);
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (data.error) setStatus(data.error, true);
        else setStatus("Aktualisiert " + new Date().toLocaleTimeString("de-DE"), false);
        appendMessages(data.messages || [], !!initial);
      })
      .catch(function (e) {
        setStatus("Abruf fehlgeschlagen: " + e.message, true);
      });
  }

  function loadNodes() {
    if (!destSelect || cfg.kind !== "dm") return;
    fetch(cfg.apiNodes + "?iface=" + encodeURIComponent(ifaceSelect ? ifaceSelect.value : cfg.interface), {
      credentials: "same-origin",
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        destSelect.innerHTML = "";
        (data.nodes || []).forEach(function (n) {
          const opt = document.createElement("option");
          opt.value = n.num;
          opt.textContent = n.label + " (#" + n.num + ")";
          destSelect.appendChild(opt);
        });
        if (!destSelect.options.length) {
          const opt = document.createElement("option");
          opt.value = "";
          opt.textContent = "Keine Knoten in NodeDB";
          destSelect.appendChild(opt);
        }
      })
      .catch(function () {});
  }

  if (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      const text = (input && input.value.trim()) || "";
      if (!text) return;
      if (sendBtn) sendBtn.disabled = true;
      const body = new URLSearchParams();
      body.set("text", text);
      body.set("channel", String(cfg.sendChannel != null ? cfg.sendChannel : 1));
      body.set("interface", ifaceSelect ? ifaceSelect.value : String(cfg.interface));
      if (cfg.kind === "dm") {
        if (!destSelect || !destSelect.value) {
          setStatus("Bitte Empfänger wählen.", true);
          if (sendBtn) sendBtn.disabled = false;
          return;
        }
        body.set("dest_node", destSelect.value);
      }
      fetch(cfg.apiSend, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          Accept: "application/json",
        },
        body: body.toString(),
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          if (data.ok) {
            if (input) input.value = "";
            setStatus(data.message || "Gesendet", false);
            poll(false);
          } else {
            setStatus(data.message || "Fehler beim Senden", true);
          }
        })
        .catch(function (e) {
          setStatus("Senden fehlgeschlagen: " + e.message, true);
        })
        .finally(function () {
          if (sendBtn) sendBtn.disabled = false;
          if (input) input.focus();
        });
    });
  }

  if (ifaceSelect) {
    ifaceSelect.addEventListener("change", loadNodes);
  }

  poll(true);
  loadNodes();
  setInterval(function () {
    poll(false);
  }, cfg.pollMs || 3000);
})();
