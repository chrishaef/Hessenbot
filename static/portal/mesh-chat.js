(function () {
  "use strict";

  const cfg = window.__MESH_CHAT__;
  if (!cfg) return;

  const isDm = cfg.kind === "dm";

  const feed = document.getElementById("mesh-chat-feed");
  const emptyEl = document.getElementById("mesh-chat-empty");
  const countEl = document.getElementById("mesh-chat-count");
  const form = document.getElementById("mesh-chat-form");
  const input = document.getElementById("mesh-chat-input");
  const statusEl = document.getElementById("mesh-chat-status");
  const ifaceSelect = document.getElementById("mesh-chat-iface");
  const sendBtn = document.getElementById("mesh-chat-send");

  const userListEl = document.getElementById("mesh-dm-user-list");
  const userSearchEl = document.getElementById("mesh-dm-user-search");
  const activeLabelEl = document.getElementById("mesh-dm-active-label");

  let lastIso = "";
  let known = new Set();
  let msgCount = 0;
  let lastDateKey = "";
  let lastFullPollAt = 0;
  let lastPollDayKey = "";
  let hideBotReplies = false;

  let allDmMessages = [];
  let allChannelMessages = [];
  let selectedPeerId = "";
  let userSearchQuery = "";

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

  function isBotAutoReply(m) {
    return m.dir === "out" && m.source !== "web";
  }

  function shouldShowMessage(m) {
    return !(hideBotReplies && isBotAutoReply(m));
  }

  function outSenderLabel(m, peer) {
    if (m.source === "web" || peer.short === "Web-Admin") {
      return "Web-Admin";
    }
    return cfg.botName || "Hessenbot";
  }

  function dmPartnerId(m) {
    if (m.peer_id) return String(m.peer_id);
    const longN = (m.peer_long || "").trim().toLowerCase();
    if (longN) return "n:" + longN;
    const shortN = (m.peer_short || "").trim().toLowerCase();
    if (shortN) return "n:" + shortN;
    const peer = (m.peer || "").trim().toLowerCase();
    if (peer) return "p:" + peer;
    return "";
  }

  function dmPartnerLabel(m) {
    if (m.peer_short || m.peer_long) {
      if (m.peer_short && m.peer_long && m.peer_short !== m.peer_long) {
        return m.peer_short + " · " + m.peer_long;
      }
      return m.peer_long || m.peer_short;
    }
    return m.peer || "?";
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
      who = outSenderLabel(m, peer);
    } else {
      who = peer.short || peer.long || "?";
    }

    let tag = "";
    if (kind === "dm") {
      tag = "DM";
    } else if (m.channel_label) {
      tag = m.channel_label;
      if (cfg.filterChannel != null && m.channel != null && Number(m.channel) !== Number(cfg.filterChannel)) {
        tag = tag + " · Ch" + m.channel;
      }
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
    if (out && kind === "dm" && m.source !== "web") {
      const toName = dmPartnerLabel(m);
      if (toName && toName !== "?") {
        const subEl = document.createElement("span");
        subEl.className = "mesh-msg-who-sub";
        subEl.textContent = "An: " + toName;
        head.appendChild(subEl);
      }
    } else if (peer.long && !out && peer.short && peer.long !== peer.short) {
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
    const doScroll = function () {
      feed.scrollTop = feed.scrollHeight;
    };
    if (force) {
      requestAnimationFrame(function () {
        requestAnimationFrame(doScroll);
      });
      return;
    }
    const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 120;
    if (nearBottom) {
      requestAnimationFrame(doScroll);
    }
  }

  function messageSort(a, b) {
    if (a.time !== b.time) {
      return a.time > b.time ? 1 : -1;
    }
    const ar = a.dir === "in" ? 0 : 1;
    const br = b.dir === "in" ? 0 : 1;
    if (ar !== br) return ar - br;
    return String(a.mid || "").localeCompare(String(b.mid || ""));
  }

  function rememberMessage(m, idx) {
    const mid = m.mid || "idx-" + idx + "-" + (m.time || "") + "-" + (m.text || "").slice(0, 40);
    if (known.has(mid)) return null;
    known.add(mid);
    m.mid = mid;
    if (m.time && m.time > lastIso) lastIso = m.time;
    return m;
  }

  function renderFeedMessages(messages, autoScroll) {
    if (!feed) return;
    feed.innerHTML = "";
    lastDateKey = "";

    messages.forEach(function (m) {
      const dk = dateKey(m.time);
      if (dk && dk !== lastDateKey) {
        feed.appendChild(renderDateDivider(dk));
        lastDateKey = dk;
      }
      feed.appendChild(renderMessage(m));
    });

    updateCount(messages.length);
    scrollFeed(!!autoScroll);
  }

  function ingestChannelMessages(messages, replace) {
    if (replace) {
      allChannelMessages = [];
      known.clear();
      lastIso = "";
      lastDateKey = "";
    }

    const before = allChannelMessages.length;
    (messages || []).forEach(function (m, idx) {
      const row = rememberMessage(m, idx);
      if (!row) return;
      allChannelMessages.push(row);
    });

    allChannelMessages.sort(messageSort);
    renderFeedMessages(
      allChannelMessages.filter(shouldShowMessage),
      replace || allChannelMessages.length > before
    );

    if (replace) {
      lastFullPollAt = Date.now();
      lastPollDayKey = todayKey();
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
    ingestChannelMessages(messages, replace);
  }

  function buildUserSummaries() {
    const map = {};
    allDmMessages.forEach(function (m) {
      if (!shouldShowMessage(m)) return;
      const pid = dmPartnerId(m);
      if (!pid) return;
      const cur = map[pid];
      if (!cur || (m.time || "") >= (cur.time || "")) {
        const nodeNum = m.peer_num || (/^\d+$/.test(pid) ? pid : "");
        map[pid] = {
          id: pid,
          nodeNum: nodeNum,
          label: dmPartnerLabel(m),
          time: m.time || "",
          timeShort: m.time_short || "",
          preview: (m.text || "").trim().slice(0, 72),
        };
      } else if (m.peer_num && !cur.nodeNum) {
        cur.nodeNum = m.peer_num;
      }
    });
    return Object.values(map).sort(function (a, b) {
      if (a.time === b.time) return 0;
      return a.time > b.time ? -1 : 1;
    });
  }

  function renderUserList() {
    if (!userListEl) return;
    const q = userSearchQuery.trim().toLowerCase();
    const users = buildUserSummaries().filter(function (u) {
      if (!q) return true;
      return (u.label + " " + u.id + " " + u.preview).toLowerCase().indexOf(q) !== -1;
    });

    userListEl.innerHTML = "";
    if (!users.length) {
      const li = document.createElement("li");
      li.className = "mesh-dm-user-empty";
      li.textContent = q ? "Kein Treffer" : "Noch keine DMs";
      userListEl.appendChild(li);
      return;
    }

    users.forEach(function (u) {
      const li = document.createElement("li");
      li.className = "mesh-dm-user-item" + (u.id === selectedPeerId ? " is-active" : "");
      li.dataset.peerId = u.id;
      li.setAttribute("role", "option");
      li.innerHTML =
        '<span class="mesh-dm-user-name">' + escapeHtml(u.label) + "</span>" +
        '<span class="mesh-dm-user-meta">' +
        escapeHtml(u.timeShort || "") +
        "</span>" +
        '<span class="mesh-dm-user-preview">' +
        escapeHtml(u.preview || "—") +
        "</span>";
      li.addEventListener("click", function () {
        selectPeer(u.id, u.label);
      });
      userListEl.appendChild(li);
    });

    if (!selectedPeerId && users.length) {
      selectPeer(users[0].id, users[0].label, true);
    } else if (selectedPeerId && !users.some(function (u) {
      return u.id === selectedPeerId;
    })) {
      selectPeer(users[0].id, users[0].label, true);
    }
  }

  function selectPeer(peerId, label, silent) {
    selectedPeerId = String(peerId || "");
    if (activeLabelEl) {
      activeLabelEl.textContent = label || selectedPeerId || "Bitte Nutzer wählen";
    }
    renderUserList();
    renderDmFeed();
    if (!silent) {
      if (input) input.focus();
    }
  }

  function renderDmFeed() {
    if (!feed) return;
    feed.innerHTML = "";
    lastDateKey = "";

    if (!selectedPeerId) {
      updateCount(0);
      return;
    }

    const thread = allDmMessages.filter(function (m) {
      return shouldShowMessage(m) && dmPartnerId(m) === selectedPeerId;
    });

    thread.sort(messageSort);

    lastDateKey = "";
    thread.forEach(function (m) {
      const dk = dateKey(m.time);
      if (dk && dk !== lastDateKey) {
        feed.appendChild(renderDateDivider(dk));
        lastDateKey = dk;
      }
      feed.appendChild(renderMessage(m));
      if (m.time && m.time > lastIso) lastIso = m.time;
    });

    updateCount(thread.length);
    scrollFeed(true);
  }

  function ingestDmMessages(messages, replace) {
    if (replace) {
      allDmMessages = [];
      known.clear();
      lastIso = "";
    }

    (messages || []).forEach(function (m, idx) {
      const row = rememberMessage(m, idx);
      if (!row) return;
      allDmMessages.push(row);
    });

    allDmMessages.sort(messageSort);

    renderUserList();
    renderDmFeed();

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
    if (isDm) {
      q.set("limit", initial ? "250" : "250");
    } else {
      q.set("limit", initial ? "150" : "200");
    }
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
        if (isDm) {
          ingestDmMessages(data.messages || [], !!initial);
        } else {
          appendMessages(data.messages || [], !!initial);
        }
      })
      .catch(function (e) {
        setStatus("Abruf fehlgeschlagen: " + e.message, true);
      });
  }

  if (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      const text = (input && input.value.trim()) || "";
      if (!text) return;
      if (isDm && !selectedPeerId) {
        setStatus("Bitte zuerst einen Nutzer links wählen.", true);
        return;
      }
      if (sendBtn) sendBtn.disabled = true;
      const body = new URLSearchParams();
      body.set("text", text);
      body.set("channel", String(cfg.sendChannel != null ? cfg.sendChannel : 1));
      body.set("interface", ifaceSelect ? ifaceSelect.value : String(cfg.interface));
      if (isDm) {
        body.set("kind", "dm");
        const users = buildUserSummaries();
        let destNode = selectedPeerId;
        for (let i = 0; i < users.length; i++) {
          if (users[i].id === selectedPeerId && users[i].nodeNum) {
            destNode = users[i].nodeNum;
            break;
          }
        }
        body.set("dest_node", destNode);
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

  if (userSearchEl) {
    userSearchEl.addEventListener("input", function () {
      userSearchQuery = userSearchEl.value;
      renderUserList();
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

  const hideBotEl = document.getElementById("mesh-chat-hide-bot");
  if (hideBotEl) {
    hideBotEl.addEventListener("change", function () {
      hideBotReplies = !!hideBotEl.checked;
      poll(true);
    });
  }

  poll(true);
  setInterval(function () {
    poll(false);
  }, cfg.pollMs || 3000);
})();
