# BUILDSHEET: Cart WebUI v3 — Layout Refinement
# maps · cassette.help · MIT
# Target agent: Codex
# Read ALL of cartographer/web/ before touching anything.
# Run `cart serve --force --port 6969` after completion to verify.

---

## Context

The WebUI (`cartographer/web/`) has a 3-pane graph layout:
  [LEFT SIDEBAR] [GRAPH IFRAME] [RIGHT SIDEBAR]

The previous Codex pass (v2) added the left sidebar and resize handles but has
several UX defects visible in the screenshot. This pass fixes them.

Files to edit:
  - `cartographer/web/style.css`     — all visual changes
  - `cartographer/web/app.js`        — all behaviour changes
  - `cartographer/web/index.html`    — minimal: add maximize button only

Do NOT edit graph_serve.py, cli.py, or any Python files.

---

## Bug inventory (what's broken now)

1. **Sidebars don't collapse cleanly.** When closed, the 2rem strip still shows
   partial sidebar body content bleeding through the overflow clip. The toggle
   button sits inside the sidebar so it compresses with it. Result: the closed
   state looks broken, not intentional.

2. **Sidebar toggle affordance is poor.** A lone `›` in a 2rem strip is hard
   to discover and offers no visual cue that it's a full panel hiding behind it.

3. **Graph space is dominated by sidebars.** Both sidebars default to 22rem
   open. On a 1440px screen that's 44rem (704px) leaving ~736px for the graph.
   On a 1280px screen the graph gets only ~576px. Default should be 18rem.

4. **No "maximize graph" shortcut.** There is a full `body.graph-only` mode
   (Codex built it) but no intermediate "collapse both sidebars, keep chrome"
   mode for quick graph focus.

5. **No keyboard shortcut for graph maximize.** `g` should maximize;
   `G` / `Escape` should restore.

6. **Section headers inside sidebars (trace, atlas) lack visual weight.**
   The `<details>` toggles are styled but the clickable area is too slim and
   the indicator is visually weak.

7. **No snap-to-default on resize handles.** Double-click should snap back.

---

## Task 1 — Fix sidebar collapse (CSS)

The core problem: `.sidebar-body` has `min-width: 12rem` which means even
inside a 2rem parent it wants to render wide, causing visible content leak.

### What to change in style.css

**Remove** `min-width: 12rem` from `.sidebar-body`.

**Add** a `.sidebar-tab` concept. The 2rem toggle strip should be a visually
distinct element that protrudes from the edge of the sidebar, not just a
button sitting inside it.

Replace the current `.sidebar-toggle` + `.graph-sidebar` collapse rules with
this model:

```
┌──────────────────┐
│ [TAB] [   BODY  ]│  ← sidebar open (is-open)
└──────────────────┘

[TAB]                  ← sidebar closed (just the 2rem tab)
```

**Specific CSS changes:**

1. `.graph-sidebar` — Remove `overflow: hidden`. Add `overflow: visible`.
   Width: `0` when closed, `var(--sidebar-w, 18rem)` when open.
   IMPORTANT: width 0, not 2rem — the tab protrudes outside the sidebar bounds.

2. `.graph-sidebar.is-open` — `width: var(--sidebar-w, 18rem)`

3. `.sidebar-toggle` (rename in markup to `.sidebar-tab`) —
   Position: `absolute`, so it sits outside the sidebar edge.
   - Right sidebar tab: `left: -2rem; top: 3rem` (protrudes left into graph)
   - Left sidebar tab: `right: -2rem; top: 3rem` (protrudes right into graph)
   Height: `5rem`. Width: `2rem`.
   Background: `var(--panel)`. Border: `1px solid var(--border)`.
   No border on the side that touches the sidebar (seamless join).
   Right sidebar tab: no right border. Left sidebar tab: no left border.
   z-index: `30`.
   Arrow: `‹` / `›` for right sidebar, `›` / `‹` for left sidebar.
   Font-size: `1.1rem`, centered.

4. `.sidebar-body` — When sidebar is closed (`width: 0`), body is `display: none`.
   Use CSS: `.graph-sidebar:not(.is-open) .sidebar-body { display: none; }`
   This is cleaner than overflow clipping.

5. `#graph-frame` — Must not overlap the sidebar tab when sidebars are closed.
   Keep `flex: 1` but set `min-width: 0`. The tabs protrude absolutely so they
   overlap the graph frame slightly — that's intentional and looks good.

6. Default sidebar width: change `--sidebar-w` CSS var default from `22rem`
   to `18rem` in both `.graph-sidebar.is-open` and `.graph-sidebar-left.is-open`.

**Updated transition**: only animate `width` on the sidebar element, not the tab.
Tab position is always stable.

---

## Task 2 — Maximize graph mode (CSS + JS)

Add a body class `body.graph-maximized` that collapses both sidebars while
keeping the top chrome visible. This is distinct from `body.graph-only` which
hides everything.

### CSS additions (style.css)

