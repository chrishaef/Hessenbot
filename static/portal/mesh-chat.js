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
  const destSearch = document.getElementById("mesh-chat-dest-search");
  const destCount = document.getElementById("mesh-chat-dest-count");
  const ifaceSelect = document.getElementById("mesh-chat-iface");
  const sendBtn = document.getElementById("mesh-chat-send");

  let lastIso = "";
  let known = new Set();
  let msgCount = 0;
  let lastDateKey = "";
  let allNodes = [];
  let selectedDest = "";
  let lastFullPollAt = 0;
  let lastPollDayKey = "";
  const DEST_MATCH_LIMIT = 200;
  const FULL_REFRESH_MS = 5 * 60 * 1000;

  function setStatus(msg, isErr) {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.classList.toggle("mesh-chat-status--err", !!isErr);
  }

  function updateCount(n) {
    msgCount = n;
    if (countEl) {
      countEl.textContent = n === 1 ? "1 Nachricht" : n + " Nachrichten";
    }
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

    const badge = out ? "Gesendet" : "Empfangen";
    const badgeClass = out ? "mesh-msg-badge--out" : "mesh-msg-badge--in";
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

    const head = document.createElement("div");
    head.className = "mesh-msg-head";

    const badgeEl = document.createElement("span");
    badgeEl.className = "mesh-msg-badge " + badgeClass;
    badgeEl.textContent = badge;

    const whoEl = document.createElement("span");
    whoEl.className = "mesh-msg-who";
    whoEl.textContent = who;

    const timeEl = document.createElement("time");
    timeEl.className = "mesh-msg-time";
    timeEl.textContent = time;

    head.appendChild(badgeEl);
    head.appendChild(whoEl);
    if (peer.long && !out && peer.short && peer.long !== peer.short) {
      const subEl = document.createElement("span");
      subEl.className = "mesh-msg-who-sub";
      subEl.textContent = peer.long;
      head.appendChild(subEl);
    }
    head.appendChild(timeEl);

    const body = document.createElement("div");
    body.className = "mesh-msg-body";
    body.textContent = text || "—";

    article.appendChild(head);
    article.appendChild(body);

    if (tag) {
      const tagEl = document.createElement("div");
      tagEl.className = "mesh-msg-tag";
      tagEl.textContent = tag;
      article.appendChild(tagEl);
    }

    return article;
  }

  function scrollFeed(force) {
    if (!feed) return;
    const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 100;
    if (force || nearBottom) {
      feed.scrollTop = feed.scrollHeight;
    }
  }

  function todayKey() {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  function needsFullRefresh() {
    const day = todayKey();
    if (day !== lastPollDayKey) return true;
    return Date.now() - lastFullPollAt > FULL_REFRESH_MS;
  }

  function appendMessages(messages, replace) {
    if (!feed) return;
    if (replace) {
      feed.innerHTML = "";
      known.clear();
      lastDateKey = "";
      lastIso = "";
    }
    if (!messages || !messages.length) {
      if (replace) updateCount(0);
      return;
    }

    let added = 0;
    messages.forEach(function (m, idx) {
      const mid = m.mid || "idx-" + idx + "-" + (m.time || "") + "-" + (m.text || "").slice(0, 40);
      if (known.has(mid)) return;
      known.add(mid);
      m.mid = mid;

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

    if (replace) {
      lastFullPollAt = Date.now();
      lastPollDayKey = todayKey();
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
    if (!initial && needsFullRefresh()) {
      initial = true;
    }
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

  function nodeHay(n) {
    if (n.search) return n.search;
    return (n.label + " " + n.num + " " + (n.node_id || "") + " " + (n.short || "") + " " + (n.long || "")).toLowerCase();
  }

  function updateDestCount(visible, total, query) {
    if (!destCount) return;
    if (!total) {
      destCount.textContent = "—";
      return;
    }
    if (!query) {
      destCount.textContent = String(total);
      destCount.title = total + " Knoten — Suche eingeben";
      return;
    }
    destCount.textContent = visible + " / " + total;
    destCount.title = visible + " Treffer von " + total;
  }

  function setDestListOpen(open) {
    if (!destSelect) return;
    destSelect.classList.toggle("is-open", !!open);
  }

  function renderDestOptions() {
    if (!destSelect || cfg.kind !== "dm") return;
    const query = destSearch ? destSearch.value.trim().toLowerCase() : "";
    const prev = selectedDest || destSelect.value;
    destSelect.innerHTML = "";

    if (!query) {
      setDestListOpen(false);
      updateDestCount(0, allNodes.length, "");
      return;
    }

    setDestListOpen(true);

    if (!allNodes.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Keine Knoten in NodeDB";
      destSelect.appendChild(opt);
      updateDestCount(0, 0, query);
      return;
    }

    const allMatched = allNodes.filter(function (n) {
      return nodeHay(n).indexOf(query) !== -1;
    });
    const matched = allMatched.slice(0, DEST_MATCH_LIMIT);

    if (!matched.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Kein Treffer — Suchbegriff anpassen";
      destSelect.appendChild(opt);
      updateDestCount(0, allNodes.length, query);
      return;
    }

    matched.forEach(function (n) {
      const opt = document.createElement("option");
      opt.value = n.num;
      const idHint = n.node_id ? " · " + n.node_id : "";
      opt.textContent = n.label + " (#" + n.num + idHint + ")";
      destSelect.appendChild(opt);
    });

    if (allMatched.length > DEST_MATCH_LIMIT) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.disabled = true;
      opt.textContent = "… " + (allMatched.length - DEST_MATCH_LIMIT) + " weitere — Suche verfeinern";
      destSelect.appendChild(opt);
    }

    if (prev && matched.some(function (n) {
      return n.num === prev;
    })) {
      destSelect.value = prev;
      selectedDest = prev;
    } else if (matched.length === 1) {
      destSelect.value = matched[0].num;
      selectedDest = matched[0].num;
    }

    updateDestCount(matched.length, allNodes.length, query);
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
        allNodes = data.nodes || [];
        renderDestOptions();
      })
      .catch(function () {
        allNodes = [];
        renderDestOptions();
      });
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
        const dest = selectedDest || (destSelect && destSelect.value);
        if (!dest) {
          setStatus("Bitte Empfänger wählen.", true);
          if (sendBtn) sendBtn.disabled = false;
          return;
        }
        body.set("dest_node", dest);
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
    ifaceSelect.addEventListener("change", function () {
      if (destSearch) destSearch.value = "";
      selectedDest = "";
      loadNodes();
    });
  }

  if (destSearch) {
    destSearch.addEventListener("input", renderDestOptions);
    destSearch.addEventListener("search", renderDestOptions);
  }

  if (destSelect) {
    destSelect.addEventListener("change", function () {
      if (destSelect.value) selectedDest = destSelect.value;
    });
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
