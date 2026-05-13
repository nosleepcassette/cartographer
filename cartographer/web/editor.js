(() => {
  const editorState = {
    notes: [],
    current: null,
    currentPayload: null,
    pendingLoad: null,
    loaded: false,
    savedBody: "",
    savedFrontmatter: {},
    autosaveTimer: null,
    wikiLink: null,
    wikiIndex: 0,
    inlineWireTarget: null,
    egoDepth: 1,
  };

  const C = () => window.Cartographer;

  async function render() {
    if (!editorState.loaded) {
      bindEvents();
      setEditorMode(localStorage.getItem("cart-editor-mode") || "split");
      startAutosave();
      editorState.loaded = true;
    }
    await loadNotes();
  }

  async function search(query) {
    const input = C().$("#note-search");
    if (input) input.value = query || "";
    await loadNotes();
  }

  async function loadNotes() {
    const q = C().$("#note-search")?.value.trim() || "";
    const type = C().$("#note-type-filter")?.value || "";
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (type) params.set("type", type);
    params.set("limit", "120");
    const payload = await C().api(`/api/notes?${params.toString()}`);
    editorState.notes = payload.notes || [];
    renderNoteList();
    if (!editorState.current && !editorState.pendingLoad && editorState.notes.length) {
      await loadNote(editorState.notes[0].id);
    }
  }

  function renderNoteList() {
    const list = C().$("#note-list");
    if (!list) return;
    if (!editorState.notes.length) {
      list.innerHTML = '<p class="muted">no notes found</p>';
      return;
    }
    list.innerHTML = editorState.notes.map((note) => `
      <button class="note-item ${editorState.current === note.id ? "is-active" : ""}" type="button" data-note-id="${C().escapeHtml(note.id)}">
        <strong>${C().escapeHtml(note.title)}</strong>
        <span>${C().escapeHtml(note.type)} / ${C().escapeHtml(note.relative_path || note.path)}</span>
      </button>
    `).join("");
    C().$$("[data-note-id]", list).forEach((button) => {
      button.addEventListener("click", () => loadNote(button.dataset.noteId));
    });
  }

  async function loadNote(noteId, options = {}) {
    if (!noteId) return;
    if (editorState.current && editorState.current !== noteId && isDirty()) {
      await saveNote({ silent: true, reloadList: true });
    }
    hideWikiDropdown();
    hideInlineWirePopover();
    const payload = await C().api(`/api/note/${encodeURIComponent(noteId)}`);
    editorState.current = payload.note.id;
    editorState.currentPayload = payload;
    editorState.savedBody = payload.body || "";
    editorState.savedFrontmatter = { ...(payload.frontmatter || {}) };

    const editor = C().$("#note-editor");
    const meta = C().$("#editor-meta");
    if (meta) {
      meta.textContent = `${payload.note.type} / ${payload.note.relative_path || payload.note.path} / ${payload.note.word_count} words`;
    }
    if (editor) {
      editor.value = payload.body || "";
      updatePreview();
      updateWordCount();
    }
    renderFrontmatter(payload.frontmatter || {});
    renderTitle();
    renderNoteWires(payload.wires || []);
    renderSimilarNotes(payload.note.id);
    renderNoteList();
    if (options.updateHash !== false) {
      C().setHash("notes", payload.note.id);
    }
    if (!C().$("#ego-panel")?.hidden) {
      renderEgoGraph(payload.note.id, editorState.egoDepth);
    }
    clearDirtyState();
  }

  async function loadAndSwitch(noteId) {
    editorState.pendingLoad = noteId;
    C().activateTab("notes");
    try {
      await loadNote(noteId);
    } finally {
      if (editorState.pendingLoad === noteId) {
        editorState.pendingLoad = null;
      }
    }
  }

  function renderTitle() {
    const title = C().$("#editor-title");
    if (!title) return;
    const base = editorState.currentPayload?.note?.title || editorState.current || "select a note";
    title.textContent = `${base}${isDirty() ? " *" : ""}`;
    title.classList.toggle("is-dirty", isDirty());
  }

  function renderFrontmatter(frontmatter) {
    const get = (key) => C().$(`[data-frontmatter="${key}"]`);
    const tags = Array.isArray(frontmatter.tags) ? frontmatter.tags.join(", ") : "";
    if (get("title")) get("title").value = frontmatter.title || "";
    if (get("type")) get("type").value = frontmatter.type || "";
    if (get("tags")) get("tags").value = tags;
    if (get("status")) get("status").value = frontmatter.status || "";
  }

  function collectFrontmatter() {
    const base = { ...(editorState.currentPayload?.frontmatter || {}) };
    const read = (key) => C().$(`[data-frontmatter="${key}"]`)?.value.trim() || "";
    base.title = read("title") || base.title;
    base.type = read("type") || base.type || "note";
    const rawTags = read("tags");
    base.tags = rawTags ? rawTags.split(",").map((item) => item.trim()).filter(Boolean) : [];
    const status = read("status");
    if (status) base.status = status;
    else delete base.status;
    return base;
  }

  function sameFrontmatter(left, right) {
    return JSON.stringify(left || {}) === JSON.stringify(right || {});
  }

  function isDirty() {
    const editor = C().$("#note-editor");
    if (!editor || !editorState.current) return false;
    return editor.value !== editorState.savedBody || !sameFrontmatter(collectFrontmatter(), editorState.savedFrontmatter);
  }

  function markDirty() {
    renderTitle();
  }

  function clearDirtyState() {
    renderTitle();
  }

  function startAutosave() {
    window.clearInterval(editorState.autosaveTimer);
    editorState.autosaveTimer = window.setInterval(() => {
      if (isDirty()) saveNote({ silent: true, reloadList: true });
    }, 30000);
  }

  async function saveNote(options = {}) {
    if (!editorState.current) return null;
    const editor = C().$("#note-editor");
    const payload = {
      body: editor?.value || "",
      frontmatter: collectFrontmatter(),
    };
    const button = C().$("#save-note");
    if (button && !options.silent) button.textContent = "saving";
    const saved = await C().api(`/api/note/${encodeURIComponent(editorState.current)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    editorState.current = saved.note.id;
    editorState.currentPayload = saved;
    editorState.savedBody = saved.body || payload.body;
    editorState.savedFrontmatter = { ...(saved.frontmatter || payload.frontmatter) };
    renderTitle();
    renderNoteWires(saved.wires || []);
    if (options.reloadList !== false) {
      await loadNotes();
    }
    if (button) {
      button.textContent = "saved";
      button.classList.add("just-saved");
      window.setTimeout(() => {
        button.textContent = "save";
        button.classList.remove("just-saved");
      }, 1000);
    }
    return saved;
  }

  function renderNoteWires(wires) {
    const output = C().$("#note-wires");
    if (!output) return;
    if (!wires.length) {
      output.innerHTML = '<p class="muted">no wires yet</p>';
      return;
    }
    output.innerHTML = wires.slice(0, 16).map((wire, index) => {
      const connected = wire.source_note === editorState.current ? wire.target_note : wire.source_note;
      return `
        <div class="wire-row editable-wire" data-wire-index="${index}">
          <button class="wire-node" type="button" data-wire-open="${C().escapeHtml(wire.source_note)}">${C().escapeHtml(wire.source_note)}</button>
          <span>--</span>
          <button class="wire-predicate-button" type="button" data-wire-predicate="${index}">${C().escapeHtml(wire.predicate)}</button>
          <span>--></span>
          <button class="wire-node" type="button" data-wire-open="${C().escapeHtml(wire.target_note)}">${C().escapeHtml(wire.target_note)}</button>
          <button class="danger-button mini-button wire-delete" type="button" data-wire-delete="${index}">x</button>
          <div class="muted">${C().escapeHtml(wire.direction)} / ${C().escapeHtml(connected)}</div>
        </div>
      `;
    }).join("");
    C().$$("[data-wire-open]", output).forEach((button) => {
      button.addEventListener("click", () => loadNote(button.dataset.wireOpen));
    });
    C().$$("[data-wire-delete]", output).forEach((button) => {
      button.addEventListener("click", async () => deleteWire(wires[Number(button.dataset.wireDelete)]));
    });
    C().$$("[data-wire-predicate]", output).forEach((button) => {
      button.addEventListener("click", () => editWirePredicate(button, wires[Number(button.dataset.wirePredicate)]));
    });
  }

  async function deleteWire(wire) {
    if (!wire || !window.confirm("Delete this wire?")) return;
    await C().api("/api/wire/delete", {
      method: "POST",
      body: JSON.stringify({
        path: wire.path,
        source_note: wire.source_note,
        target_note: wire.target_note,
        predicate: wire.predicate,
      }),
    });
    await refreshCurrentNote();
  }

  async function editWirePredicate(button, wire) {
    const predicates = await predicatesForSelect();
    const select = document.createElement("select");
    select.className = "wire-predicate-select";
    select.innerHTML = predicates.map((predicate) => `
      <option value="${C().escapeHtml(predicate.name)}" ${predicate.name === wire.predicate ? "selected" : ""}>${C().escapeHtml(predicate.name)}</option>
    `).join("");
    button.replaceWith(select);
    select.focus();
    select.addEventListener("change", async () => {
      await C().api("/api/wire/update", {
        method: "POST",
        body: JSON.stringify({
          path: wire.path,
          source_note: wire.source_note,
          target_note: wire.target_note,
          predicate: wire.predicate,
          new_predicate: select.value,
        }),
      });
      await refreshCurrentNote();
    });
    select.addEventListener("blur", () => refreshCurrentNote());
  }

  async function refreshCurrentNote() {
    if (editorState.current) await loadNote(editorState.current, { updateHash: false });
  }

  function updatePreview() {
    const preview = C().$("#note-preview");
    const editor = C().$("#note-editor");
    if (!preview || !editor) return;
    preview.innerHTML = C().mdToHtml(editor.value);
  }

  function updateWordCount() {
    const editor = C().$("#note-editor");
    const counter = C().$("#word-count");
    if (!editor || !counter) return;
    const text = editor.value;
    const words = text.trim() ? text.trim().split(/\s+/).length : 0;
    const chars = text.length;
    const line = text.slice(0, editor.selectionStart).split("\n").length;
    counter.textContent = `${words} words / ${chars.toLocaleString()} chars / line ${line}`;
  }

  function setEditorMode(mode) {
    const safeMode = ["edit", "split", "preview"].includes(mode) ? mode : "split";
    const split = C().$(".editor-split");
    if (split) split.dataset.mode = safeMode;
    C().$$("[data-view]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.view === safeMode);
    });
    localStorage.setItem("cart-editor-mode", safeMode);
  }

  async function createNoteFromDialog(event) {
    event.preventDefault();
    const title = C().$("#nn-title")?.value.trim();
    if (!title) return;
    const type = C().$("#nn-type")?.value || "note";
    const tags = (C().$("#nn-tags")?.value || "").split(",").map((item) => item.trim()).filter(Boolean);
    const template = C().$("#nn-template")?.value || "blank";
    let body = `# ${title}\n\n`;
    if (template === "daily") body = `# ${title}\n\n## log\n\n- \n\n## notes\n\n`;
    if (template === "project") body = `# ${title}\n\n## outcome\n\n## next steps\n\n- \n`;
    const payload = await C().api("/api/note/new", {
      method: "POST",
      body: JSON.stringify({ title, type, body, tags }),
    });
    C().$("#new-note-dialog")?.close();
    C().$("#nn-title").value = "";
    C().$("#nn-tags").value = "";
    editorState.current = payload.note.id;
    await loadNotes();
    await loadNote(payload.note.id);
  }

  function openNewNoteDialog() {
    const dialog = C().$("#new-note-dialog");
    if (!dialog) return;
    dialog.showModal();
    window.setTimeout(() => C().$("#nn-title")?.focus(), 0);
  }

  async function deleteCurrentNote() {
    if (!editorState.current) return;
    const noteTitle = editorState.currentPayload?.note?.title || editorState.current;
    if (!window.confirm(`Delete ${noteTitle}?`)) return;
    await C().api(`/api/note/${encodeURIComponent(editorState.current)}?confirm=1`, {
      method: "DELETE",
    });
    editorState.current = null;
    editorState.currentPayload = null;
    C().$("#note-editor").value = "";
    updatePreview();
    await loadNotes();
  }

  function applyMarkdown(action) {
    if (action === "wire-selection") {
      openInlineWirePopover();
      return;
    }
    const textarea = C().$("#note-editor");
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selected = textarea.value.slice(start, end);
    const before = textarea.value.slice(0, start);
    const after = textarea.value.slice(end);
    let replacement = selected;

    if (action === "bold") replacement = `**${selected || "bold"}**`;
    if (action === "italic") replacement = `*${selected || "italic"}*`;
    if (action === "heading") replacement = `## ${selected || "heading"}`;
    if (action === "rule") replacement = `${selected}\n---\n`;
    if (action === "link") replacement = `[${selected || "text"}](url)`;
    if (action === "code") replacement = `\`${selected || "code"}\``;
    if (action === "list") replacement = selected
      ? selected.split(/\r?\n/).map((line) => `- ${line}`).join("\n")
      : "- item";

    textarea.value = before + replacement + after;
    textarea.focus();
    textarea.setSelectionRange(start, start + replacement.length);
    handleEditorInput({ currentTarget: textarea });
  }

  function handleEditorInput(event) {
    const textarea = event.currentTarget;
    const pos = textarea.selectionStart;
    const text = textarea.value;
    if (text.slice(pos - 2, pos) === "[[") {
      editorState.wikiLink = { active: true, startPos: pos - 2, query: "" };
      updateWikiDropdown("", textarea);
    } else if (editorState.wikiLink?.active) {
      const afterBrackets = text.slice(editorState.wikiLink.startPos + 2, pos);
      if (afterBrackets.includes("]]") || afterBrackets.includes("\n") || pos < editorState.wikiLink.startPos + 2) {
        hideWikiDropdown();
      } else {
        editorState.wikiLink.query = afterBrackets;
        updateWikiDropdown(afterBrackets, textarea);
      }
    }
    updatePreview();
    updateWordCount();
    markDirty();
  }

  const debouncedWikiSearch = C().debounce(async (query, textarea) => {
    const dropdown = wikiDropdown();
    const payload = await C().api(`/api/notes?q=${encodeURIComponent(query)}&limit=8`);
    const notes = payload.notes || [];
    editorState.wikiIndex = 0;
    dropdown.innerHTML = notes.length ? notes.map((note, index) => `
      <button type="button" class="wiki-item ${index === 0 ? "is-focused" : ""}" data-wiki-id="${C().escapeHtml(note.id)}">
        <strong>${C().escapeHtml(note.title)}</strong>
        <span>${C().escapeHtml(note.id)}</span>
      </button>
    `).join("") : '<div class="wiki-empty">no matches</div>';
    C().$$("[data-wiki-id]", dropdown).forEach((button) => {
      button.addEventListener("mousedown", (event) => {
        event.preventDefault();
        insertWikiLink(button.dataset.wikiId);
      });
    });
    positionWikiDropdown(textarea);
  }, 180);

  function updateWikiDropdown(query, textarea) {
    const dropdown = wikiDropdown();
    dropdown.hidden = false;
    dropdown.innerHTML = '<div class="wiki-empty">searching...</div>';
    positionWikiDropdown(textarea);
    debouncedWikiSearch(query, textarea);
  }

  function wikiDropdown() {
    let dropdown = C().$("#wiki-link-dropdown");
    if (!dropdown) {
      dropdown = document.createElement("div");
      dropdown.id = "wiki-link-dropdown";
      dropdown.className = "wiki-link-dropdown";
      document.body.appendChild(dropdown);
    }
    return dropdown;
  }

  function positionWikiDropdown(textarea) {
    const rect = textarea.getBoundingClientRect();
    const lineHeight = 22;
    const lines = textarea.value.slice(0, textarea.selectionStart).split("\n");
    const y = rect.top + Math.min(rect.height - 12, lines.length * lineHeight - textarea.scrollTop + 8);
    wikiDropdown().style.left = `${rect.left + 12}px`;
    wikiDropdown().style.top = `${y}px`;
    wikiDropdown().style.width = `${Math.min(420, rect.width - 24)}px`;
  }

  function hideWikiDropdown() {
    const dropdown = C().$("#wiki-link-dropdown");
    if (dropdown) dropdown.hidden = true;
    editorState.wikiLink = null;
  }

  function moveWikiFocus(delta) {
    const items = C().$$(".wiki-item");
    if (!items.length) return;
    editorState.wikiIndex = Math.max(0, Math.min(items.length - 1, editorState.wikiIndex + delta));
    items.forEach((item, index) => item.classList.toggle("is-focused", index === editorState.wikiIndex));
  }

  function insertWikiLink(noteId) {
    const textarea = C().$("#note-editor");
    if (!textarea || !editorState.wikiLink) return;
    const start = editorState.wikiLink.startPos;
    const end = textarea.selectionStart;
    textarea.value = `${textarea.value.slice(0, start)}[[${noteId}]]${textarea.value.slice(end)}`;
    const nextPos = start + noteId.length + 4;
    textarea.setSelectionRange(nextPos, nextPos);
    textarea.focus();
    hideWikiDropdown();
    handleEditorInput({ currentTarget: textarea });
  }

  function handleEditorKeys(event) {
    const textarea = event.currentTarget;
    if (editorState.wikiLink?.active && !C().$("#wiki-link-dropdown")?.hidden) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveWikiFocus(1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        moveWikiFocus(-1);
        return;
      }
      if (event.key === "Enter") {
        const item = C().$$(".wiki-item")[editorState.wikiIndex] || C().$(".wiki-item");
        if (item) {
          event.preventDefault();
          insertWikiLink(item.dataset.wikiId);
          return;
        }
      }
      if (event.key === "Escape") {
        event.preventDefault();
        hideWikiDropdown();
        return;
      }
    }
    if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "w") {
      event.preventDefault();
      openInlineWirePopover();
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveNote();
      return;
    }
    if (event.key === "Tab") {
      event.preventDefault();
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      textarea.value = textarea.value.slice(0, start) + "  " + textarea.value.slice(end);
      textarea.setSelectionRange(start + 2, start + 2);
      handleEditorInput({ currentTarget: textarea });
      return;
    }
    if (event.key === "Enter") {
      const lineStart = textarea.value.lastIndexOf("\n", textarea.selectionStart - 1) + 1;
      const line = textarea.value.slice(lineStart, textarea.selectionStart);
      const indent = line.match(/^(\s*(?:-\s+)?)/)?.[1] || "";
      if (indent) {
        event.preventDefault();
        const start = textarea.selectionStart;
        textarea.value = textarea.value.slice(0, start) + `\n${indent}` + textarea.value.slice(textarea.selectionEnd);
        textarea.setSelectionRange(start + indent.length + 1, start + indent.length + 1);
        handleEditorInput({ currentTarget: textarea });
      }
    }
  }

  async function predicatesForSelect() {
    if (editorState.predicates) return editorState.predicates;
    editorState.predicates = await C().api("/api/predicates");
    return editorState.predicates;
  }

  async function openInlineWirePopover() {
    if (!editorState.current) return;
    const textarea = C().$("#note-editor");
    const popover = C().$("#inline-wire-popover");
    if (!textarea || !popover) return;
    const selected = textarea.value.slice(textarea.selectionStart, textarea.selectionEnd).trim();
    popover.dataset.selectedText = selected;
    popover.hidden = false;
    const rect = textarea.getBoundingClientRect();
    popover.style.left = `${Math.min(window.innerWidth - 380, rect.left + 24)}px`;
    popover.style.top = `${Math.min(window.innerHeight - 260, rect.top + 90)}px`;
    const select = C().$("#inline-wire-predicate");
    const predicates = await predicatesForSelect();
    if (select) {
      select.innerHTML = predicates.map((predicate) => `<option value="${C().escapeHtml(predicate.name)}">${C().escapeHtml(predicate.name)}</option>`).join("");
    }
    C().$("#inline-wire-target").value = "";
    C().$("#inline-wire-results").innerHTML = "";
    C().$("#inline-wire-target")?.focus();
  }

  function hideInlineWirePopover() {
    const popover = C().$("#inline-wire-popover");
    if (popover) popover.hidden = true;
    editorState.inlineWireTarget = null;
  }

  async function searchInlineWireTarget() {
    const query = C().$("#inline-wire-target")?.value.trim() || "";
    const output = C().$("#inline-wire-results");
    if (!output) return;
    if (!query) {
      output.innerHTML = "";
      return;
    }
    const payload = await C().api(`/api/notes?q=${encodeURIComponent(query)}&limit=6`);
    output.innerHTML = (payload.notes || []).map((note) => `
      <button type="button" data-inline-target="${C().escapeHtml(note.id)}" data-inline-title="${C().escapeHtml(note.title)}">
        ${C().escapeHtml(note.title)} <span class="muted">${C().escapeHtml(note.type)}</span>
      </button>
    `).join("");
    C().$$("[data-inline-target]", output).forEach((button) => {
      button.addEventListener("click", () => {
        editorState.inlineWireTarget = { id: button.dataset.inlineTarget, title: button.dataset.inlineTitle };
        C().$("#inline-wire-target").value = button.dataset.inlineTitle || button.dataset.inlineTarget;
        output.innerHTML = "";
      });
    });
  }

  async function createInlineWire() {
    if (!editorState.current || !editorState.inlineWireTarget) return;
    const popover = C().$("#inline-wire-popover");
    await C().api("/api/wire/create", {
      method: "POST",
      body: JSON.stringify({
        source_note: editorState.current,
        target_note: editorState.inlineWireTarget.id,
        predicate: C().$("#inline-wire-predicate")?.value || "relates_to",
        note: popover?.dataset.selectedText || null,
        reviewed: true,
        method: "interactive",
        confidence: "high",
      }),
    });
    hideInlineWirePopover();
    await refreshCurrentNote();
  }

  function wireFromHere() {
    if (!editorState.current) return;
    const title = editorState.currentPayload?.note?.title || editorState.current;
    window.CartWiring?.setSource(editorState.current, title);
    C().activateTab("wires");
    setTimeout(() => C().$("#wire-target-input")?.focus(), 100);
  }

  function traceFromHere() {
    if (!editorState.current) return;
    C().traceFromNote(editorState.current);
  }

  async function renderSimilarNotes(noteId) {
    const output = C().$("#similar-notes");
    if (!output || !noteId) return;
    output.innerHTML = '<p class="muted">checking...</p>';
    try {
      const payload = await C().api(`/api/note/${encodeURIComponent(noteId)}/similar?limit=5`);
      const items = payload.similar || [];
      output.innerHTML = items.length ? items.map((item) => `
        <button class="similar-item" type="button" data-similar-id="${C().escapeHtml(item.id)}">
          <strong>${C().escapeHtml(item.title)}</strong>
          <span>${C().escapeHtml(item.type)} / ${Math.round(Number(item.score || 0) * 10) / 10}</span>
        </button>
      `).join("") : '<p class="muted">no related notes yet</p>';
      C().$$("[data-similar-id]", output).forEach((button) => {
        button.addEventListener("click", () => loadNote(button.dataset.similarId));
      });
    } catch (error) {
      output.innerHTML = `<p class="error">${C().escapeHtml(error.message)}</p>`;
    }
  }

  async function renderEgoGraph(noteId, depth = 1) {
    const output = C().$("#ego-graph");
    if (!output || !noteId) return;
    output.innerHTML = '<p class="muted">loading graph...</p>';
    const payload = await C().api(`/api/note/${encodeURIComponent(noteId)}/ego?depth=${depth}`);
    window.CartEgoGraph?.render(output, payload, loadNote);
  }

  function bindEvents() {
    C().$("#note-search")?.addEventListener("input", C().debounce(loadNotes, 250));
    C().$("#note-type-filter")?.addEventListener("change", loadNotes);
    C().$("#save-note")?.addEventListener("click", () => saveNote());
    C().$("#new-note")?.addEventListener("click", openNewNoteDialog);
    C().$("#delete-note")?.addEventListener("click", deleteCurrentNote);
    C().$("#wire-from-note")?.addEventListener("click", wireFromHere);
    C().$("#trace-from-note")?.addEventListener("click", traceFromHere);
    C().$("#toggle-ego")?.addEventListener("click", () => {
      const panel = C().$("#ego-panel");
      if (!panel) return;
      panel.hidden = !panel.hidden;
      if (!panel.hidden && editorState.current) renderEgoGraph(editorState.current, editorState.egoDepth);
    });
    C().$("#expand-ego")?.addEventListener("click", () => {
      editorState.egoDepth = editorState.egoDepth === 1 ? 2 : 1;
      C().$("#expand-ego").textContent = editorState.egoDepth === 1 ? "expand" : "collapse";
      if (editorState.current) renderEgoGraph(editorState.current, editorState.egoDepth);
    });
    C().$("#toggle-frontmatter")?.addEventListener("click", () => {
      const panel = C().$("#frontmatter-panel");
      if (panel) panel.hidden = !panel.hidden;
    });
    C().$("#note-editor")?.addEventListener("input", handleEditorInput);
    C().$("#note-editor")?.addEventListener("click", updateWordCount);
    C().$("#note-editor")?.addEventListener("keyup", updateWordCount);
    C().$("#note-editor")?.addEventListener("keydown", handleEditorKeys);
    C().$$("[data-frontmatter]").forEach((input) => {
      input.addEventListener("input", markDirty);
    });
    C().$$("[data-md]").forEach((button) => {
      button.addEventListener("click", () => applyMarkdown(button.dataset.md));
    });
    C().$$("[data-view]").forEach((button) => {
      button.addEventListener("click", () => setEditorMode(button.dataset.view));
    });
    C().$("#new-note-dialog form")?.addEventListener("submit", createNoteFromDialog);
    C().$("#nn-cancel")?.addEventListener("click", () => C().$("#new-note-dialog")?.close());
    C().$("#inline-wire-target")?.addEventListener("input", C().debounce(searchInlineWireTarget, 200));
    C().$("#inline-wire-cancel")?.addEventListener("click", hideInlineWirePopover);
    C().$("#inline-wire-create")?.addEventListener("click", createInlineWire);
  }

  window.CartEditor = {
    render,
    search,
    save: () => saveNote(),
    loadNote,
    loadAndSwitch,
    wireFromHere,
    traceFromHere,
    current: () => editorState.current,
  };
})();
