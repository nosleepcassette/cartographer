# cartographer — Phase 4 Spec
# maps · cassette.help · MIT
# generated: 2026-04-17
# status: DRAFT / SPEC ONLY — DO NOT IMPLEMENT WITHOUT EXPLICIT DIRECTIVE
# target_agent: Codex / OpenCode / Advanced Coding Agent

---

## Strategic Objective

Phase 3 successfully shipped the core closed loop (mapsOS -> atlas -> daily brief). 
Phase 4 focuses on **Ecosystem Robustness, Deep Sync, and Extensibility**. 

This spec defines the architectural boundaries for the next coding agent. The implementation requires deep thinking about state management, concurrency, and parsing logic.

## 1. Concurrent Write Protection (SQLite & Filesystem)

**The Problem:** Running multiple index-refreshing CLI commands (`cart session-import`, `cart mapsos ingest`, etc.) in parallel causes SQLite database locking errors on `index.db` and `worklog.db`.

**The Spec:**
- Enable Write-Ahead Logging (WAL) mode for all SQLite connections in `cartographer/index.py` and `cartographer/worklog.py` (`PRAGMA journal_mode=WAL;`).
- Implement a bounded retry loop (e.g., exponential backoff up to 5 seconds) for `sqlite3.OperationalError: database is locked`.
- For raw markdown file writes (`Note.write()`), implement a cross-platform file locking mechanism (or simple `.lock` file protocol in the `.cartographer/` directory) to prevent parallel plugin or ingest runs from clobbering identical files (like `MASTER_SUMMARY.md` or `active.md`).

## 2. Deep mapsOS Arc & Task Bidirectional Sync

**The Problem:** The current mapsOS bridge relies on a "carry-over hint layer" for tasks. It is not fully bidirectional.

**The Spec:**
- **Atlas -> mapsOS:** Create a hook or plugin (`mapsos-sync`) that listens to `cart todo done <id>`. If the task has a `project` matching a mapsOS `arc`, it queues a state-update event for mapsOS's next initialization.
- **mapsOS -> Atlas:** When mapsOS exports an arc update (e.g., momentum shift, new arc intent), map it directly into `tasks/active.md` as structured blocks, rather than just appending text to the daily note. 
- **Taskwarrior Export:** Build the `cart export-tasks --format=taskwarrior` command to push `type:task` blocks to the local taskwarrior DB.

## 3. Transclusion Rendering Engine

**The Problem:** The spec defines `![[note-id#block-id]]` for block-level transclusion, but there is no mechanism to render this flat for sharing, publishing, or external reading.

**The Spec:**
- Implement `cart export <note-id> --resolve-transclusions`.
- The parser must recursively resolve `![[note-id#block-id]]` tags up to a max depth (e.g., 3) to prevent infinite loops.
- Replaces the transclusion tag with the literal `content` of the referenced block from the SQLite index.
- Output formats: `markdown` (default), `html`.

## 4. Lua Plugin Support (`lupa`)

**The Problem:** Python plugins have a startup latency overhead. The spec demands Lua support for lightweight, near-instant hooks and plugins.

**The Spec:**
- Integrate `lupa` (Python-Lua bridge) as an optional dependency (`[project.optional-dependencies] lua = ["lupa"]`).
- Modify `cartographer/plugins.py`:
  - If a plugin file ends in `.lua`, spin up a Lua runtime.
  - Inject a `cartographer` global table into the Lua environment exposing methods: `cartographer.query()`, `cartographer.read_note()`, `cartographer.write_note()`.
  - Pass the standard JSON payload as a Lua table to the script's `main()` function.
  - Expect a standard Lua table return (matching the JSON output schema) and translate back to Python dicts.

## 5. External Mirror Polish (Obsidian Dataview Integration)

**The Problem:** `cart obsidian-sync` writes a static `_cartographer_index.md`. It does not fully leverage Obsidian's power.

**The Spec:**
- Upgrade `obsidian.py` to optionally generate Dataview-compatible metadata. 
- Ensure all cartographer-generated frontmatter (especially `tags` and `links`) is strictly formatted so Obsidian's Dataview plugin can query tasks (`- [ ]`) and project status directly from the raw markdown without needing cartographer's SQLite index.

---

## Handover Notes for Coding Agent

- **Do not build this spec unilaterally.** Wait for the user to specify which numbered item to execute.
- Read `cartographer/index.py` before touching concurrency.
- Read `cartographer/plugins.py` before mocking the Lua implementation.
- You are writing production CLI code. Fail gracefully. Print actionable `click.ClickException` errors. Keep it fast.