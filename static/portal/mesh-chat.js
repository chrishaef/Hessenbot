(function () {
  "use strict";

  const cfg = window.__MESH_CHAT__;
  if (!cfg) return;

  const feed = document.getElementById("mesh-chat-feed");
  const emptyEl = document.getElementById("mesh-chat-empty");
  const countEl = document.getElementById("mesh-chat-count");
  const form = document.getElementById("mesh-chat-form");
  const input = document.getElementById("mesh-chat-input");
  const statusEl = document.getElementById("mesh-chat-status");
  const destSelect = document.getElementById("mesh-chat-dest");
  const ifaceSelect = document.getElementById("mesh-chat-iface");
  const sendBtn = document.getElementById("mesh-chat-send");

  let lastIso = "";
  let known = new Set();
  let msgCount = 0;
  let lastDateKey = "";

  function setStatus(msg, isErr) {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.classList.toggle("mesh-chat-status--err", !!isErr);
  }

  function updateCount(n) {
    msgCount = n;
    if (!countEl) return;
    countEl.textContent = n === 1 ? "1 Nachricht" : n + " Nachrichten";
    if (emptyEl) emptyEl.hidden = n > 0;
    if (feed) feed.hidden = n === 0;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function splitPeer(peer) {
    const p = (peer || "?").trim();
    const parts = p.split(" · ");
    if (parts.length >= 2) {
      return { short: parts[0], long: parts.slice(1).join(" · ") };
    }
    return { short: p, long: "" };
  }

  function dateKey(iso) {
    if (!iso) return "";
    return iso.slice(0, 10);
  }

  function formatDateLabel(key) {
    if (!key) return "";
    const parts = key.split("-");
    if (parts.length !== 3) return key;
    return parts[2] + "." + parts[1] + "." + parts[0];
  }

  function renderDateDivider(key) {
    const div = document.createElement("div");
    div.className = "mesh-msg-day";
    div.innerHTML = "<span>" + escapeHtml(formatDateLabel(key)) + "</span>";
    return div;
  }

  function renderMessage(m) {
    const out = m.dir === "out";
    const kind = m.kind || "channel";
    const peer = splitPeer(m.peer);
    const text = (m.text || "").trim();
    const time = m.time_short || "";

    let badge = out ? "Gesendet" : "Empfangen";
    let badgeClass = out ? "mesh-msg-badge--out" : "mesh-msg-badge--in";
    let who = "";
    if (out) {
      who = kind === "dm" ? peer.long || peer.short || "DM" : "Web-Admin";
    } else {
      who = peer.short || peer.long || "?";
    }

    let tag = "";
    if (kind === "dm") {
      tag = "DM";
    } else if (m.channel_label) {
      tag = m.channel_label;
    } else if (cfg.channelLabel) {
      tag = cfg.channelLabel;
    }

    const article = document.createElement("article");
    article.className = "mesh-msg " + (out ? "mesh-msg--out" : "mesh-msg--in");
    article.dataset.mid = m.mid || "";

    article.innerHTML =
      '<div class="mesh-msg-head">' +
      '<span class="mesh-msg-badge ' +
      badgeClass +
      '">' +
      escapeHtml(badge) +
      "</span>" +
      '<span class="mesh-msg-who">' +
      escapeHtml(who) +
      "</span>" +
      (peer.long && !out && peer.short
        ? '<span class="mesh-msg-who-sub">' + escapeHtml(peer.long) + "</span>"
        : "") +
      '<time class="mesh-msg-time">' +
      escapeHtml(time) +
      "</time>" +
      "</div>" +
      '<div class="mesh-msg-body">' +
      escapeHtml(text || "—") +
      "</div>" +
      (tag ? '<div class="mesh-msg-tag">' + escapeHtml(tag) + "</div>" : "");

    return article;
  }

  function scrollFeed(force) {
    if (!feed) return;
    const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 100;
    if (force || nearBottom) {
      feed.scrollTop = feed.scrollHeight;
    }
  }

  function appendMessages(messages, replace) {
    if (!feed) return;
    if (replace) {
      feed.innerHTML = "";
      known.clear();
      lastDateKey = "";
      updateCount(0);
    }
    if (!messages || !messages.length) {
      if (replace) updateCount(0);
      return;
    }

    let added = 0;
    messages.forEach(function (m) {
      if (!m.mid || known.has(m.mid)) return;
      known.add(m.mid);

      const dk = dateKey(m.time);
      if (dk && dk !== lastDateKey) {
        feed.appendChild(renderDateDivider(dk));
        lastDateKey = dk;
      }

      feed.appendChild(renderMessage(m));
      added++;
      if (m.time && m.time > lastIso) lastIso = m.time;
    });

    if (added) {
      updateCount(known.size);
      scrollFeed(replace);
    } else if (replace) {
      updateCount(0);
    }
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
          opt.textContent = n.label;
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

  if (input) {
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        form.requestSubmit();
      }
    });
  }

  poll(true);
  loadNodes();
  setInterval(function () {
    poll(false);
  }, cfg.pollMs || 3000);
})();
