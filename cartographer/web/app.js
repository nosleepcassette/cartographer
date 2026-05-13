(() => {
  const state = {
    activeTab: "graph",
    applyingHash: false,
    quickOpenIndex: 0,
    sidebarOpen: false,
    sidebarNoteId: null,
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = payload.error || response.statusText || "request failed";
      const error = new Error(message);
      error.payload = payload;
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function debounce(fn, wait = 250) {
    let timer = null;
    return (...args) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => fn(...args), wait);
    };
  }

  function mdToHtml(markdown) {
    const lines = String(markdown || "").split(/\r?\n/);
    const html = [];
    let inList = false;
    const inline = (text) => escapeHtml(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[\[([^\]]+)\]\]/g, "<code>[[$1]]</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');

    for (const line of lines) {
      if (/^\s*-\s+/.test(line)) {
        if (!inList) {
          html.push("<ul>");
          inList = true;
        }
        html.push(`<li>${inline(line.replace(/^\s*-\s+/, ""))}</li>`);
        continue;
      }
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      if (!line.trim()) html.push("");
      else if (/^---+$/.test(line.trim())) html.push("<hr>");
      else if (line.startsWith("### ")) html.push(`<h3>${inline(line.slice(4))}</h3>`);
      else if (line.startsWith("## ")) html.push(`<h2>${inline(line.slice(3))}</h2>`);
      else if (line.startsWith("# ")) html.push(`<h1>${inline(line.slice(2))}</h1>`);
      else if (line.startsWith("> ")) html.push(`<blockquote>${inline(line.slice(2))}</blockquote>`);
      else html.push(`<p>${inline(line)}</p>`);
    }
    if (inList) html.push("</ul>");
    return html.join("\n");
  }

  function parseHash() {
    const raw = window.location.hash.replace("#", "");
    const [tab, ...rest] = raw.split("/");
    return {
      tab: ["home", "notes", "graph", "wires"].includes(tab) ? tab : "graph",
      noteId: rest.join("/") || null,
    };
  }

  function setHash(tab, noteId = null) {
    const next = noteId ? `#${tab}/${encodeURIComponent(noteId)}` : `#${tab}`;
    if (window.location.hash !== next) {
      state.applyingHash = true;
      window.location.hash = next;
      window.setTimeout(() => {
        state.applyingHash = false;
      }, 0);
    }
  }

  function activateTab(tab, options = {}) {
    state.activeTab = tab;
    $$(".tab").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.tab === tab);
    });
    $$(".tab-panel").forEach((panel) => {
      panel.classList.toggle("is-active", panel.dataset.panel === tab);
    });

    if (!options.skipHash) setHash(tab);
    if (tab === "home") renderHome();
    if (tab === "notes" && window.CartEditor) window.CartEditor.render();
    if (tab === "wires" && window.CartWiring) window.CartWiring.render();
    if (tab === "graph") renderGraph();
  }

  async function applyHash() {
    const { tab, noteId } = parseHash();
    activateTab(tab, { skipHash: true });
    if (tab === "notes" && noteId && window.CartEditor) {
      await window.CartEditor.loadNote(decodeURIComponent(noteId), { updateHash: false });
    }
  }

  async function renderHome() {
    const briefOutput = $("#brief-output");
    const statsOutput = $("#stats-output");
    const attentionOutput = $("#attention-output");
    if (!briefOutput || !statsOutput) return;
    briefOutput.innerHTML = '<p class="muted">loading brief...</p>';
    statsOutput.innerHTML = '<dt>status</dt><dd>loading</dd>';
    if (attentionOutput) attentionOutput.innerHTML = '<p class="muted">checking atlas...</p>';
    try {
      const [brief, stats, attention] = await Promise.all([
        api("/api/daily-brief"),
        api("/api/stats"),
        api("/api/attention"),
      ]);
      briefOutput.innerHTML = mdToHtml(brief.markdown || "");
      statsOutput.innerHTML = [
        ["notes", stats.index?.notes],
        ["blocks", stats.index?.blocks],
        ["wires", stats.index?.wires],
        ["wire issues", stats.index?.wire_issues],
        ["graph nodes", stats.graph?.node_count],
        ["graph edges", stats.graph?.edge_count],
      ].map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value ?? 0)}</dd>`).join("");
      renderAttention(attention);
    } catch (error) {
      briefOutput.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
    }
  }

  function renderAttention(attention) {
    const output = $("#attention-output");
    if (!output) return;
    const noteButton = (note, extra = "") => `
      <button class="attention-item" type="button" data-open-note="${escapeHtml(note.id)}">
        <strong>${escapeHtml(note.title || note.id)}</strong>
        <span>${escapeHtml(note.type || "note")}${extra}</span>
      </button>
    `;
    output.innerHTML = `
      <section>
        <h3>orphans</h3>
        ${(attention.orphans || []).length ? attention.orphans.map((note) => noteButton(note)).join("") : '<p class="muted">none</p>'}
      </section>
      <section>
        <h3>stale</h3>
        ${(attention.stale || []).length ? attention.stale.map((note) => noteButton(note, ` / ${note.days_since} days`)).join("") : '<p class="muted">none</p>'}
      </section>
      <section>
        <h3>broken wires</h3>
        ${(attention.broken_wires || []).length ? attention.broken_wires.map((wire) => `
          <div class="attention-item">
            <strong>${escapeHtml(wire.source)} --${escapeHtml(wire.predicate)}--> ${escapeHtml(wire.target)}</strong>
            <span>${escapeHtml(wire.issue)}</span>
            <button class="danger-button mini-button" type="button" data-delete-broken="${escapeHtml(JSON.stringify(wire))}">delete</button>
          </div>
        `).join("") : '<p class="muted">none</p>'}
      </section>
      <section>
        <h3>recent access</h3>
        ${(attention.recent_access || []).length ? attention.recent_access.map((note) => noteButton(note, ` / ${note.access_count} hits`)).join("") : '<p class="muted">none</p>'}
      </section>
    `;
    $$("[data-open-note]", output).forEach((button) => {
      button.addEventListener("click", () => window.CartEditor?.loadAndSwitch(button.dataset.openNote));
    });
    $$("[data-delete-broken]", output).forEach((button) => {
      button.addEventListener("click", async () => {
        const wire = JSON.parse(button.dataset.deleteBroken || "{}");
        await api("/api/wire/delete", {
          method: "POST",
          body: JSON.stringify({
            path: wire.path,
            source_note: wire.source,
            target_note: wire.target,
            predicate: wire.predicate,
          }),
        });
        renderHome();
      });
    });
  }

  async function renderQuery(query) {
    const output = $("#query-output");
    if (!output || !query) {
      if (output) output.innerHTML = "";
      return;
    }
    output.innerHTML = '<p class="muted">searching...</p>';
    try {
      const payload = await api(`/api/query?route=1&q=${encodeURIComponent(query)}&budget=1200`);
      const results = payload.results || [];
      output.innerHTML = `
        <h3>search results</h3>
        ${results.length ? results.slice(0, 8).map((item) => `
          <button class="query-result" type="button" data-open-note="${escapeHtml(item.id)}">
            <strong>${escapeHtml(item.label || item.id)}</strong>
            <span class="muted">${escapeHtml(item.shelf || "")}</span>
            <span>${escapeHtml(item.text || "")}</span>
          </button>
        `).join("") : '<p class="muted">no results</p>'}
      `;
      $$("[data-open-note]", output).forEach((button) => {
        button.addEventListener("click", () => window.CartEditor?.loadAndSwitch(button.dataset.openNote));
      });
    } catch (error) {
      output.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
    }
  }

  async function quickAdd(event) {
    if (event.key !== "Enter") return;
    const title = event.target.value.trim();
    if (!title) return;
    event.preventDefault();
    const payload = await api("/api/note/new", {
      method: "POST",
      body: JSON.stringify({ title, type: "note", body: `# ${title}\n\n`, tags: [] }),
    });
    event.target.value = "";
    window.CartEditor?.loadAndSwitch(payload.note.id);
  }

  async function renderGraph() {
    const frame = $("#graph-frame");
    if (frame && !frame.src) frame.src = "/graph";
    await populateTracePredicates();
  }

  async function populateTracePredicates() {
    const select = $("#trace-predicate");
    if (!select || select.dataset.loaded) return;
    const predicates = await api("/api/predicates").catch(() => []);
    select.innerHTML = predicates.map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`).join("");
    select.dataset.loaded = "1";
  }

  async function runTrace() {
    const note = $("#trace-note")?.value.trim();
    const predicate = $("#trace-predicate")?.value || "";
    const depth = $("#trace-depth")?.value || "3";
    const output = $("#trace-output");
    if (!note || !output) return;
    output.innerHTML = '<p class="muted">running trace...</p>';
    try {
      const payload = await api(`/api/trace?note=${encodeURIComponent(note)}&type=${encodeURIComponent(predicate)}&depth=${encodeURIComponent(depth)}`);
      const results = payload.results || [];
      output.innerHTML = results.length ? `
        <div class="trace-chain">
          <button type="button" data-open-note="${escapeHtml(payload.note_id)}">${escapeHtml(payload.note_id)}</button>
          ${results.map((item) => `
            <span>--${escapeHtml(item.predicate || predicate)}--></span>
            <button type="button" data-open-note="${escapeHtml(item.note_id)}">${escapeHtml(item.title || item.note_id)}</button>
          `).join("")}
        </div>
      ` : '<p class="muted">no trace results</p>';
      $$("[data-open-note]", output).forEach((button) => {
        button.addEventListener("click", () => window.CartEditor?.loadAndSwitch(button.dataset.openNote));
      });
    } catch (error) {
      output.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
    }
  }

  function toggleSidebar(forceOpen = null) {
    const opening = forceOpen !== null ? forceOpen : !state.sidebarOpen;
    state.sidebarOpen = opening;
    const sidebar = $("#graph-sidebar");
    const toggle = $("#sidebar-toggle");
    if (sidebar) sidebar.classList.toggle("is-open", state.sidebarOpen);
    if (toggle) toggle.textContent = state.sidebarOpen ? "‹" : "›";
  }

  async function loadSidebarNote(noteId) {
    if (!noteId) return;
    state.sidebarNoteId = noteId;
    toggleSidebar(true);
    const titleEl = $("#sidebar-note-title");
    const metaEl = $("#sidebar-note-meta");
    const contentEl = $("#sidebar-note-content");
    const editBtn = $("#sidebar-open-editor");
    const traceBtn = $("#sidebar-trace-note");
    if (contentEl) contentEl.innerHTML = '<p class="muted">loading...</p>';
    if (editBtn) editBtn.hidden = true;
    if (traceBtn) traceBtn.hidden = true;
    try {
      const payload = await api(`/api/note/${encodeURIComponent(noteId)}`);
      const note = payload.note;
      if (titleEl) titleEl.textContent = note.title || noteId;
      if (metaEl) metaEl.textContent = `${note.type} / ${note.relative_path || note.path}`;
      if (contentEl) contentEl.innerHTML = mdToHtml(payload.body || "");
      if (editBtn) editBtn.hidden = false;
      if (traceBtn) traceBtn.hidden = false;
    } catch (error) {
      if (contentEl) contentEl.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
    }
  }

  function traceFromNote(noteId) {
    if (state.activeTab !== "graph") activateTab("graph");
    toggleSidebar(true);
    const traceSection = $("#sidebar-trace-section");
    if (traceSection) traceSection.open = true;
    const input = $("#trace-note");
    if (input) {
      input.value = noteId || "";
      setTimeout(() => input.focus(), 120);
    }
  }

  function openQuickOpen() {
    let overlay = $("#quick-open");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "quick-open";
      overlay.className = "quick-open-overlay";
      overlay.innerHTML = `
        <div class="quick-open-box">
          <input id="qo-input" type="search" placeholder="open note...">
          <div id="qo-results" class="qo-results"></div>
        </div>
      `;
      document.body.appendChild(overlay);
      overlay.addEventListener("click", (event) => {
        if (event.target === overlay) closeQuickOpen();
      });
    }
    overlay.hidden = false;
    state.quickOpenIndex = 0;
    const input = $("#qo-input");
    input.value = "";
    input.focus();
    input.oninput = debounce(quickOpenSearch, 150);
    input.onkeydown = quickOpenNav;
  }

  function closeQuickOpen() {
    const overlay = $("#quick-open");
    if (overlay) overlay.hidden = true;
  }

  async function quickOpenSearch() {
    const query = $("#qo-input")?.value.trim() || "";
    const results = $("#qo-results");
    if (!results) return;
    if (!query) {
      results.innerHTML = "";
      return;
    }
    const payload = await api(`/api/notes?q=${encodeURIComponent(query)}&limit=12`);
    state.quickOpenIndex = 0;
    results.innerHTML = (payload.notes || []).map((note, index) => `
      <button class="qo-item ${index === 0 ? "is-focused" : ""}" data-note-id="${escapeHtml(note.id)}" type="button">
        <strong>${escapeHtml(note.title)}</strong>
        <span class="muted">${escapeHtml(note.type)} / ${escapeHtml(note.relative_path || "")}</span>
      </button>
    `).join("");
    $$(".qo-item", results).forEach((button) => {
      button.addEventListener("click", () => {
        closeQuickOpen();
        window.CartEditor?.loadAndSwitch(button.dataset.noteId);
      });
    });
  }

  function focusQuickOpenItem(index) {
    const items = $$(".qo-item");
    if (!items.length) return;
    state.quickOpenIndex = Math.max(0, Math.min(index, items.length - 1));
    items.forEach((item, itemIndex) => {
      item.classList.toggle("is-focused", itemIndex === state.quickOpenIndex);
    });
  }

  function quickOpenNav(event) {
    const items = $$(".qo-item");
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusQuickOpenItem(state.quickOpenIndex + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusQuickOpenItem(state.quickOpenIndex - 1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const target = items[state.quickOpenIndex] || items[0];
      if (target) {
        closeQuickOpen();
        window.CartEditor?.loadAndSwitch(target.dataset.noteId);
      }
    } else if (event.key === "Escape") {
      closeQuickOpen();
    }
  }

  const SHORTCUTS = {
    k: { mod: true, desc: "quick-open note", action: openQuickOpen },
    e: { mod: true, desc: "switch to editor", action: () => activateTab("notes") },
    g: { mod: true, shift: true, desc: "switch to graph", action: () => activateTab("graph") },
    w: { mod: true, shift: true, desc: "wire from current note", action: () => window.CartEditor?.wireFromHere() || activateTab("wires") },
    s: { mod: true, desc: "save note", action: () => state.activeTab === "notes" && window.CartEditor?.save() },
  };

  function handleShortcuts(event) {
    const key = event.key.toLowerCase();
    const shortcut = SHORTCUTS[key];
    if (!shortcut) return;
    if (shortcut.mod && !(event.metaKey || event.ctrlKey)) return;
    if (shortcut.shift && !event.shiftKey) return;
    const tag = document.activeElement?.tagName;
    if (!shortcut.mod && ["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
    event.preventDefault();
    shortcut.action();
  }

  function renderShortcutHelp() {
    const list = $("#shortcut-list");
    if (!list) return;
    list.innerHTML = Object.entries(SHORTCUTS).map(([key, shortcut]) => {
      const combo = `${navigator.platform.includes("Mac") ? "Cmd" : "Ctrl"}${shortcut.shift ? "+Shift" : ""}+${key.toUpperCase()}`;
      return `<dt>${escapeHtml(combo)}</dt><dd>${escapeHtml(shortcut.desc)}</dd>`;
    }).join("");
    $("#shortcut-dialog")?.showModal();
  }

  function init() {
    $$(".tab").forEach((button) => {
      button.addEventListener("click", () => activateTab(button.dataset.tab));
    });
    $("[data-refresh='home']")?.addEventListener("click", renderHome);
    $("#quick-add-input")?.addEventListener("keydown", quickAdd);
    $("#theme-toggle")?.addEventListener("click", () => document.body.classList.toggle("dim-mode"));
    $("#shortcut-help")?.addEventListener("click", renderShortcutHelp);
    $("#run-trace")?.addEventListener("click", runTrace);
    $("#sidebar-toggle")?.addEventListener("click", () => toggleSidebar());
    $("#sidebar-open-editor")?.addEventListener("click", () => {
      if (state.sidebarNoteId) window.CartEditor?.loadAndSwitch(state.sidebarNoteId);
    });
    $("#sidebar-trace-note")?.addEventListener("click", () => {
      if (state.sidebarNoteId) traceFromNote(state.sidebarNoteId);
    });
    $$(".sidebar-nav-item").forEach((button) => {
      button.addEventListener("click", () => activateTab(button.dataset.tab));
    });

    $("#global-search")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const query = $("#global-search-input").value.trim();
      if (state.activeTab === "notes" && window.CartEditor) {
        window.CartEditor.search(query);
        return;
      }
      if (state.activeTab !== "home") activateTab("home");
      renderQuery(query);
    });

    window.addEventListener("hashchange", () => {
      if (!state.applyingHash) applyHash();
    });
    window.addEventListener("message", (event) => {
      if (event.data?.type === "cart-node-click" && event.data.noteId) {
        loadSidebarNote(event.data.noteId);
      }
    });
    document.addEventListener("keydown", handleShortcuts);
    applyHash();
  }

  window.Cartographer = {
    $,
    $$,
    api,
    debounce,
    escapeHtml,
    mdToHtml,
    activateTab,
    setHash,
    traceFromNote,
    loadSidebarNote,
    toggleSidebar,
    state,
  };

  document.addEventListener("DOMContentLoaded", init);
})();
