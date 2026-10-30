/*
 * Ticket detail page (students and assistants): conversation, timeline,
 * live status, and assistant actions.
 *
 * Sending a message: the browser shows a "Sending…" bubble, emits
 * ticket:send_message over the Socket.IO connection and waits for the
 * server's acknowledgement (sent only after the message is saved in SQLite),
 * then marks the bubble "Delivered". If the live connection is down, the
 * message is sent with an ordinary HTTP POST instead.
 */
"use strict";

(() => {
  const { h, icon } = App;
  const root = document.getElementById("ticket-root");
  if (!root) return;

  const ticketId = Number(root.dataset.ticketId);
  const isAssistant = App.user.role === "assistant";
  const messagesBox = document.getElementById("messages");
  const timeline = document.getElementById("timeline");
  const actionsBox = document.getElementById("ticket-actions");
  const composer = document.getElementById("composer");
  const input = document.getElementById("message-input");
  const messageCount = document.getElementById("message-count");

  const renderedMessages = new Set(); // server message ids already on screen
  const pendingBubbles = new Map();   // client_id -> bubble element awaiting the ack
  const renderedHistory = new Set();
  let ticket = App.pageData.ticket;

  App.currentTicketId = ticketId;

  const TRANSITIONS = {
    "open>in_progress": { label: "Start work", icon: "i-play", style: "btn-primary" },
    "in_progress>resolved": { label: "Mark as resolved", icon: "i-check", style: "btn-success" },
    "in_progress>open": { label: "Return to open queue", icon: "i-rotate", style: "" },
    "resolved>open": { label: "Reopen ticket", icon: "i-rotate", style: "" },
  };

  // ---------- Summary fields ----------

  function setField(name, content) {
    document.querySelectorAll(`[data-ticket-field="${name}"]`).forEach((element) => {
      element.replaceChildren(content instanceof Node ? content.cloneNode(true) : content);
    });
  }

  function renderSummary(data) {
    ticket = { ...ticket, ...data };
    setField("status", App.statusBadge(ticket.status));
    setField("assignee", ticket.assignee ? ticket.assignee.name : "Not assigned yet");
    setField("updated_at", App.timeEl(ticket.updated_at));
    setField("resolved_at", ticket.resolved_at ? App.timeEl(ticket.resolved_at, "datetime") : "—");
    renderActions();
  }

  // ---------- Assistant actions ----------

  function actionButton(text, iconName, style, handler) {
    const button = h("button", { class: `btn btn-block ${style}`, type: "button" }, icon(iconName), text);
    button.addEventListener("click", async () => {
      App.setBusy(button, true);
      try {
        const updated = await handler();
        renderSummary(updated);
        updated.history.forEach(addHistory);
        const latest = updated.history[updated.history.length - 1];
        App.toast(`${updated.ticket_number}: ${latest.action}.`, { type: "success", timeout: 3500 });
      } catch (error) {
        App.toast(error.message, { type: "error" });
      } finally {
        App.setBusy(button, false);
      }
    });
    return button;
  }

  function renderActions() {
    if (!actionsBox) return;
    const items = [];
    const mine = ticket.assignee && ticket.assignee.id === App.user.id;
    if (ticket.status !== "resolved" && !mine) {
      const label = ticket.assignee ? `Take over from ${ticket.assignee.name}` : "Assign to me";
      items.push(actionButton(label, "i-hand", "",
        () => App.api("POST", `/api/tickets/${ticketId}/assign`)));
    }
    for (const next of ticket.allowed_transitions) {
      const spec = TRANSITIONS[`${ticket.status}>${next}`];
      if (!spec) continue;
      items.push(actionButton(spec.label, spec.icon, spec.style,
        () => App.api("PATCH", `/api/tickets/${ticketId}/status`, { status: next })));
    }
    const note = {
      open: "Starting work moves the ticket to In Progress and assigns it to you if nobody has it.",
      in_progress: "Resolve the ticket once the student confirms the problem is fixed.",
      resolved: "Reopen the ticket if the problem comes back.",
    }[ticket.status];
    items.push(h("p", { class: "actions-note" }, note));
    actionsBox.replaceChildren(...items);
  }

  // ---------- Timeline ----------

  function addHistory(entry) {
    if (renderedHistory.has(entry.id)) return;
    renderedHistory.add(entry.id);
    const dotClass = entry.to_status ? `dot to-${entry.to_status}` : "dot";
    timeline.append(h("li", {},
      h("span", { class: dotClass }),
      h("div", { class: "action" }, entry.action),
      h("div", { class: "when" }, `${entry.actor.name} · `, App.timeEl(entry.created_at))));
  }

  // ---------- Conversation ----------

  function updateMessageCount() {
    const count = messagesBox.querySelectorAll(".msg:not(.pending):not(.failed)").length;
    messageCount.textContent = count === 1 ? "1 message" : `${count} messages`;
    const empty = messagesBox.querySelector(".state");
    if (empty && messagesBox.querySelector(".msg")) empty.remove();
  }

  function scrollToBottom() {
    messagesBox.scrollTop = messagesBox.scrollHeight;
  }

  function bubble({ sender, body, created_at: createdAt }, statusNode) {
    const mine = sender.id === App.user.id;
    const assistantTag = sender.role === "assistant" ? h("span", { class: "tag" }, "Lab assistant") : null;
    return h("div", { class: `msg${mine ? " mine" : ""}` },
      h("span", { class: `avatar avatar-sm${sender.role === "assistant" ? " is-assistant" : ""}`, "aria-hidden": "true" },
        App.initials(sender.name)),
      h("div", { class: "msg-bubble" },
        h("div", { class: "msg-head" },
          h("span", { class: "sender" }, mine ? "You" : sender.name), assistantTag,
          createdAt ? App.timeEl(createdAt) : null),
        h("div", { class: "msg-body" }, body),
        statusNode || null));
  }

  function deliveredNote(text = "Delivered") {
    return h("div", { class: "msg-status" }, icon("i-check", "icon-sm"), text);
  }

  /** Render a stored message unless it is already on screen. */
  function addMessage(message, clientId = null) {
    if (renderedMessages.has(message.id)) return;
    renderedMessages.add(message.id);
    const pending = clientId && pendingBubbles.get(clientId);
    const mine = message.sender.id === App.user.id;
    const element = bubble(message, mine ? deliveredNote() : null);
    if (pending) {
      pendingBubbles.delete(clientId);
      pending.replaceWith(element);
    } else {
      messagesBox.append(element);
    }
    updateMessageCount();
    scrollToBottom();
  }

  function renderMessages(messages) {
    messagesBox.replaceChildren();
    renderedMessages.clear();
    if (!messages.length) {
      messagesBox.append(App.emptyState("No messages yet",
        isAssistant ? "Send the student an update or ask for more details." :
          "A lab assistant will reply here. You can add more details at any time.", "i-chat"));
    }
    messages.forEach((message) => addMessage(message));
    pendingBubbles.forEach((element) => messagesBox.append(element)); // keep unsent ones
    updateMessageCount();
    scrollToBottom();
  }

  function newClientId() {
    return `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  }

  async function deliver(body, clientId) {
    if (Realtime.isConnected()) {
      const data = await Realtime.emit("ticket:send_message", { ticket_id: ticketId, body, client_id: clientId });
      return data.message;
    }
    // Fallback when the live connection is down: plain HTTP request.
    return App.api("POST", `/api/tickets/${ticketId}/messages`, { body, client_id: clientId });
  }

  async function send(body, existingBubble = null) {
    const clientId = newClientId();
    const statusLine = h("div", { class: "msg-status" }, icon("i-clock", "icon-sm"), "Sending…");
    const element = bubble({ sender: App.user, body, created_at: null }, statusLine);
    element.classList.add("pending");
    pendingBubbles.set(clientId, element);
    if (existingBubble) existingBubble.replaceWith(element);
    else messagesBox.append(element);
    updateMessageCount();
    scrollToBottom();

    try {
      const message = await deliver(body, clientId);
      addMessage(message, clientId); // no-op if the broadcast already rendered it
    } catch (error) {
      if (!pendingBubbles.has(clientId)) return; // delivered via the broadcast after all
      pendingBubbles.delete(clientId);
      element.classList.remove("pending");
      element.classList.add("failed");
      const retry = h("button", { class: "retry", type: "button" }, "Retry");
      retry.addEventListener("click", () => send(body, element));
      statusLine.replaceChildren(icon("i-alert", "icon-sm"), `Not delivered: ${error.message} `, retry);
    }
  }

  composer.addEventListener("submit", (event) => {
    event.preventDefault();
    const body = input.value.trim();
    if (!body) {
      input.focus();
      return;
    }
    input.value = "";
    input.dispatchEvent(new Event("input"));
    input.style.height = "";
    send(body);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      composer.requestSubmit();
    }
  });

  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  });

  // ---------- Live updates ----------

  async function reload() {
    try {
      const fresh = await App.api("GET", `/api/tickets/${ticketId}`);
      renderSummary(fresh);
      timeline.replaceChildren();
      renderedHistory.clear();
      fresh.history.forEach(addHistory);
      renderMessages(fresh.messages);
    } catch (error) {
      App.toast(`Could not refresh the ticket: ${error.message}`, { type: "error" });
    }
  }

  Realtime.on("ticket:message", (payload) => {
    if (payload.ticket_id === ticketId) addMessage(payload.message, payload.client_id);
  });

  // (The pop-up notification for someone else's change is shown by socket.js.)
  Realtime.on("ticket:updated", (payload) => {
    if (payload.ticket.id !== ticketId) return;
    renderSummary(payload.ticket);
    addHistory(payload.history);
  });

  Realtime.on("resync", reload);
  Realtime.joinTicket(ticketId);

  renderSummary(ticket);
  ticket.history.forEach(addHistory);
  renderMessages(ticket.messages);
})();
