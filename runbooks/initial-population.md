# Atlas Initial Population

Treat `~/atlas` as an existing workspace unless you are explicitly repairing init behavior.

---

## Recommended Flow

```bash
cart status
cart bootstrap-populate
cart mapsos ingest-intake --all
cart entities clean-imports
cart daily-brief --output ~/atlas/daily/brief-$(date +%F).md
```

If you need manual control over sources:

```bash
cart session-import claude ~/.claude/session-data/2026-04-16-maps-session.tmp
cart session-import hermes ~/.hermes/sessions/session_20260416_214759_5b702d.json
```

---

## What This Produces

- agent session notes under `~/atlas/agents/*/sessions/`
- project and entity backlink surfaces
- daily notes updated from imports
- mapsOS snapshots, state log, and learning notes
- a session-start brief for the next agent or mapsOS run

---

## Preferred Commands

Use these instead of older ad hoc flows:

- `cart session-import ...`
- `cart bootstrap-populate`
- `cart mapsos ingest-intake`
- `cart mapsos ingest-exports`
- `cart daily-brief`

Avoid relying on `cart agent-ingest` or `hermes-start.zsh` for the main population path unless you are deliberately working on legacy plumbing.

---

## Quick Validation

```bash
cart ls --type project --limit 10
cart show master-summary
cart query 'type:master-summary'
cart mapsos patterns
```
