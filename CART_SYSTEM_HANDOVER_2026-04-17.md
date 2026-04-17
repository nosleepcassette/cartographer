# cartographer / atlas System Handover
# maps · cassette.help · MIT
# 2026-04-17
# PRIMARY OWNER: OpenCode
# SECONDARY: Codex (only for narrow follow-up patches)

---

## State After Codex Final Pass

This repo is past init/bootstrap triage.

Shipped in the final Codex pass:

- Phase 3 closed-loop work is implemented
- `cart entities clean-imports` exists and migrated live atlas entity notes away from full imported-session blocks
- `cart ls`, `cart show`, and `cart query` were verified against the live atlas
- atlas-local Obsidian bootstrap is part of `cart init`
- vimwiki setup remains part of `cart init`, with opt-out flags
- learning provenance and confirm/reject workflow are live
- mapsOS export + brief-load bridge is live in `~/dev/mapsOS`
- the `templates/` -> `jinja/` rename fixed the Python 3.14 editable install collision

Operational note:
- running multiple index-refreshing CLI commands against the same atlas in parallel can still hit SQLite locking
- sequential use is fine and is the expected operator path right now

---

## Commands That Matter Right Now

```zsh
cart status
cart session-import claude --latest 1
cart session-import hermes --latest 1
cart bootstrap-populate
cart mapsos ingest-intake --all
cart mapsos ingest-exports --latest
cart mapsos patterns
cart daily-brief --output ~/atlas/daily/brief-$(date +%F).md
cart entities clean-imports
cart ls --type entity --limit 10
cart show master-summary
cart query 'type:master-summary'
```

---

## What OpenCode Should Read First

1. `README.md`
2. `CART_PHASE3_SPEC.md`
3. `runbooks/bootstrap-runbook.md`
4. `runbooks/source-inventory.md`
5. `~/dev/mapsOS/HANDOVER_phase5.md`

Those now reflect the shipped state more accurately than the older init-only notes.

---

## What OpenCode Should Build Next

Priority order:

1. Session import dedup
   - `cart session-import` should skip already-imported sessions by default
   - add `--force` for overwrite behavior

2. External import pipeline
   - `cart import chatgpt <conversations.json>`
   - `cart import claude-web <export.json>`

3. Graph export / visualization
   - minimum viable target is `cart graph --export`

4. External mirror polish
   - better daily-note propagation into external Obsidian / vimwiki surfaces
   - keep atlas as the canonical source of truth

5. mapsOS follow-through
   - richer brief UX inside the TUI
   - deeper atlas task / arc sync beyond the current carry-over hint layer

---

## Smoke-Test Loop

Use this for real-world validation:

1. `cart daily-brief --output ~/atlas/daily/brief-$(date +%F).md`
2. `maps check --load-brief ~/atlas/daily/brief-$(date +%F).md`
3. run the actual session
4. `cart mapsos ingest-exports --latest`
5. `cart mapsos patterns --field state`

If that loop stays smooth, the substrate is doing its job.

---

## Notes For OpenCode

- The live atlas already has a local git init commit.
- Entity notes should stay curated; do not reintroduce full session-content duplication there.
- `cart agent-ingest` still exists for generic plugin-based ingest, but `cart session-import ...` is the intended operator-facing flow for Claude/Hermes session files.
- Treat local session artifacts as first-class inputs when Claude is unavailable.
