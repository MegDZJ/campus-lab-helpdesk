/*
 * Lab assistant pages: overview, ticket management, announcements, network.
 * Lists are drawn from the JSON embedded in the page and re-fetched from the
 * API whenever a relevant Socket.IO event arrives.
 */
"use strict";

(() => {
  const { h, icon } = App;
  const page = document.body.dataset.page;

  // ---------- Overview ----------

  function activityItem(entry) {
    const dotClass = entry.to_status ? `activity-dot to-${entry.to_status}` : "activity-dot";
    const dotIcon = { open: "i-inbox", in_progress: "i-activity", resolved: "i-check" }[entry.to_status] || "i-hand";
    return h("div", { class: "activity-item" },
      h("span", { class: dotClass }, icon(dotIcon, "icon-sm")),
      h("div", {},
        h("div", { class: "text" }, h("a", { href: App.ticketUrl(entry.ticket_id) }, entry.ticket_number), " ",
          entry.action.charAt(0).toLowerCase() + entry.action.slice(1)),
        h("div", { class: "subtle" }, `${entry.actor.name} · ${entry.ticket_title} · `, App.timeEl(entry.created_at))));
  }

  function queueItem(ticket) {
    return h("a", { class: "list-item", href: App.ticketUrl(ticket.id) },
      h("div", { class: "grow" },
        h("div", { class: "title" }, ticket.title),
        h("div", { class: "meta" }, App.dotted(h("span", { class: "ticket-no" }, ticket.ticket_number),
          ticket.student.name, ticket.workstation || "No workstation", App.timeEl(ticket.created_at)))),
      App.priorityBadge(ticket.priority));
  }

  function initDashboard() {
    const queueBox = document.getElementById("queue");
    const activityBox = document.getElementById("activity");
    const onlineCount = document.getElementById("online-count");

    const renderQueue = (tickets) => {
      const waiting = tickets.filter((t) => t.status !== "resolved").slice(0, 6);
      queueBox.replaceChildren(waiting.length
        ? h("div", { class: "list" }, waiting.map(queueItem))
        : App.emptyState("All caught up", "Every unresolved ticket has an assistant.", "i-check-circle"));
    };
    const renderActivity = (entries) => {
      activityBox.replaceChildren(entries.length
        ? h("div", {}, entries.slice(0, 10).map(activityItem))
        : App.emptyState("No activity yet", "Ticket events will appear here live.", "i-activity"));
    };

    const refresh = App.debounce(async () => {
      try {
        const [queue, activity] = await Promise.all([
          App.api("GET", "/api/tickets?assigned=unassigned&sort=priority"),
          App.api("GET", "/api/activity"),
        ]);
        renderQueue(queue);
        renderActivity(activity);
      } catch (error) {
        App.toast(`Could not refresh the overview: ${error.message}`, { type: "error" });
      }
    }, 150);

    renderQueue(App.pageData.queue);
    renderActivity(App.pageData.activity);
    ["ticket:created", "ticket:updated", "resync"].forEach((event) => Realtime.on(event, refresh));
    Realtime.on("presence:updated", (payload) => { onlineCount.textContent = payload.count; });
  }

  // ---------- Ticket management ----------

  function ticketRow(ticket, highlight) {
    const link = App.ticketUrl(ticket.id);
    const assigned = ticket.assignee
      ? (ticket.assignee.id === App.user.id ? h("strong", {}, "You") : ticket.assignee.name)
      : h("span", { class: "subtle" }, "Unassigned");
    const row = h("tr", { class: `clickable${highlight ? " row-new" : ""}` },
      h("td", { class: "nowrap" }, h("a", { class: "ticket-no", href: link }, ticket.ticket_number)),
      h("td", { class: "title-cell" }, h("a", { href: link }, ticket.title),
        h("div", { class: "sub" }, `${ticket.student.name}${ticket.workstation ? ` · ${ticket.workstation}` : ""}`)),
      h("td", {}, App.categoryBadge(ticket.category)),
      h("td", {}, App.priorityBadge(ticket.priority)),
      h("td", {}, App.statusBadge(ticket.status)),
      h("td", { class: "nowrap" }, assigned),
      h("td", { class: "nowrap" }, App.timeEl(ticket.created_at)),
      h("td", {}, h("span", { class: "count", title: "Messages" }, icon("i-chat", "icon-sm"), ticket.message_count)));
    row.addEventListener("click", (event) => {
      if (!event.target.closest("a")) window.location.href = link;
    });
    return row;
  }

  function initTickets() {
    const form = document.getElementById("ticket-filters");
    const tableBox = document.getElementById("ticket-table");
    const count = document.getElementById("result-count");

    const render = (tickets, highlightId = null) => {
      count.textContent = `${tickets.length} ticket${tickets.length === 1 ? "" : "s"} shown`;
      if (!tickets.length) {
        tableBox.replaceChildren(App.emptyState("No tickets match these filters",
          "Clear the filters to see every ticket.", "i-search"));
        return;
      }
      const head = ["Ticket", "Problem / student", "Category", "Priority", "Status", "Assigned", "Created", ""];
      tableBox.replaceChildren(h("table", { class: "table" },
        h("thead", {}, h("tr", {}, head.map((title) => h("th", { scope: "col" }, title)))),
        h("tbody", {}, tickets.map((ticket) => ticketRow(ticket, ticket.id === highlightId)))));
    };

    let requestNumber = 0;
    const load = async (highlightId = null) => {
      const filters = App.readFilters(form);
      if (filters.sort === "newest") delete filters.sort;
      App.syncUrl(filters);
      const current = ++requestNumber;
      try {
        const tickets = await App.api("GET", `/api/tickets?${new URLSearchParams(filters)}`);
        if (current === requestNumber) render(tickets, highlightId);
      } catch (error) {
        tableBox.replaceChildren(App.errorState(error.message));
      }
    };

    form.addEventListener("submit", (event) => event.preventDefault());
    form.addEventListener("input", App.debounce(() => load(), 250));
    form.addEventListener("change", () => load());
    form.addEventListener("reset", () => setTimeout(() => load(), 0));

    if (App.applyFiltersFromUrl(form)) load();
    else render(App.pageData.tickets);

    Realtime.on("ticket:created", (payload) => load(payload.ticket.id));
    Realtime.on("ticket:updated", (payload) => load(payload.ticket.id));
    Realtime.on("resync", () => load());
  }

  // ---------- Announcements ----------

  function initAnnouncements() {
    const createForm = document.getElementById("announcement-form");
    const list = document.getElementById("announcement-list");
    const countLabel = document.getElementById("announcement-count");
    const editDialog = document.getElementById("edit-dialog");
    const editForm = document.getElementById("edit-form");
    const deleteDialog = document.getElementById("delete-dialog");
    const confirmDelete = document.getElementById("confirm-delete");
    let items = App.pageData.announcements;
    let editingId = null;
    let deletingId = null;

    function itemView(item, isNew) {
      const editButton = h("button", { class: "btn btn-ghost btn-sm", type: "button", "aria-label": `Edit “${item.title}”` },
        icon("i-edit", "icon-sm"), "Edit");
      const deleteButton = h("button", { class: "btn btn-ghost btn-sm", type: "button", "aria-label": `Delete “${item.title}”` },
        icon("i-trash", "icon-sm"), "Delete");
      editButton.addEventListener("click", () => openEdit(item));
      deleteButton.addEventListener("click", () => openDelete(item));
      const edited = item.updated_at ? h("span", {}, "edited ", App.timeEl(item.updated_at)) : null;
      return h("article", { class: `announcement${isNew ? " is-new" : ""}` },
        h("h3", {}, item.title),
        h("p", { class: "body" }, item.content),
        h("div", { class: "meta" }, icon("i-user", "icon-sm"),
          App.dotted(item.author.name, App.timeEl(item.created_at, "datetime"), edited),
          h("span", { class: "announcement-tools" }, editButton, deleteButton)));
    }

    function render(newId = null) {
      countLabel.textContent = `${items.length} total`;
      list.replaceChildren(items.length
        ? h("div", {}, items.map((item) => itemView(item, item.id === newId)))
        : App.emptyState("Nothing published yet", "Write the first announcement for the lab.", "i-megaphone"));
    }

    async function refresh(newId = null) {
      try {
        items = await App.api("GET", "/api/announcements");
        render(newId);
      } catch (error) {
        list.replaceChildren(App.errorState(error.message));
      }
    }

    function fillForm(form, item) {
      form.elements.title.value = item ? item.title : "";
      form.elements.content.value = item ? item.content : "";
      form.querySelectorAll("input, textarea").forEach((el) => el.dispatchEvent(new Event("input")));
    }

    function openEdit(item) {
      editingId = item.id;
      App.clearFieldErrors(editForm);
      fillForm(editForm, item);
      editDialog.showModal();
    }

    function openDelete(item) {
      deletingId = item.id;
      document.getElementById("delete-title").textContent = item.title;
      deleteDialog.showModal();
    }

    document.querySelectorAll("dialog [data-close]").forEach((button) => {
      button.addEventListener("click", () => button.closest("dialog").close());
    });

    createForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = createForm.querySelector("[type=submit]");
      App.clearFieldErrors(createForm);
      App.setBusy(button, true);
      try {
        const created = await App.api("POST", "/api/announcements", App.formToObject(createForm));
        fillForm(createForm, null);
        App.toast("Announcement published to every connected user.", { type: "success", timeout: 4000 });
        await refresh(created.id);
      } catch (error) {
        App.showFieldErrors(createForm, error.fields, error.message);
      } finally {
        App.setBusy(button, false);
      }
    });

    editForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = editForm.querySelector("[type=submit]");
      App.setBusy(button, true);
      try {
        await App.api("PUT", `/api/announcements/${editingId}`, App.formToObject(editForm));
        editDialog.close();
        App.toast("Announcement updated.", { type: "success", timeout: 3500 });
        await refresh();
      } catch (error) {
        App.showFieldErrors(editForm, error.fields, error.message);
      } finally {
        App.setBusy(button, false);
      }
    });

    confirmDelete.addEventListener("click", async () => {
      App.setBusy(confirmDelete, true);
      try {
        await App.api("DELETE", `/api/announcements/${deletingId}`);
        deleteDialog.close();
        App.toast("Announcement deleted.", { type: "success", timeout: 3500 });
        await refresh();
      } catch (error) {
        App.toast(error.message, { type: "error" });
      } finally {
        App.setBusy(confirmDelete, false);
      }
    });

    render();
    Realtime.on("announcement:created", (payload) => refresh(payload.announcement.id));
    Realtime.on("announcement:updated", () => refresh());
    Realtime.on("announcement:deleted", () => refresh());
    Realtime.on("resync", () => refresh());
  }

  // ---------- Network monitor ----------

  function initNetwork() {
    const tableBox = document.getElementById("client-table");
    const countLabel = document.getElementById("client-count");
    const refreshButton = document.getElementById("refresh-network");

    const render = (clients) => {
      countLabel.textContent = clients.length;
      if (!clients.length) {
        tableBox.replaceChildren(App.emptyState("No live connections", "Open the helpdesk in a browser to see it here.", "i-users"));
        return;
      }
      const head = ["User", "Role", "Client IP address", "Transport", "Connected", "Socket id"];
      tableBox.replaceChildren(h("table", { class: "table" },
        h("thead", {}, h("tr", {}, head.map((title) => h("th", { scope: "col" }, title)))),
        h("tbody", {}, clients.map((client) => h("tr", {},
          h("td", {}, h("strong", {}, client.name), h("div", { class: "sub" }, `@${client.username}`)),
          h("td", {}, client.role === "assistant" ? "Lab assistant" : "Student"),
          h("td", { class: "mono" }, client.ip),
          h("td", {}, h("span", { class: `transport ${client.transport}` }, client.transport)),
          h("td", { class: "nowrap" }, App.timeEl(client.connected_at)),
          h("td", { class: "mono subtle" }, client.sid))))));
    };

    refreshButton.addEventListener("click", async () => {
      App.setBusy(refreshButton, true);
      try {
        const data = await App.api("GET", "/api/network");
        render(data.clients);
      } catch (error) {
        App.toast(error.message, { type: "error" });
      } finally {
        App.setBusy(refreshButton, false);
      }
    });

    render(App.pageData.clients);
    Realtime.on("presence:updated", (payload) => render(payload.clients));
    Realtime.on("resync", () => refreshButton.click());
  }

  const initializers = {
    "assistant-dashboard": initDashboard,
    "assistant-tickets": initTickets,
    "assistant-announcements": initAnnouncements,
    "assistant-network": initNetwork,
  };
  if (initializers[page]) initializers[page]();
})();
