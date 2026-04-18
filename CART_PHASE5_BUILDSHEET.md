# BUILDSHEET — cartographer phase 5
# maps · cassette.help · MIT
# session: 2026-04-17
# owner: codex

---

## goal

Ship a significantly better cart operator experience:

- shell completion and more discoverable CLI workflows
- a TUI that feels responsive on a real atlas
- collapsible structure in the graph pane
- clearer navigation and state

This is an execution sheet, not the product rationale. Read `CART_PHASE5_SPEC.md` first.

---

## workstreams

| # | workstream | status | output |
|---|---|---|---|
| 1 | CLI completion + help pass | scoped | `cart completion`, clearer help text |
| 2 | `cart doctor` | scoped | health/status command with actionable checks |
| 3 | TUI performance refactor | scoped | cached note render, debounced filter, targeted refresh |
| 4 | TUI structure | scoped | collapsible groups, view modes, counts |
| 5 | TUI search surface | scoped | dedicated atlas search mode |
| 6 | tests + instrumentation | scoped | coverage for completion, doctor, TUI caches |

---

## immediate implementation order

### pass 1

- land CLI completion
- add tests for completion output
- improve README completion docs

### pass 2

- implement `cart doctor`
- add `--json` for `status`, `worklog status`, and `doctor`
- improve top-level command help copy

### pass 3

- split `refresh_from_source()` into targeted refresh methods
- add note cache keyed by path + mtime
- debounce filter input
- stop rereading mapsOS and tasks on every graph movement

### pass 4

- collapsible graph groups
- persisted in-memory collapse state
- pane subtitles with counts

### pass 5

- dedicated TUI search mode
- qmd-backed search only when atlas-scoped collection exists
- result list separated from graph filter

### pass 6

- timing instrumentation
- regression tests
- polish and docs

---

## success criteria

- `cart completion zsh` is usable without reading Click docs
- `cart doctor` answers the obvious local-health questions
- TUI filter no longer feels blocked per keystroke
- moving between notes does not reread the whole world
- operators can collapse sessions and other noisy groups
- the app stops feeling like it needs manual interruption under routine usage
