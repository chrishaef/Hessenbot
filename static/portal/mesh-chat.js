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
  const channelSelect = document.getElementById("mesh-chat-channel");
  const subtitleEl = document.getElementById("mesh-chat-subtitle");
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
  let selectedPeerLabel = "";
  let selectedPeerNodeNum = "";
  let userSearchQuery = "";
  let forceDmScrollOnce = false;
  let nodedbPeers = [];
  let nodedbLoaded = false;

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
    if (m.peer_num) return String(m.peer_num);
    if (m.peer_id) {
      const pid = String(m.peer_id);
      if (/^\d+$/.test(pid)) return pid;
      const looked = lookupNodeNum(pid, dmPartnerLabel(m));
      if (looked) return looked;
      return pid;
    }
    const longN = (m.peer_long || "").trim().toLowerCase();
    if (longN) {
      const looked = lookupNodeNum("n:" + longN, longN);
      if (looked) return looked;
      return "n:" + longN;
    }
    const shortN = (m.peer_short || "").trim().toLowerCase();
    if (shortN && shortN !== "web-admin") {
      const looked = lookupNodeNum("n:" + shortN, shortN);
      if (looked) return looked;
      return "n:" + shortN;
    }
    const peer = (m.peer || "").trim().toLowerCase();
    if (peer && peer !== "web-admin") return "p:" + peer;
    return "";
  }

  function dmThreadMatches(m, peerId, nodeNum) {
    const mid = dmPartnerId(m);
    if (!mid) return false;
    const ids = {};
    function addId(v) {
      if (!v) return;
      ids[String(v)] = true;
    }
    addId(peerId);
    addId(nodeNum);
    addId(m.peer_num);
    if (peerId) {
      addId(lookupNodeNum(peerId, selectedPeerLabel));
    }
    if (mid.indexOf("n:") === 0 || mid.charAt(0) === "!") {
      addId(lookupNodeNum(mid, dmPartnerLabel(m)));
    }
    if (ids[mid]) return true;
    if (m.peer_num && ids[String(m.peer_num)]) return true;
    // Name-only mid vs numeric selection
    const midLooked = lookupNodeNum(mid, dmPartnerLabel(m));
    if (midLooked && ids[midLooked]) return true;
    return false;
  }

  function dmPartnerLabel(m) {
    const shortN = (m.peer_short || "").trim();
    const longN = (m.peer_long || "").trim();
    // Outgoing web DMs used to misuse Web-Admin as peer — ignore that for labels
    if (
      shortN.toLowerCase() === "web-admin" ||
      longN.toLowerCase().indexOf("web-admin") !== -1
    ) {
      if (m.peer_num) return "#" + m.peer_num;
      if (m.peer_id && /^\d+$/.test(String(m.peer_id))) return "#" + m.peer_id;
      return m.peer && String(m.peer).toLowerCase() !== "web-admin" ? m.peer : "?";
    }
    if (shortN || longN) {
      if (shortN && longN && shortN !== longN) {
        return shortN + " · " + longN;
      }
      return longN || shortN;
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

  function isFeedNearBottom() {
    if (!feed) return true;
    return feed.scrollHeight - feed.scrollTop - feed.clientHeight < 120;
  }

  function restoreFeedScroll(prevTop) {
    if (!feed) return;
    requestAnimationFrame(function () {
      feed.scrollTop = prevTop;
    });
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
      // Skip bogus "Web-Admin" threads from older optimistic sends
      if (String(pid).toLowerCase().indexOf("web-admin") !== -1) return;
      const label = dmPartnerLabel(m);
      if (String(label).toLowerCase().indexOf("web-admin") !== -1 && !m.peer_num && !/^\d+$/.test(pid)) {
        return;
      }
      const cur = map[pid];
      if (!cur || (m.time || "") >= (cur.time || "")) {
        const nodeNum =
          m.peer_num ||
          (/^\d+$/.test(pid) ? pid : "") ||
          (cur && cur.nodeNum) ||
          lookupNodeNum(pid, label) ||
          "";
        map[pid] = {
          id: nodeNum || pid,
          nodeNum: nodeNum,
          label: label.indexOf("web-admin") !== -1 && nodeNum ? "#" + nodeNum : label,
          time: m.time || "",
          timeShort: m.time_short || "",
          preview: (m.text || "").trim().slice(0, 72),
          source: "chat",
        };
      } else if (m.peer_num && !cur.nodeNum) {
        cur.nodeNum = m.peer_num;
        cur.id = m.peer_num;
      }
    });
    Object.keys(map).forEach(function (pid) {
      const u = map[pid];
      if (!u.nodeNum) {
        u.nodeNum = lookupNodeNum(u.id, u.label) || "";
        if (u.nodeNum) u.id = u.nodeNum;
      }
    });
    // Collapse name-key and numeric-key for the same node
    const byNum = {};
    Object.keys(map).forEach(function (pid) {
      const u = map[pid];
      if (u.nodeNum) {
        const existing = byNum[u.nodeNum];
        if (!existing || (u.time || "") >= (existing.time || "")) {
          byNum[u.nodeNum] = u;
          byNum[u.nodeNum].id = u.nodeNum;
        } else if ((u.label || "").indexOf("#") !== 0 && (existing.label || "").indexOf("#") === 0) {
          existing.label = u.label;
        }
        delete map[pid];
      }
    });
    Object.keys(byNum).forEach(function (num) {
      map[num] = byNum[num];
    });
    return Object.values(map).sort(function (a, b) {
      if (a.time === b.time) return 0;
      return a.time > b.time ? -1 : 1;
    });
  }

  function lookupNodeNum(peerId, label) {
    const id = String(peerId || "");
    if (/^\d+$/.test(id)) return id;
    if (!nodedbPeers.length) return "";

    if (id.charAt(0) === "!") {
      const hex = id.toLowerCase();
      for (let i = 0; i < nodedbPeers.length; i++) {
        const n = nodedbPeers[i];
        if ((n.search || "").indexOf(hex) !== -1 || String(n.id).toLowerCase() === hex) {
          return n.nodeNum || "";
        }
      }
    }

    const nameKey = id.indexOf("n:") === 0 ? id.slice(2).toLowerCase() : "";
    const labelToken = String(label || "")
      .split(/[·|]/)[0]
      .trim()
      .toLowerCase();
    const tokens = [nameKey, labelToken].filter(Boolean);

    for (let i = 0; i < nodedbPeers.length; i++) {
      const n = nodedbPeers[i];
      const shortN = String(n.short || "").trim().toLowerCase();
      const longN = String(n.long || "").trim().toLowerCase();
      const longFirst = longN.split(/\s+/)[0] || "";
      for (let t = 0; t < tokens.length; t++) {
        const tok = tokens[t];
        if (!tok) continue;
        if (shortN === tok || longN === tok || longFirst === tok) {
          return n.nodeNum || "";
        }
      }
    }
    return "";
  }

  function loadNodedbPeers() {
    if (!isDm || !cfg.apiNodes) return;
    const iface = ifaceSelect ? ifaceSelect.value : String(cfg.interface || 1);
    fetch(cfg.apiNodes + "?iface=" + encodeURIComponent(iface), {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        nodedbPeers = (data.nodes || []).map(function (n) {
          const num = String(n.num || "");
          return {
            id: num,
            nodeNum: num,
            label: n.label || n.short || num,
            short: n.short || "",
            long: n.long || "",
            search: String(n.search || [n.short, n.long, n.num, n.node_id, n.label].join(" ")).toLowerCase(),
            source: "nodedb",
          };
        });
        nodedbLoaded = true;
        if (selectedPeerId && !selectedPeerNodeNum) {
          selectedPeerNodeNum =
            lookupNodeNum(selectedPeerId, selectedPeerLabel) || "";
        }
        if (selectedPeerNodeNum) {
          selectedPeerId = selectedPeerNodeNum;
        }
        renderUserList();
        if (isDm) renderDmFeed(false);
      })
      .catch(function () {
        nodedbPeers = [];
        nodedbLoaded = true;
        renderUserList();
      });
  }

  function buildCombinedUsers() {
    const chats = buildUserSummaries();
    const q = userSearchQuery.trim().toLowerCase();
    const chatNums = {};
    chats.forEach(function (u) {
      if (u.nodeNum) chatNums[String(u.nodeNum)] = true;
      if (/^\d+$/.test(u.id)) chatNums[String(u.id)] = true;
    });

    let list;
    if (!q) {
      list = chats.slice();
    } else {
      list = chats.filter(function (u) {
        return (u.label + " " + u.id + " " + (u.nodeNum || "") + " " + (u.preview || ""))
          .toLowerCase()
          .indexOf(q) !== -1;
      });
      nodedbPeers.forEach(function (n) {
        if (chatNums[n.nodeNum]) return;
        if (n.search.indexOf(q) === -1) return;
        list.push({
          id: n.id,
          nodeNum: n.nodeNum,
          label: n.label,
          time: "",
          timeShort: "NodeDB",
          preview: "Neue DM starten",
          source: "nodedb",
        });
      });
    }

    // Keep an actively selected NodeDB peer visible even without matching search
    if (selectedPeerId && !list.some(function (u) { return u.id === selectedPeerId; })) {
      const fromDb = nodedbPeers.find(function (n) {
        return n.id === selectedPeerId || n.nodeNum === selectedPeerNodeNum;
      });
      if (fromDb || selectedPeerNodeNum) {
        list.unshift({
          id: selectedPeerId,
          nodeNum: selectedPeerNodeNum || (fromDb && fromDb.nodeNum) || selectedPeerId,
          label: selectedPeerLabel || (fromDb && fromDb.label) || selectedPeerId,
          time: "",
          timeShort: "NodeDB",
          preview: "Neue DM starten",
          source: "nodedb",
        });
      }
    }
    return list;
  }

  function renderUserList() {
    if (!userListEl) return;
    const q = userSearchQuery.trim();
    const users = buildCombinedUsers();

    userListEl.innerHTML = "";
    if (!users.length) {
      const li = document.createElement("li");
      li.className = "mesh-dm-user-empty";
      if (q) {
        li.textContent = nodedbLoaded
          ? "Kein Treffer in Chats/NodeDB"
          : "Suche … NodeDB wird geladen";
      } else {
        li.textContent = "Noch keine DMs — Node über Suche wählen";
      }
      userListEl.appendChild(li);
      return;
    }

    users.forEach(function (u) {
      const li = document.createElement("li");
      li.className = "mesh-dm-user-item" + (u.id === selectedPeerId ? " is-active" : "");
      if (u.source === "nodedb") li.className += " mesh-dm-user-item--nodedb";
      li.dataset.peerId = u.id;
      li.setAttribute("role", "option");
      const badge =
        u.source === "nodedb"
          ? '<span class="mesh-dm-user-badge">NodeDB</span>'
          : "";
      li.innerHTML =
        '<span class="mesh-dm-user-name">' + escapeHtml(u.label) + badge + "</span>" +
        '<span class="mesh-dm-user-meta">' +
        escapeHtml(u.timeShort || "") +
        "</span>" +
        '<span class="mesh-dm-user-preview">' +
        escapeHtml(u.preview || "—") +
        "</span>";
      li.addEventListener("click", function () {
        selectPeer(u.id, u.label, false, u.nodeNum);
      });
      userListEl.appendChild(li);
    });

    // Auto-select first chat only; never clobber an explicit NodeDB selection
    if (!selectedPeerId && users.length && users[0].source === "chat") {
      selectPeer(users[0].id, users[0].label, true, users[0].nodeNum);
    }
  }

  function selectPeer(peerId, label, silent, nodeNum) {
    selectedPeerId = String(peerId || "");
    selectedPeerLabel = label || selectedPeerId || "";
    selectedPeerNodeNum = nodeNum
      ? String(nodeNum)
      : (/^\d+$/.test(selectedPeerId) ? selectedPeerId : "");
    if (!selectedPeerNodeNum) {
      selectedPeerNodeNum = lookupNodeNum(selectedPeerId, selectedPeerLabel) || "";
    }
    // Prefer numeric thread key so sends stay in the same conversation
    if (selectedPeerNodeNum) {
      selectedPeerId = selectedPeerNodeNum;
    }
    if (activeLabelEl) {
      activeLabelEl.textContent =
        selectedPeerLabel || selectedPeerId || "Bitte Nutzer wählen";
    }
    renderUserList();
    renderDmFeed(true);
    if (!silent) {
      if (input) input.focus();
    }
  }

  function renderDmFeed(forceBottom) {
    if (!feed) return;
    if (forceDmScrollOnce) {
      forceBottom = true;
      forceDmScrollOnce = false;
    }
    const stickBottom = !!forceBottom || isFeedNearBottom();
    const prevTop = feed.scrollTop;
    feed.innerHTML = "";
    lastDateKey = "";

    if (!selectedPeerId) {
      updateCount(0);
      return;
    }

    const thread = allDmMessages.filter(function (m) {
      return (
        shouldShowMessage(m) &&
        dmThreadMatches(m, selectedPeerId, selectedPeerNodeNum)
      );
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
    if (stickBottom) {
      scrollFeed(true);
    } else {
      restoreFeedScroll(prevTop);
    }
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
    // Stick to bottom only if user was already near bottom (or peer just selected via selectPeer(true)).
    renderDmFeed(false);

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
        let destNode = selectedPeerNodeNum || "";
        if (!destNode) {
          const users = buildCombinedUsers();
          for (let i = 0; i < users.length; i++) {
            if (users[i].id === selectedPeerId && users[i].nodeNum) {
              destNode = users[i].nodeNum;
              break;
            }
          }
        }
        if (!destNode) {
          destNode = lookupNodeNum(selectedPeerId, selectedPeerLabel) || "";
        }
        if (!destNode && /^\d+$/.test(selectedPeerId)) {
          destNode = selectedPeerId;
        }
        // Name-/Hex-Keys an den Server geben, damit resolve_dest_node greifen kann
        if (!destNode && selectedPeerId) {
          destNode = selectedPeerId;
        }
        if (!destNode) {
          setStatus("Bitte Empfänger wählen.", true);
          if (sendBtn) sendBtn.disabled = false;
          return;
        }
        selectedPeerNodeNum = /^\d+$/.test(String(destNode))
          ? String(destNode)
          : selectedPeerNodeNum;
        if (selectedPeerNodeNum) {
          selectedPeerId = selectedPeerNodeNum;
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
            if (isDm) forceDmScrollOnce = true;
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

  function channelOptionLabel(ch) {
    const label = (ch && ch.label) || ("Kanal " + (ch && ch.number));
    return label + " (#" + ch.number + ")";
  }

  function updateChannelSubtitle(num, label) {
    if (!subtitleEl || isDm) return;
    subtitleEl.textContent =
      "Kanäle vom Radio · aktuell #" + num + " · " + (label || ("Kanal " + num));
  }

  function switchChannel(num, label) {
    const n = parseInt(num, 10);
    if (isNaN(n)) return;
    cfg.filterChannel = n;
    cfg.sendChannel = n;
    cfg.channelLabel = label || ("Kanal " + n);
    updateChannelSubtitle(n, cfg.channelLabel);
    // Reset feed for the new channel
    allChannelMessages = [];
    known.clear();
    lastIso = "";
    lastDateKey = "";
    poll(true);
  }

  if (channelSelect && !isDm) {
    channelSelect.addEventListener("change", function () {
      const opt = channelSelect.options[channelSelect.selectedIndex];
      const label = opt ? opt.textContent.replace(/\s*\(#\d+\)\s*$/, "").trim() : "";
      switchChannel(channelSelect.value, label);
    });
  }

  function fillChannelSelect(channels, keepValue) {
    if (!channelSelect || isDm) return;
    const current = keepValue != null ? String(keepValue) : String(cfg.filterChannel);
    channelSelect.innerHTML = "";
    (channels || []).forEach(function (ch) {
      const opt = document.createElement("option");
      opt.value = String(ch.number);
      opt.textContent = channelOptionLabel(ch);
      if (String(ch.number) === current) opt.selected = true;
      channelSelect.appendChild(opt);
    });
    if (!channelSelect.value && channels && channels.length) {
      channelSelect.selectedIndex = 0;
    }
  }

  if (ifaceSelect && cfg.apiChannels && !isDm) {
    ifaceSelect.addEventListener("change", function () {
      const iface = ifaceSelect.value;
      const url =
        cfg.apiChannels +
        "?iface=" +
        encodeURIComponent(iface) +
        "&refresh=1";
      fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          if (data.channels && data.channels.length) {
            fillChannelSelect(data.channels, cfg.filterChannel);
            const opt = channelSelect.options[channelSelect.selectedIndex];
            const label = opt
              ? opt.textContent.replace(/\s*\(#\d+\)\s*$/, "").trim()
              : cfg.channelLabel;
            switchChannel(channelSelect.value, label);
          }
        })
        .catch(function () {
          /* keep existing channel list */
        });
    });
  }

  if (ifaceSelect && isDm) {
    ifaceSelect.addEventListener("change", function () {
      loadNodedbPeers();
    });
  }

  if (isDm) {
    loadNodedbPeers();
  }

  poll(true);
  setInterval(function () {
    poll(false);
  }, cfg.pollMs || 3000);
})();
