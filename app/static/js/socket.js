/*
 * Real-time connection to the server using the Socket.IO client library
 * (served locally from /static/js/vendor, so it works without internet).
 *
 * - io() opens an HTTP long-polling connection first, then upgrades it to a
 *   WebSocket. If WebSockets are blocked, it keeps working over polling.
 * - The browser sends the login cookie with the handshake; the server refuses
 *   the connection if the user is not logged in.
 * - After a disconnection the client reconnects automatically and pages
 *   re-fetch their data ("resync"), because events sent while offline are lost.
 * - Every server event carries an event_id; duplicates are ignored.
 */
"use strict";

const Realtime = (() => {
  const SERVER_EVENTS = [
    "ticket:created", "ticket:updated", "ticket:message", "notification", "stats:updated",
    "announcement:created", "announcement:updated", "announcement:deleted", "presence:updated",
  ];
  const STATE_LABELS = {
    connecting: "Connecting…",
    connected: "Connected",
    reconnecting: "Reconnecting…",
    offline: "Disconnected",
    expired: "Session ended",
  };

  const listeners = new Map();
  const seenIds = new Set();
  const seenOrder = [];
  const joinedTickets = new Set();
  let socket = null;
  let everConnected = false;
  let rttTimer = null;
  let lastRtt = null;

  const pill = document.getElementById("conn");
  const label = document.getElementById("conn-label");
  const meta = document.getElementById("conn-meta");

  function on(event, handler) {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event).add(handler);
  }

  function dispatch(event, payload) {
    (listeners.get(event) || []).forEach((handler) => {
      try {
        handler(payload);
      } catch (error) {
        console.error(`Error in ${event} handler`, error);
      }
    });
  }

  function isDuplicate(payload) {
    const id = payload && payload.event_id;
    if (!id) return false;
    if (seenIds.has(id)) return true;
    seenIds.add(id);
    seenOrder.push(id);
    if (seenOrder.length > 500) seenIds.delete(seenOrder.shift());
    return false;
  }

  function transportName() {
    return socket && socket.io.engine && socket.io.engine.transport ? socket.io.engine.transport.name : "";
  }

  function setStatus(state, detail = "") {
    if (!pill) return;
    pill.dataset.state = state;
    if (state === "expired") {
      label.textContent = "";
      label.append(STATE_LABELS.expired, " · ", App.h("a", { href: "/login" }, "log in again"));
    } else {
      label.textContent = STATE_LABELS[state];
    }
    if (state === "connected") {
      const transport = transportName() === "websocket" ? "WebSocket" : "HTTP polling";
      meta.textContent = lastRtt === null ? transport : `${transport} · ${lastRtt} ms`;
      pill.title = `Live connection over ${transport}. Round-trip time measured with a ping event every 10 s.`;
    } else {
      meta.textContent = detail;
      pill.title = "Real-time connection to the helpdesk server";
    }
  }

  /** Emit an event and wait for the server's acknowledgement (resolves with data). */
  function emit(event, data, timeoutMs = 8000) {
    return new Promise((resolve, reject) => {
      if (!socket || !socket.connected) {
        reject(new App.ApiError("Not connected to the server."));
        return;
      }
      socket.timeout(timeoutMs).emit(event, data, (timeoutError, response) => {
        if (timeoutError) {
          reject(new App.ApiError("The server did not answer in time."));
        } else if (!response || !response.ok) {
          const error = (response && response.error) || {};
          reject(new App.ApiError(error.message || "The server rejected the request.", 0, error.fields || {}));
        } else {
          resolve(response.data);
        }
      });
    });
  }

  /** Measure round-trip time: send a ping event and time the acknowledgement. */
  function measureRtt() {
    const started = performance.now();
    emit("net:ping", {}, 5000)
      .then(() => {
        lastRtt = Math.max(1, Math.round(performance.now() - started));
        if (socket.connected) setStatus("connected");
      })
      .catch(() => { /* a missed ping is reported by the heartbeat/disconnect logic */ });
  }

  function joinTicketRoom(ticketId) {
    emit("ticket:join", { ticket_id: ticketId }).catch((error) => {
      App.toast(`Live updates for this ticket are unavailable: ${error.message}`, { type: "error" });
    });
  }

  /** Subscribe to one ticket's live events (re-joined automatically after reconnects). */
  function joinTicket(ticketId) {
    joinedTickets.add(ticketId);
    if (socket && socket.connected) joinTicketRoom(ticketId);
  }

  function connect() {
    if (typeof io === "undefined") {
      setStatus("offline", "client library missing");
      return;
    }
    setStatus("connecting");
    socket = io({ reconnectionDelay: 1000, reconnectionDelayMax: 5000, timeout: 10000 });

    socket.on("connect", () => {
      setStatus("connected");
      joinedTickets.forEach(joinTicketRoom);
      if (everConnected) {
        dispatch("resync", {});
        App.toast("Reconnected to the server. Data refreshed.", { type: "success", timeout: 3500 });
      }
      everConnected = true;
      measureRtt();
      clearInterval(rttTimer);
      rttTimer = setInterval(measureRtt, 10000);
      socket.io.engine.once("upgrade", () => {
        setStatus("connected");
        socket.emit("client:transport", {});
      });
    });

    socket.on("disconnect", (reason) => {
      clearInterval(rttTimer);
      lastRtt = null;
      if (reason === "io server disconnect") {
        setStatus("expired"); // the server closed us, e.g. after logging out in another tab
      } else {
        setStatus("reconnecting", reason === "ping timeout" ? "heartbeat lost" : "");
      }
    });

    socket.on("connect_error", (error) => {
      if (error.message === "unauthorized") {
        setStatus("expired");
      } else {
        setStatus(socket.active ? "reconnecting" : "offline", "server unreachable");
      }
    });

    socket.io.on("reconnect_attempt", (attempt) => setStatus("reconnecting", `attempt ${attempt}`));

    SERVER_EVENTS.forEach((name) => {
      socket.on(name, (payload) => {
        if (!isDuplicate(payload)) dispatch(name, payload);
      });
    });
  }

  // ---------- Behaviour shared by every page ----------

  on("stats:updated", (payload) => App.applyStats(payload.stats));

  on("resync", () => {
    App.api("GET", "/api/stats").then(App.applyStats).catch(() => {});
  });

  on("notification", (note) => {
    if (App.user && note.actor_id === App.user.id) return; // our own action
    if (note.kind === "ticket_message" && note.ticket_id === App.currentTicketId) return; // already on screen
    let href = note.ticket_id ? App.ticketUrl(note.ticket_id) : App.announcementsUrl();
    if (note.ticket_id && note.ticket_id === App.currentTicketId) href = null; // already viewing it
    const type = note.kind === "ticket_status" && /resolved/i.test(note.text) ? "success" : "info";
    App.toast(note.text, { type, href, linkText: note.ticket_id ? "Open ticket" : "View", timeout: 8000 });
  });

  return { connect, on, emit, joinTicket, isConnected: () => Boolean(socket && socket.connected) };
})();

Realtime.connect();
