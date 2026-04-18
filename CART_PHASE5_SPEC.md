# cartographer — Phase 5 Spec
# maps · cassette.help · MIT
# generated: 2026-04-17
# status: SCOPED / READY FOR IMPLEMENTATION
# target_agent: Codex / Hermes / Claude Code

---

## Strategic Objective

Phase 5 makes cart feel like a daily driver instead of a promising prototype.

The focus is not new data models. The focus is **speed, clarity, recoverability, and operator trust**:

- the CLI should be easier to discover and faster to use
- shell completion should work out of the box
- the TUI should stop freezing under normal exploration
- navigation should feel structured instead of flat
- the system should surface clear state instead of making the operator guess

This spec is grounded in the current code, not a greenfield fantasy.

---

## Current Friction

### CLI

- Top-level help is sparse and uneven; many commands rely on memory rather than discoverability
- There is no first-class completion flow unless the user already knows Click internals
- Output modes are inconsistent: some commands are operator-friendly, some are tool-friendly, some are neither
- There is no `doctor` or equivalent "what is broken right now?" command

### TUI

- The app does expensive synchronous work on the UI thread
- The graph filter recomputes the entire surface on every keystroke
- Moving selection reparses note files from disk and resolves transclusions immediately
- State strip and task overlay refresh even when the underlying data did not change
- There is no notion of collapsed groups, so the graph pane gets noisy as the atlas grows
- When heavy work is happening, the UI gives almost no feedback and can feel frozen

### Specific hot paths in current code

- `CartTUI.refresh_from_source()` reloads all records and edges, rebuilds graph rows, rerenders note, rerenders state strip, rerenders footer, and rerenders tasks in one synchronous sweep
- `CartTUI.on_input_changed()` calls `refresh_from_source()` on every filter keystroke
- `CartTUI.render_note()` calls `Note.from_file()` and `resolve_transclusions()` on every selection movement
- `CartTUI.render_tasks()` reruns `query_tasks(...)` each refresh
- `CartTUI.render_state_strip()` rereads the latest mapsOS export JSON every refresh
- `CartTUI.action_rebuild()` runs a full refresh on demand with no loading state

The freeze reports are credible. The implementation currently makes them likely on larger atlases.

---

## Workstream 1 — TUI Runtime Stability

**Priority:** P0

### Goal

Keep the UI responsive while data loads or recomputes.

### Spec

- Split TUI state into:
  - atlas index snapshot
  - graph view state
  - note render cache
  - tasks snapshot
  - mapsOS strip snapshot
- Replace all-one-shot `refresh_from_source()` with targeted refresh methods:
  - `refresh_graph_snapshot()`
  - `refresh_note_view(note_id)`
  - `refresh_tasks_snapshot()`
  - `refresh_state_strip()`
- Debounce filter input by ~120–180ms instead of recomputing per keystroke
- Cache `Note.from_file()` results by `(path, mtime)`
- Cache resolved transclusion output by `(note_id, mtime, selected mode)`
- Add a lightweight loading indicator in header or footer during rebuild/render work
- Add exception boundaries so failed note render becomes a recoverable pane error, not a frozen-feeling no-op

### Acceptance

- Selection movement never triggers a full atlas reload
- Typing in `/` filter feels responsive on a few hundred notes
- Rebuilds show visible progress or busy state
- Interrupting the app is no longer the normal way to escape a stall

---

## Workstream 2 — TUI Information Architecture

**Priority:** P0

### Goal

Make the graph pane readable as the atlas scales.

### Spec

- Add collapsible groups for:
  - projects
  - entities
  - learnings
  - sessions
  - other
- Default sessions to collapsed once the user is outside session-oriented work
- Preserve collapse state across refreshes within the running app
- Add a secondary "view mode" concept:
  - `all`
  - `active`
  - `sessions`
  - `tasks`
- Add an explicit selected-row indicator that does not rely only on reverse video
- Add pane subtitles with counts, for example `PROJECTS (18)`

### Acceptance

- Operators can collapse noise instead of scrolling past it
- Large session sets no longer dominate the left pane
- The UI communicates structure even before the user reads the footer

---

## Workstream 3 — TUI Interaction Model

**Priority:** P1

### Goal

Make the app more intuitive without turning it into menu soup.

### Spec

- Keep vim keys, but make the state machine clearer
- Introduce a slim command row or action rail for high-frequency actions:
  - filter
  - new note
  - backlinks
  - tasks
  - mapsOS
  - rebuild
- Add an in-app help overlay with grouped actions instead of footer-only recall
- Add "open related" actions from the note pane:
  - open backlinks
  - jump to linked note
  - jump to source of transclusion
- Make task overlay and filter feel modal and visually distinct

### Acceptance

- A new operator can learn the main loop from the app itself
- Footer hints become reinforcement, not the only documentation

---

## Workstream 4 — CLI Operator UX

**Priority:** P1

### Goal

Make `cart` usable by discovery, not just memory.

### Spec

- Ship shell completion as a first-class command
- Improve help text for top-level groups and commands with concise operator-focused descriptions
- Add `cart doctor`:
  - atlas init status
  - index status
  - qmd status if configured
  - mapsOS export visibility
  - plugin directory presence
  - recent lock or rebuild failures where available
- Add `--json` output to more operator commands over time, starting with:
  - `status`
  - `worklog status`
  - `doctor`
- Add a "common workflows" section to top-level help or README:
  - start session
  - inspect atlas
  - query memory
  - import sessions
  - mapsOS ingest

### Acceptance

- `cart --help` feels useful instead of skeletal
- Completion setup is documented and scriptable
- `cart doctor` answers "why is this weird right now?" in one command

---

## Workstream 5 — Search Surface Upgrade

**Priority:** P1

### Goal

Separate graph filtering from retrieval.

### Spec

- Keep `/` as local graph filter
- Add a dedicated atlas search action in the TUI that can:
  - run built-in search
  - optionally use qmd for semantic search
  - show ranked results separate from graph grouping
- Support opening a search result without forcing the graph pane to act as a search UI
- Preserve the current atlas-scoped qmd rule: never drift into unrelated collections

### Acceptance

- Filtering the current graph and retrieving from the atlas are distinct actions
- TUI search feels like search, not a side effect of the graph view

---

## Workstream 6 — Observability and Tests

**Priority:** P1

### Goal

Catch regressions before users feel them.

### Spec

- Add focused tests for:
  - filter debounce behavior
  - collapse state retention
  - note render cache invalidation on mtime change
  - completion command output
  - `doctor` degraded states
- Add timing instrumentation for heavy TUI operations in debug mode
- Make "frozen" states diagnosable from logs or structured timings

### Acceptance

- The next TUI regression is easier to identify than the current one
- New interaction features come with at least smoke-level test coverage

---

## Recommended Build Order

1. Workstream 1 — TUI runtime stability
2. Workstream 2 — collapsible groups and view modes
3. Workstream 4 — CLI operator UX (`completion`, `doctor`, help text)
4. Workstream 5 — dedicated search surface
5. Workstream 3 — broader interaction polish
6. Workstream 6 — observability hardening as each slice lands

---

## Non-Goals

- No force-directed graph renderer this pass
- No web UI
- No rewrite away from Textual
- No new storage backend
- No command palette unless it clearly beats the slim action rail approach

---

## Handover Notes

- Do not treat "freezes" as a vibes issue. The current code has synchronous hot paths that need structural fixes.
- Do not start by repainting the TUI. Start by reducing work on the UI thread.
- Preserve the existing atlas/mapsOS handoff behavior while refactoring.