```css
body.graph-maximized .graph-sidebar,
body.graph-maximized .graph-sidebar-left {
  width: 0 !important;
}
/* Show tabs even in maximized mode so user can re-open */
body.graph-maximized .sidebar-tab {
  display: flex;
}
/* Maximize button — lives in the graph workspace */
.graph-maximize-btn {
  position: absolute;
  top: 0.6rem;
  right: 0.6rem;   /* or left: 0.6rem — place it visually near the graph center */
  z-index: 25;
  min-height: 1.8rem;
  padding: 0.2rem 0.6rem;
  font-size: 0.8rem;
  opacity: 0.5;
  transition: opacity 0.15s;
}
.graph-maximize-btn:hover { opacity: 1; }
```

### HTML addition (index.html)

Inside `.graph-workspace`, add a maximize button. Place it after the `<iframe>`:

```html
<button class="graph-maximize-btn" id="graph-maximize-btn" type="button"
        title="Maximize graph (G)">⛶</button>
```

(⛶ is U+26F6 "square four corners" — feels right. Fall back to `[ ]` if it
doesn't render on target system. Verify in browser.)

### JS additions (app.js)

Add to `state`: `graphMaximized: false`

Add function:
```js
function toggleGraphMaximized(force = null) {
  state.graphMaximized = force !== null ? force : !state.graphMaximized;
  document.body.classList.toggle("graph-maximized", state.graphMaximized);
  const btn = $("#graph-maximize-btn");
  if (btn) btn.title = state.graphMaximized ? "Restore (G)" : "Maximize graph (G)";
  // When restoring, re-open sidebars to their previous state
  if (!state.graphMaximized) {
    if (localStorage.getItem("cart-right-open") === "1") toggleSidebar(true);
    if (localStorage.getItem("cart-left-open") === "1") toggleLeftSidebar(true);
  } else {
    // Close both sidebars without touching localStorage
    const lsb = $("#graph-sidebar-left");
    const rsb = $("#graph-sidebar");
    if (lsb) lsb.classList.remove("is-open");
    if (rsb) rsb.classList.remove("is-open");
    state.sidebarOpen = false;
    state.leftSidebarOpen = false;
  }
  localStorage.setItem("cart-graph-maximized", state.graphMaximized ? "1" : "0");
}
```

Wire up in `init()`:
- `$("#graph-maximize-btn")?.addEventListener("click", () => toggleGraphMaximized())`
- Load persisted state: `if (localStorage.getItem("cart-graph-maximized") === "1") toggleGraphMaximized(true)`

---

## Task 3 — Keyboard shortcuts (app.js)

Extend the existing keydown handler. Find the block that handles keyboard
shortcuts (search for `keydown` in app.js).

Add these cases:

```js
// G = maximize/restore graph (collapse both sidebars, keep chrome)
case "g":
  if (!e.metaKey && !e.ctrlKey && !e.altKey && !isInput) {
    e.preventDefault();
    toggleGraphMaximized();
  }
  break;

// F = fullscreen graph (graph-only mode, existing toggleGraphOnly)
// Already wired? If not, add:
case "f":
  if (e.metaKey && e.shiftKey && !isInput) {
    e.preventDefault();
    toggleGraphOnly();
  }
  break;

// Escape = exit graph-only OR graph-maximized
case "Escape":
  if (state.graphOnly) { toggleGraphOnly(false); e.preventDefault(); }
  else if (state.graphMaximized) { toggleGraphMaximized(false); e.preventDefault(); }
  break;

// [ = toggle left sidebar
case "[":
  if (!isInput) { e.preventDefault(); toggleLeftSidebar(); }
  break;

// ] = toggle right sidebar
case "]":
  if (!isInput) { e.preventDefault(); toggleSidebar(); }
  break;
```

Add these to the shortcut dialog list (find where shortcuts are registered, add
entries):
```
g       maximize graph
G / Esc restore
[       toggle left panel
]       toggle right panel
Cmd+Shift+F  fullscreen graph
```

---

## Task 4 — Resize handle snap-to-default (app.js)

Find the `$$(".resize-handle").forEach(...)` block in app.js (around line 430).

Add a `dblclick` handler on each resize handle:

```js
handle.addEventListener("dblclick", (e) => {
  e.preventDefault();
  const targetId = handle.dataset.target;
  const target = document.getElementById(targetId);
  if (!target) return;
  // Remove custom width — snap to CSS default
  target.style.removeProperty("--sidebar-w");
  localStorage.removeItem(`cart-sidebar-w-${targetId}`);
});
```

This snaps the sidebar to the CSS default (18rem) on double-click.

Also add a "snap zone": if drag ends within `±24px` of the default width
(`18rem = ~288px`), snap to default. Add this inside the `mouseup` handler,
before the `localStorage.setItem` call:

```js
const DEFAULT_W = 288; // 18rem at 16px base
const snapZone = 24;
let finalWidth = parseFloat(target.style.getPropertyValue("--sidebar-w")) || newWidth;
if (Math.abs(finalWidth - DEFAULT_W) <= snapZone) {
  target.style.removeProperty("--sidebar-w");
  localStorage.removeItem(`cart-sidebar-w-${targetId}`);
  return; // don't save custom width
}
```

---

## Task 5 — Section headers inside sidebars (CSS only)

The `<details class="sidebar-section">` elements ("trace", "atlas") need more
visual weight. Do NOT change the HTML structure.

Replace the current `.sidebar-section > summary` rules with:

```css
.sidebar-section > summary {
  color: var(--accent-2);
  cursor: pointer;
  text-transform: uppercase;
  font-size: 0.82rem;
  letter-spacing: 0.1em;
  padding: 0.5rem 0.4rem;
  list-style: none;
  user-select: none;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  /* Subtle hover background */
  border-radius: 2px;
  transition: background 0.1s;
}
.sidebar-section > summary:hover {
  background: rgba(255,176,0,0.07);
}
.sidebar-section > summary::-webkit-details-marker { display: none; }
.sidebar-section > summary::before {
  content: "▸";
  color: var(--accent);
  font-size: 0.75rem;
  flex-shrink: 0;
  width: 0.85rem;
  text-align: center;
}
.sidebar-section[open] > summary::before { content: "▾"; }
```

---

## Task 6 — General polish (CSS)

Small changes that tighten the layout:

1. **Reduce top chrome height.** The topbar has `padding: 1rem 1.2rem` which
   is generous. Change to `padding: 0.6rem 1.2rem`. This gives ~0.8rem back
   to the graph height.

2. **Recalculate graph workspace height.** Change the two instances of
   `calc(100vh - 6.6rem)` in `.graph-workspace` and `.graph-panel.is-active`
   to `calc(100vh - 5.2rem)` to reflect the tighter topbar. Adjust if it
   clips — the goal is no vertical scrollbar in the graph workspace.

3. **`.surface` padding when graph tab is active.** The `.graph-panel.is-active`
   already uses `margin: -1.2rem` to cancel `.surface` padding. Verify this
   still works after topbar height change. If graph bleeds under topbar, add
   `top: 0` to `.graph-panel.is-active`.

4. **Sidebar body padding.** Reduce from `0.9rem` to `0.7rem` to give content
   slightly more room within a narrower default sidebar width.

---

## Task 7 — Port fix

After all changes, verify that `cart serve` defaults to port 6969.

```bash
grep -n "default=6969\|port.*6969" cartographer/cli.py
grep -n "port.*6969\|6969" cartographer/graph_serve.py
```

If either shows 6970 anywhere, change to 6969.

Then kill the current server and restart:
```bash
kill_port 6970 2>/dev/null || true
kill_port 6969 2>/dev/null || true
cart serve --force --port 6969
```

Or using Python:
```bash
python3 -c "
import http.client, socket
for p in [6970, 6969]:
    try:
        s = socket.socket(); s.connect(('localhost', p)); s.close()
        import subprocess, os, signal, time
        r = subprocess.run(['lsof','-ti',f':{p}'], capture_output=True, text=True)
        for pid in r.stdout.split():
            try: os.kill(int(pid), signal.SIGTERM)
            except: pass
        time.sleep(0.5)
    except: pass
"
cart serve --force --port 6969
```

---

## Acceptance criteria

After this build, opening http://localhost:6969/ should show:

1. ✓ Both sidebars collapsed by default (width 0, tabs floating at graph edges)
2. ✓ Clicking a sidebar tab opens it to 18rem cleanly — no partial render glitch
3. ✓ Dragging a resize handle changes width; double-click snaps back to 18rem default
4. ✓ Pressing `g` collapses both sidebars (maximize graph); pressing `g` or `Esc` restores
5. ✓ Pressing `Cmd+Shift+F` activates graph-only fullscreen; `Esc` exits
6. ✓ `[` and `]` toggle left and right sidebar respectively
7. ✓ Section headers in sidebars (trace, atlas) have hover state and clear indicator
8. ✓ Graph iframe fills available space without vertical scroll
9. ✓ No content visible when a sidebar is closed (test by toggling and looking for bleeds)
10. ✓ Server runs on port 6969

---

## Notes for Codex

- The `sidebar-tab` / `sidebar-toggle` rename is optional — you can keep the
  element ID `sidebar-toggle` and `sidebar-left-toggle` for JS compatibility.
  Just change the CSS positioning model.
- Do not break the existing `loadSidebarNote()` flow that opens the right
  sidebar when a graph node is clicked.
- The `body.graph-only` mode must still work after these changes.
- Test with both sidebars open, both closed, and one of each before declaring done.
- localStorage keys: `cart-right-open`, `cart-left-open`, `cart-top-open`,
  `cart-graph-only`, `cart-graph-maximized`, `cart-sidebar-w-graph-sidebar`,
  `cart-sidebar-w-graph-sidebar-left`
