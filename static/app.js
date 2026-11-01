"use strict";

const $ = (selector) => document.querySelector(selector);
const state = { view: "chat", sessionId: null, documents: [], sessions: [], notes: [], citations: [], trace: [], health: {}, busy: false, noticeTimer: null };
const titles = { chat: "Document assistant", library: "Library", notes: "Saved notes" };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function button(label, className, action) {
  const node = element("button", className, label);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}
function notify(message, error = false) {
  const node = $("#notice");
  clearTimeout(state.noticeTimer);
  node.replaceChildren(element("span", "", message), button("×", "", () => { node.hidden = true; }));
  node.lastChild.setAttribute("aria-label", "Dismiss notification");
  node.classList.toggle("error", error);
  node.setAttribute("role", error ? "alert" : "status");
  node.hidden = false;
  if (!error) state.noticeTimer = setTimeout(() => { node.hidden = true; }, 6500);
}
async function api(path, options = {}) {
  const headers = { ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...options.headers };
  let response;
  try { response = await fetch(path, { ...options, headers }); }
  catch { throw new Error("Could not connect to the server. Check that the app is running and try again."); }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : `Request failed (HTTP ${response.status}).`;
    throw new Error(detail);
  }
  return data;
}
function setBusy(busy) {
  state.busy = busy;
  document.querySelectorAll("button:not(.close-dialog):not(#mode-help):not(.context-tab)").forEach((node) => {
    if (!node.closest("#notice")) node.disabled = busy;
  });
  $("#message-input").disabled = busy;
  $("#upload-input").disabled = busy;
  $("#chat-form").setAttribute("aria-busy", String(busy));
}
async function run(action) {
  if (state.busy) return;
  setBusy(true);
  try { return await action(); }
  catch (error) { notify(error.message || "Something went wrong. Please try again.", true); }
  finally { setBusy(false); }
}
function dateLabel(value) {
  if (!value) return "Just created";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("en-US", { day: "2-digit", month: "2-digit", year: "numeric" }).format(date);
}
function showView(view) {
  state.view = view;
  $("#context-panel").classList.remove("mobile-open");
  $("#show-context").setAttribute("aria-expanded", "false");
  Object.keys(titles).forEach((key) => { $(`#${key}-view`).hidden = key !== view; });
  document.querySelectorAll("[data-view]").forEach((node) => {
    const active = node.dataset.view === view;
    node.classList.toggle("active", active);
    if (active) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current");
  });
  $("#view-title").textContent = titles[view];
}
function updateHealth(health) {
  state.health = health;
  const isDemo = health.mode !== "openai";
  $("#mode-badge").textContent = isDemo ? "Demo · Excerpts" : "OpenAI · Configured";
  $("#owner-name").textContent = health.owner_name || "You";
  $(".avatar").textContent = (health.owner_name || "You").slice(0, 1).toUpperCase();
  $("#mode-explanation").replaceChildren();
  const copy = isDemo
    ? "You are using the offline demo: it searches and returns document excerpts using a fixed workflow. This mode does not use a language model or generate summaries and reasoning like OpenAI."
    : "The app is using OpenAI to generate answers and call document search and reading tools. Depending on your settings, processed content may be sent to OpenAI.";
  $("#mode-explanation").append(element("p", "", copy));
  const config = element("p", "", "To use a live model, configure the provider and API key in ");
  config.append(element("code", "", ".env"), document.createTextNode(" and restart the app. See the project README for configuration variables. Do not enter your API key in the chat."));
  $("#mode-explanation").append(config);
}
function renderSessions() {
  const list = $("#session-list");
  list.replaceChildren();
  if (!state.sessions.length) list.append(element("p", "sidebar-empty", "Your ideas start here."));
  state.sessions.forEach((session) => {
    const node = button(session.title || "New chat", "session-item", () => run(() => loadSession(session.id)));
    node.classList.toggle("active", session.id === state.sessionId);
    node.title = session.title || "New chat";
    list.append(node);
  });
}
async function refreshSessions() { state.sessions = await api("/api/sessions"); renderSessions(); }
function renderDocuments() {
  const list = $("#document-list");
  list.replaceChildren();
  $("#document-count").textContent = state.documents.length;
  $("#onboarding").hidden = state.documents.length > 0;
  if (!state.documents.length) {
    const empty = element("div", "empty-state");
    empty.append(element("h2", "", "One library, endless connections."), element("p", "", "Add your documents or try the sample work documents to get started."), button("Try sample data", "small-button", seedDemo));
    list.append(empty);
  }
  state.documents.forEach((doc) => {
    const row = element("article", "document-row");
    const extension = (doc.filename || "TXT").split(".").pop().toUpperCase().slice(0, 5);
    const details = element("div", "document-details");
    details.append(element("strong", "", doc.title || doc.filename), element("small", "", `${doc.chunk_count || 0} passages · ${dateLabel(doc.created_at)}`));
    const actions = element("div", "row-actions");
    actions.append(button("View document ↗", "small-button", () => run(() => previewDocument(doc.id))), button("Delete", "delete-button", () => deleteDocument(doc)));
    row.append(element("div", "document-icon", extension), details, actions);
    list.append(row);
  });
}
async function refreshDocuments() { state.documents = await api("/api/documents"); renderDocuments(); }
function renderNotes() {
  const list = $("#note-list");
  list.replaceChildren();
  if (!state.notes.length) {
    const empty = element("div", "empty-state");
    empty.append(element("h2", "", "Keep what matters."), element("p", "", "Click “Save note” below an answer or write a new note."));
    list.append(empty);
  }
  state.notes.forEach((note) => {
    const card = element("article", "note-card");
    const footer = element("footer");
    footer.append(element("small", "", dateLabel(note.created_at)), button("View full note", "text-button", () => previewNote(note)), button("Delete", "delete-button", () => deleteNote(note)));
    card.append(element("h2", "", note.title), element("p", "", note.content), footer);
    list.append(card);
  });
}
async function refreshNotes() { state.notes = await api("/api/notes"); renderNotes(); }
function showWelcome(show) { $("#welcome").hidden = !show; }
function scrollChat() { const node = $("#conversation-scroll"); node.scrollTo({ top: node.scrollHeight, behavior: "smooth" }); }
function showContext(citations = [], trace = []) {
  state.citations = citations || []; state.trace = trace || [];
  $("#source-count").textContent = state.citations.length;
  const sources = $("#sources-panel");
  sources.replaceChildren();
  if (!state.citations.length) {
    const empty = element("div", "context-empty");
    empty.append(element("h2", "", "Sources to verify"), element("p", "", "No document passages were cited in this answer."));
    sources.append(empty);
  }
  state.citations.forEach((citation, index) => {
    const card = button("", "source-card", () => previewCitation(citation, index));
    const title = element("div");
    title.append(element("span", "source-num", `${index + 1}`), element("strong", "", citation.title || "Document"));
    card.append(title, element("p", "", citation.content || ""), element("small", "", `${citation.page ? `Page ${citation.page} · ` : ""}View excerpt ↗`));
    sources.append(card);
  });
  const traceList = $("#trace-list"); traceList.replaceChildren();
  state.trace.forEach((item, index) => {
    const row = element("div", "trace-step");
    row.append(element("div"));
    row.firstChild.append(element("strong", "", `${item.step || index + 1}. ${item.tool || "Operation"}`), element("p", "", typeof item.detail === "string" ? item.detail : JSON.stringify(item.detail || "")));
    traceList.append(row);
  });
}
function addMessage(message, response = {}) {
  const node = element("article", `message ${message.role === "user" ? "user" : "assistant"}`);
  const isAssistant = message.role !== "user";
  node.append(element("div", "message-role", isAssistant ? "PERSONAL AGENTICRAG" : "YOU"), element("div", "message-body", message.content));
  if (isAssistant) {
    const actions = element("div", "message-actions");
    const citations = message.citations || [];
    citations.forEach((citation, index) => actions.append(button(`[${index + 1}] ${citation.title || "Document"}${citation.page ? ` · p. ${citation.page}` : ""}`, "citation-chip", () => { showContext(citations, message.trace); previewCitation(citation, index); })));
    actions.append(button("＋ Save note", "save-answer", () => openNote(message.content)));
    const mode = response.mode || state.health.mode;
    const elapsed = response.elapsed_ms ? ` · ${(response.elapsed_ms / 1000).toFixed(1)} sec` : "";
    actions.append(element("span", "message-meta", `${mode === "openai" ? "OpenAI" : "Demo · excerpts"}${elapsed}`));
    node.append(actions);
  }
  $("#messages").append(node);
  return node;
}
async function loadSession(id) {
  const session = await api(`/api/sessions/${encodeURIComponent(id)}`);
  state.sessionId = session.id || id;
  $("#messages").replaceChildren();
  const messages = session.messages || [];
  showWelcome(messages.length === 0);
  messages.forEach((message) => addMessage(message));
  const latest = [...messages].reverse().find((message) => message.role === "assistant");
  showContext(latest?.citations || [], latest?.trace || []);
  renderSessions(); showView("chat"); scrollChat();
}
async function newChat() {
  await run(async () => {
    const session = await api("/api/sessions", { method: "POST", body: JSON.stringify({}) });
    state.sessionId = session.id;
    $("#messages").replaceChildren(); showWelcome(true); showView("chat"); showContext();
    await refreshSessions();
  });
  $("#message-input").focus();
}
async function sendMessage(event) {
  event.preventDefault();
  const input = $("#message-input");
  const text = input.value.trim();
  if (!text || state.busy) return;
  if (!state.documents.length) { notify("Add a document or click “Try sample data” before asking a question.", true); return; }
  await run(async () => {
    showWelcome(false);
    const pendingUser = addMessage({ role: "user", content: text });
    input.value = "";
    const pending = element("div", "thinking");
    pending.setAttribute("role", "status");
    pending.append(element("i"), element("i"), element("i"), element("span", "", "Searching your documents…"));
    $("#messages").append(pending); scrollChat();
    try {
      const data = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text, session_id: state.sessionId, top_k: 6 }) });
      state.sessionId = data.session_id;
      addMessage({ role: "assistant", content: data.answer, citations: data.citations, trace: data.trace }, data);
      showContext(data.citations, data.trace);
      await refreshSessions().catch(() => notify("The answer is ready, but the chat list could not be updated. Reload the page when the connection is stable.", true));
    } catch (error) {
      pendingUser.remove();
      input.value = text;
      showWelcome($("#messages").children.length <= 1);
      throw error;
    } finally { pending.remove(); scrollChat(); }
  });
  input.focus();
}
function openPreview(title, label, chunks) {
  $("#preview-title").textContent = title;
  $("#preview-label").textContent = label;
  const content = $("#preview-content"); content.replaceChildren();
  chunks.forEach((chunk, index) => {
    content.append(element("h3", "", `${chunk.page ? `Page ${chunk.page} · ` : ""}Passage ${chunk.ordinal !== undefined ? chunk.ordinal + 1 : index + 1}`), element("pre", "", chunk.content || ""));
  });
  if (!chunks.length) content.append(element("p", "", "This document has no content passages."));
  $("#preview-dialog").showModal();
}
function previewCitation(citation, index = 0) {
  openPreview(citation.title || "Reference source", `CITATION [${index + 1}]${citation.page ? ` · PAGE ${citation.page}` : ""}`, [citation]);
}
async function previewDocument(id) {
  const doc = await api(`/api/documents/${encodeURIComponent(id)}`);
  openPreview(doc.title || doc.filename, "LIBRARY DOCUMENT", doc.chunks || []);
}
function previewNote(note) { openPreview(note.title, "SAVED NOTE", [{ content: note.content }]); }
function openNote(content = "") {
  $("#note-title").value = "";
  $("#note-content").value = content;
  $("#note-dialog").showModal();
  $("#note-title").focus();
}
async function saveNote(event) {
  event.preventDefault();
  const title = $("#note-title").value.trim();
  const content = $("#note-content").value.trim();
  if (!title || !content) return;
  await run(async () => {
    await api("/api/notes", { method: "POST", body: JSON.stringify({ title, content }) });
    await refreshNotes(); $("#note-dialog").close(); notify("Note saved to your workspace.");
  });
}
async function deleteDocument(doc) {
  if (!window.confirm(`Delete “${doc.title}” and its indexed passages?`)) return;
  await run(async () => {
    await api(`/api/documents/${encodeURIComponent(doc.id)}`, { method: "DELETE" });
    await refreshDocuments(); notify("Document deleted.");
  });
}
async function deleteNote(note) {
  if (!window.confirm(`Delete note “${note.title}”?`)) return;
  await run(async () => { await api(`/api/notes/${encodeURIComponent(note.id)}`, { method: "DELETE" }); await refreshNotes(); notify("Note deleted."); });
}
function chooseUpload() { if (!state.busy) $("#upload-input").click(); }
async function uploadFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  const extension = file.name.split(".").pop().toLowerCase();
  if (!["pdf", "md", "markdown", "txt"].includes(extension)) { notify("Choose a PDF, Markdown, or TXT document.", true); event.target.value = ""; return; }
  await run(async () => {
    notify(`Reading and indexing “${file.name}”…`);
    const form = new FormData(); form.append("file", file);
    await api("/api/documents/upload", { method: "POST", body: form });
    await refreshDocuments(); notify(`Added “${file.name}”. You can ask questions about it now.`);
  });
  event.target.value = "";
}
async function seedDemo() {
  await run(async () => {
    const data = await api("/api/demo/seed", { method: "POST" });
    await refreshDocuments();
    notify(data.added ? `Added ${data.added} sample documents. Try asking about the onboarding process.` : "The sample documents are already in your library.");
  });
}
function selectContextTab(name) {
  ["sources", "activity"].forEach((key) => {
    const active = name === key;
    $(`#${key}-tab`).classList.toggle("active", active);
    $(`#${key}-tab`).setAttribute("aria-selected", String(active));
    $(`#${key}-tab`).tabIndex = active ? 0 : -1;
    $(`#${key}-panel`).hidden = !active;
  });
}
document.querySelectorAll("[data-view]").forEach((node) => node.addEventListener("click", () => showView(node.dataset.view)));
document.querySelectorAll(".starter-card").forEach((node) => node.addEventListener("click", () => { $("#message-input").value = node.dataset.prompt; $("#message-input").focus(); }));
document.querySelectorAll(".close-dialog").forEach((node) => node.addEventListener("click", () => node.closest("dialog").close()));
document.querySelectorAll("dialog").forEach((node) => node.addEventListener("click", (event) => { if (event.target === node) { const rect = node.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) node.close(); } }));
$("#new-chat").addEventListener("click", newChat);
$("#chat-form").addEventListener("submit", sendMessage);
$("#message-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); $("#chat-form").requestSubmit(); } });
$("#message-input").addEventListener("input", (event) => { event.target.style.height = "auto"; event.target.style.height = `${Math.min(event.target.scrollHeight, 180)}px`; });
["welcome-upload", "library-upload", "attach-document"].forEach((id) => $(`#${id}`).addEventListener("click", chooseUpload));
$("#upload-input").addEventListener("change", uploadFile);
$("#seed-demo").addEventListener("click", seedDemo);
$("#new-note").addEventListener("click", () => openNote());
$("#note-form").addEventListener("submit", saveNote);
$("#mode-help").addEventListener("click", () => $("#mode-dialog").showModal());
$("#show-context").addEventListener("click", () => {
  showView("chat");
  $("#context-panel").classList.add("mobile-open");
  $("#show-context").setAttribute("aria-expanded", "true");
  $("#close-context").focus();
});
$("#close-context").addEventListener("click", () => {
  $("#context-panel").classList.remove("mobile-open");
  $("#show-context").setAttribute("aria-expanded", "false");
  $("#show-context").focus();
});
$("#context-panel").addEventListener("keydown", (event) => {
  if (event.key === "Escape") $("#close-context").click();
});
["sources", "activity"].forEach((name) => {
  $(`#${name}-tab`).addEventListener("click", () => selectContextTab(name));
  $(`#${name}-tab`).addEventListener("keydown", (event) => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) { event.preventDefault(); const next = name === "sources" ? "activity" : "sources"; selectContextTab(next); $(`#${next}-tab`).focus(); } });
});
document.addEventListener("keydown", (event) => { if (event.key.toLowerCase() === "n" && !event.ctrlKey && !event.altKey && !event.metaKey && !["INPUT", "TEXTAREA"].includes(event.target.tagName) && !document.querySelector("dialog[open]")) { event.preventDefault(); newChat(); } });

async function initialize() {
  setBusy(true);
  const results = await Promise.allSettled([api("/api/health"), refreshDocuments(), refreshSessions(), refreshNotes()]);
  if (results[0].status === "fulfilled") updateHealth(results[0].value);
  else $("#mode-badge").textContent = "Not connected";
  const failed = results.find((result) => result.status === "rejected");
  if (failed) notify(failed.reason.message, true);
  setBusy(false);
  selectContextTab("sources");
}
initialize();
