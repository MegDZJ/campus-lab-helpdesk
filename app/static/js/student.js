/*
 * Student pages: dashboard, report form, my tickets, announcements.
 * Lists are drawn from the JSON embedded in the page and re-fetched from the
 * API whenever a relevant Socket.IO event arrives.
 */
"use strict";

(() => {
  const { h, icon } = App;
  const page = document.body.dataset.page;

  // ---------- Shared renderers ----------

  function ticketListItem(ticket) {
    return h("a", { class: "list-item", href: App.ticketUrl(ticket.id) },
      h("div", { class: "grow" },
        h("div", { class: "title" }, ticket.title),
        h("div", { class: "meta" }, App.dotted(h("span", { class: "ticket-no" }, ticket.ticket_number),
          App.categoryBadge(ticket.category), App.timeEl(ticket.updated_at)))),
      App.statusBadge(ticket.status));
  }

  function announcementItem(item, isNew = false) {
    const edited = item.updated_at ? h("span", {}, "edited ", App.timeEl(item.updated_at)) : null;
    return h("article", { class: `announcement${isNew ? " is-new" : ""}` },
      h("h3", {}, item.title),
      h("p", { class: "body" }, item.content),
      h("div", { class: "meta" }, icon("i-megaphone", "icon-sm"),
        App.dotted(item.author.name, App.timeEl(item.created_at, "datetime"), edited)));
  }

  function renderAnnouncements(container, items, newId = null) {
    if (!items.length) {
      container.replaceChildren(App.emptyState("No announcements yet",
        "Notices from the lab staff will appear here.", "i-megaphone"));
      return;
    }
    container.replaceChildren(...items.map((item) => announcementItem(item, item.id === newId)));
  }

  function watchAnnouncements(container, limit = null) {
    const refresh = async (newId = null) => {
      try {
        const items = await App.api("GET", "/api/announcements");
        renderAnnouncements(container, limit ? items.slice(0, limit) : items, newId);
      } catch (error) {
        container.replaceChildren(App.errorState(error.message));
      }
    };
    Realtime.on("announcement:created", (payload) => refresh(payload.announcement.id));
    Realtime.on("announcement:updated", () => refresh());
    Realtime.on("announcement:deleted", () => refresh());
    Realtime.on("resync", () => refresh());
  }

  // ---------- Dashboard ----------

  function initDashboard() {
    const recent = document.getElementById("recent-tickets");
    const latest = document.getElementById("latest-announcements");

    const renderRecent = (tickets) => {
      if (!tickets.length) {
        recent.replaceChildren(App.emptyState("No tickets yet",
          "When something goes wrong with a lab computer, report it and track it here.", "i-ticket"));
        return;
      }
      recent.replaceChildren(h("div", { class: "list" }, tickets.map(ticketListItem)));
    };
    const refreshRecent = App.debounce(async () => {
      try {
        renderRecent((await App.api("GET", "/api/tickets")).slice(0, 5));
      } catch (error) {
        recent.replaceChildren(App.errorState(error.message));
      }
    }, 150);

    renderRecent(App.pageData.tickets);
    renderAnnouncements(latest, App.pageData.announcements);
    watchAnnouncements(latest, 3);
    ["ticket:created", "ticket:updated", "resync"].forEach((event) => Realtime.on(event, refreshRecent));
  }

  // ---------- Report a problem ----------

  function initNewTicket() {
    const form = document.getElementById("ticket-form");
    const success = document.getElementById("ticket-success");
    const submit = document.getElementById("submit-ticket");

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      App.clearFieldErrors(form);
      if (!form.checkValidity()) {
        form.reportValidity(); // the browser's own hints; the server validates again
        return;
      }
      App.setBusy(submit, true);
      try {
        const ticket = await App.api("POST", "/api/tickets", App.formToObject(form));
        document.getElementById("success-number").textContent = ticket.ticket_number;
        const time = document.getElementById("success-time");
        time.setAttribute("datetime", ticket.created_at);
        App.refreshTimes(success);
        document.getElementById("success-link").href = App.ticketUrl(ticket.id);
        form.hidden = true;
        success.hidden = false;
        success.querySelector("a").focus();
        App.toast(`Ticket ${ticket.ticket_number} created.`, { type: "success", timeout: 4000 });
      } catch (error) {
        App.showFieldErrors(form, error.fields, error.message);
      } finally {
        App.setBusy(submit, false);
      }
    });

    document.getElementById("report-another").addEventListener("click", () => {
      form.reset();
      form.querySelectorAll("textarea, input").forEach((el) => el.dispatchEvent(new Event("input")));
      success.hidden = true;
      form.hidden = false;
      document.getElementById("title").focus();
    });
  }

  // ---------- My tickets ----------

  function ticketRow(ticket, highlight) {
    const link = App.ticketUrl(ticket.id);
    const row = h("tr", { class: `clickable${highlight ? " row-new" : ""}` },
      h("td", { class: "nowrap" }, h("a", { class: "ticket-no", href: link }, ticket.ticket_number)),
      h("td", { class: "title-cell" }, h("a", { href: link }, ticket.title),
        h("div", { class: "sub" }, ticket.workstation ? `Workstation ${ticket.workstation}` : "No workstation given")),
      h("td", {}, App.categoryBadge(ticket.category)),
      h("td", {}, App.priorityBadge(ticket.priority)),
      h("td", { class: "nowrap" }, ticket.assignee ? ticket.assignee.name : h("span", { class: "subtle" }, "Not assigned")),
      h("td", { class: "nowrap" }, App.timeEl(ticket.created_at)),
      h("td", {}, App.statusBadge(ticket.status)));
    row.addEventListener("click", (event) => {
      if (!event.target.closest("a")) window.location.href = link;
    });
    return row;
  }

  function initMyTickets() {
    const form = document.getElementById("ticket-filters");
    const tableBox = document.getElementById("ticket-table");
    const count = document.getElementById("result-count");

    const render = (tickets, highlightId = null) => {
      count.textContent = tickets.length === 1 ? "1 ticket" : `${tickets.length} tickets`;
      if (!tickets.length) {
        const filtered = Object.keys(App.readFilters(form)).length > 0;
        tableBox.replaceChildren(filtered
          ? App.emptyState("No tickets match your filters", "Try a different search or status.", "i-search")
          : App.emptyState("You haven't reported any problems yet", "Use “Report a problem” to create your first ticket.", "i-ticket"));
        return;
      }
      const head = ["Ticket", "Problem", "Category", "Priority", "Assigned to", "Created", "Status"];
      tableBox.replaceChildren(h("table", { class: "table" },
        h("thead", {}, h("tr", {}, head.map((title) => h("th", { scope: "col" }, title)))),
        h("tbody", {}, tickets.map((ticket) => ticketRow(ticket, ticket.id === highlightId)))));
    };

    let requestNumber = 0;
    const load = async (highlightId = null) => {
      const filters = App.readFilters(form);
      App.syncUrl(filters);
      const current = ++requestNumber;
      try {
        const tickets = await App.api("GET", `/api/tickets?${new URLSearchParams(filters)}`);
        if (current === requestNumber) render(tickets, highlightId); // ignore out-of-date replies
      } catch (error) {
        tableBox.replaceChildren(App.errorState(error.message));
      }
    };

    form.addEventListener("submit", (event) => event.preventDefault());
    form.addEventListener("input", App.debounce(() => load(), 250));
    form.addEventListener("change", () => load());

    if (App.applyFiltersFromUrl(form)) load();
    else render(App.pageData.tickets);

    Realtime.on("ticket:created", (payload) => load(payload.ticket.id));
    Realtime.on("ticket:updated", (payload) => load(payload.ticket.id));
    Realtime.on("resync", () => load());
  }

  // ---------- Announcements page ----------

  function initAnnouncements() {
    const list = document.getElementById("announcement-list");
    renderAnnouncements(list, App.pageData.announcements);
    watchAnnouncements(list);
  }

  const initializers = {
    "student-dashboard": initDashboard,
    "student-new-ticket": initNewTicket,
    "student-tickets": initMyTickets,
    "student-announcements": initAnnouncements,
  };
  if (initializers[page]) initializers[page]();
})();
