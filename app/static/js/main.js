/*
 * Shared browser helpers: HTTP API calls, safe DOM building, formatting,
 * toasts and form error display. Every page loads this file first.
 *
 * User-supplied text is always inserted with textContent (never innerHTML),
 * so a ticket title such as "<script>" is displayed, not executed.
 */
"use strict";

const App = (() => {
  const config = JSON.parse(document.getElementById("app-config").textContent);
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const pageDataElement = document.getElementById("page-data");
  const pageData = pageDataElement ? JSON.parse(pageDataElement.textContent) : {};
  const user = config.user;
  const labels = config.labels;

  class ApiError extends Error {
    constructor(message, status = 0, fields = {}) {
      super(message);
      this.status = status;
      this.fields = fields;
    }
  }

  /** Call the JSON API. Resolves with `data`, rejects with ApiError. */
  async function api(method, url, body) {
    const options = { method, credentials: "same-origin", headers: { Accept: "application/json" } };
    if (method !== "GET") options.headers["X-CSRF-Token"] = csrfToken;
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(url, options);
    } catch (networkError) {
      throw new ApiError("Cannot reach the helpdesk server. Check that you are connected to the lab network.");
    }
    let payload = null;
    try {
      payload = await response.json();
    } catch (parseError) {
      payload = null;
    }
    if (response.status === 401) {
      window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
    }
    if (!response.ok || !payload || !payload.ok) {
      const error = (payload && payload.error) || {};
      throw new ApiError(error.message || `Request failed (HTTP ${response.status}).`, response.status, error.fields || {});
    }
    return payload.data;
  }

  /** Build a DOM element: h("a", {href: "/x", class: "btn"}, "text", childNode) */
  function h(tag, attrs, ...children) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") element.className = value;
      else if (key === "dataset") Object.assign(element.dataset, value);
      else if (key.startsWith("on") && typeof value === "function") element.addEventListener(key.slice(2), value);
      else element.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      element.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return element;
  }

  function icon(name, extraClass = "") {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", `icon ${extraClass}`.trim());
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `#${name}`);
    svg.append(use);
    return svg;
  }

  // ---------- Formatting ----------

  const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
  const relativeFormat = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

  function formatDateTime(iso) {
    return iso ? dateTimeFormat.format(new Date(iso)) : "";
  }

  function formatRelative(iso) {
    if (!iso) return "";
    const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
    const abs = Math.abs(seconds);
    if (abs < 45) return "just now";
    if (abs < 3600) return relativeFormat.format(Math.round(seconds / 60), "minute");
    if (abs < 86400) return relativeFormat.format(Math.round(seconds / 3600), "hour");
    if (abs < 604800) return relativeFormat.format(Math.round(seconds / 86400), "day");
    return formatDateTime(iso);
  }

  /** <time> element showing local time; relative ones are refreshed every 30 s. */
  function timeEl(iso, format = "relative") {
    const element = h("time", { datetime: iso, "data-format": format });
    renderTime(element);
    return element;
  }

  function renderTime(element) {
    const iso = element.getAttribute("datetime");
    if (!iso) return;
    element.textContent = element.dataset.format === "datetime" ? formatDateTime(iso) : formatRelative(iso);
    element.title = formatDateTime(iso);
  }

  function refreshTimes(root = document) {
    root.querySelectorAll("time[datetime]").forEach(renderTime);
  }

  /** Join parts with "·" separators; each part becomes its own element so CSS gaps apply. */
  function dotted(...parts) {
    const nodes = [];
    parts.filter((part) => part !== null && part !== undefined && part !== false && part !== "")
      .forEach((part, index) => {
        if (index > 0) nodes.push(h("span", { "aria-hidden": "true" }, "·"));
        nodes.push(part instanceof Node ? part : h("span", {}, part));
      });
    return nodes;
  }

  function statusBadge(status) {
    return h("span", { class: `badge badge-${status}` }, labels.statuses[status] || status);
  }

  function priorityBadge(priority, suffix = "") {
    return h("span", { class: `badge badge-${priority}` }, (labels.priorities[priority] || priority) + suffix);
  }

  function categoryBadge(category) {
    return h("span", { class: "badge badge-category" }, labels.categories[category] || category);
  }

  function initials(name) {
    const parts = String(name).trim().split(/\s+/);
    return ((parts[0] || "")[0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
  }

  function ticketUrl(ticketId) {
    return user && user.role === "assistant" ? `/assistant/tickets/${ticketId}` : `/student/tickets/${ticketId}`;
  }

  function announcementsUrl() {
    return user && user.role === "assistant" ? "/assistant/announcements" : "/student/announcements";
  }

  // ---------- Feedback ----------

  const toastRegion = document.getElementById("toasts");
  const TOAST_ICONS = { success: "i-check-circle", error: "i-alert", info: "i-bell" };

  /** Small notification in the bottom-right corner. */
  function toast(message, { type = "info", href = null, linkText = "View", timeout = 6000 } = {}) {
    if (!toastRegion) return;
    const close = h("button", { class: "toast-close", type: "button", "aria-label": "Dismiss" }, icon("i-x", "icon-sm"));
    const body = h("div", { class: "toast-text" }, message, href ? [" ", h("a", { href }, linkText)] : null);
    const item = h("div", { class: `toast toast-${type}`, role: type === "error" ? "alert" : null },
      icon(TOAST_ICONS[type] || "i-info"), body, close);
    const remove = () => item.remove();
    close.addEventListener("click", remove);
    toastRegion.append(item);
    while (toastRegion.children.length > 4) toastRegion.firstElementChild.remove();
    if (timeout) setTimeout(remove, timeout);
  }

  function setBusy(button, busy) {
    if (!button) return;
    button.disabled = busy;
    if (busy) button.setAttribute("aria-busy", "true");
    else button.removeAttribute("aria-busy");
  }

  function emptyState(title, text, iconName = "i-inbox") {
    return h("div", { class: "state" },
      h("div", { class: "state-icon" }, icon(iconName, "icon-lg")),
      h("strong", {}, title), text ? h("span", {}, text) : null);
  }

  function errorState(text) {
    return h("div", { class: "state compact" },
      h("div", { class: "state-icon", style: "background:var(--red-bg);color:var(--red)" }, icon("i-alert", "icon-lg")),
      h("strong", {}, "Could not load data"), h("span", {}, text));
  }

  // ---------- Forms ----------

  function errorSlotFor(form, name) {
    return form.querySelector(`[data-error-for="${name}"]`) || document.getElementById(`${name}-error`);
  }

  function clearFieldErrors(form) {
    form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
    form.querySelectorAll(".field-error").forEach((el) => { el.textContent = ""; });
    const formError = form.querySelector("[data-form-error]") || form.querySelector("#form-error");
    if (formError) formError.hidden = true;
  }

  /** Show server-side validation errors next to the matching fields. */
  function showFieldErrors(form, fields, message) {
    clearFieldErrors(form);
    let first = null;
    for (const [name, text] of Object.entries(fields || {})) {
      const slot = errorSlotFor(form, name);
      if (slot) slot.textContent = text;
      const inputs = form.querySelectorAll(`[name="${name}"]`);
      inputs.forEach((input) => input.setAttribute("aria-invalid", "true"));
      if (!first && inputs[0]) first = inputs[0];
    }
    const formError = form.querySelector("[data-form-error]") || form.querySelector("#form-error");
    if (formError && message) {
      formError.textContent = message;
      formError.hidden = false;
    }
    if (first) first.focus();
  }

  /** Live "12 / 120" character counters for inputs with maxlength. */
  function initCounters(root = document) {
    root.querySelectorAll("[data-counter-for]").forEach((counter) => {
      const input = document.getElementById(counter.dataset.counterFor);
      if (!input || input.dataset.counterBound) return;
      input.dataset.counterBound = "1";
      const update = () => { counter.textContent = `${input.value.length} / ${input.maxLength}`; };
      input.addEventListener("input", update);
      update();
    });
  }

  // Keep aria-invalid in step with the browser's :user-invalid state, so screen
  // readers hear about an error at the same moment it becomes visible.
  function syncAriaInvalid(event) {
    const input = event.target;
    if (!input.matches || !input.matches("input, textarea, select")) return;
    if (input.matches(":user-invalid")) input.setAttribute("aria-invalid", "true");
    else if (event.type !== "focus") input.removeAttribute("aria-invalid");
  }
  document.addEventListener("blur", syncAriaInvalid, true);
  document.addEventListener("input", (event) => {
    if (event.target.getAttribute && event.target.getAttribute("aria-invalid") === "true") syncAriaInvalid(event);
  });

  function debounce(fn, wait = 250) {
    let timer = null;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), wait);
    };
  }

  function formToObject(form) {
    const data = {};
    new FormData(form).forEach((value, key) => { data[key] = typeof value === "string" ? value : ""; });
    return data;
  }

  /** Read <form> filter values and keep them in the address bar (?status=open). */
  function readFilters(form) {
    const values = {};
    form.querySelectorAll("input[name], select[name]").forEach((el) => {
      if (el.value) values[el.name] = el.value.trim();
    });
    return values;
  }

  function applyFiltersFromUrl(form) {
    const params = new URLSearchParams(window.location.search);
    let changed = false;
    form.querySelectorAll("input[name], select[name]").forEach((el) => {
      if (params.has(el.name)) { el.value = params.get(el.name); changed = true; }
    });
    return changed;
  }

  function syncUrl(values) {
    const params = new URLSearchParams(values);
    const query = params.toString();
    history.replaceState(null, "", window.location.pathname + (query ? `?${query}` : ""));
  }

  function bumpStat(element, value) {
    if (element.textContent === String(value)) return;
    element.textContent = value;
    const card = element.closest(".stat");
    if (card) {
      card.classList.remove("flash");
      void card.offsetWidth; // restart the CSS animation
      card.classList.add("flash");
    }
  }

  /** Update every element marked data-stat="open" etc. with fresh counts. */
  function applyStats(stats) {
    document.querySelectorAll("[data-stat]").forEach((element) => {
      const key = element.dataset.stat;
      if (key in stats) bumpStat(element, stats[key]);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    refreshTimes();
    initCounters();
    setInterval(() => refreshTimes(), 30000);
  });

  return {
    config, user, labels, pageData, ApiError, api, h, icon,
    formatDateTime, formatRelative, timeEl, refreshTimes, dotted,
    statusBadge, priorityBadge, categoryBadge, initials, ticketUrl, announcementsUrl,
    toast, setBusy, emptyState, errorState,
    clearFieldErrors, showFieldErrors, initCounters, debounce, formToObject,
    readFilters, applyFiltersFromUrl, syncUrl, applyStats,
    currentTicketId: null,
  };
})();
