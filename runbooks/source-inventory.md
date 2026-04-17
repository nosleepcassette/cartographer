# Atlas Source Inventory

Exact file paths and precedence for current atlas population.

---

## Primary Session Sources

Claude session files:

- `~/.claude/session-data/*.tmp`
- operator command: `cart session-import claude --latest N`

Hermes session files:

- `~/.hermes/sessions/*.json`
- operator command: `cart session-import hermes --latest N`

mapsOS intake markdown:

- `~/dev/mapsOS/intakes/*.md`
- operator command: `cart mapsos ingest-intake --all`

mapsOS structured exports:

- `~/.mapsOS/exports/*.json`
- operator command: `cart mapsos ingest-exports --latest`

---

## Atlas / Repo Context Sources

- `~/atlas/agents/MASTER_SUMMARY.md`
- `~/atlas/agents/MAPSOS_LEARNING_SUMMARY_2026-04-16.md`
- `~/dev/cartographer/README.md`
- `~/dev/cartographer/HERMES_BOOTSTRAP.md`
- `~/dev/cartographer/AGENT_CONTRIBUTE.md`
- `~/dev/cartographer/CART_PHASE3_SPEC.md`
- `~/dev/mapsOS/HANDOVER_phase5.md`

---

## Source Precedence

When sources disagree, prefer:

1. newest raw session artifact
2. curated atlas synthesis (`MASTER_SUMMARY.md`, project notes, entity notes)
3. runbooks / handovers / bootstrap prompts

Important:
- local session files remain first-class sources even if Claude is unavailable
- atlas is the canonical write target; vimwiki and Obsidian are mirrors / companions, not the source of truth

---

## Verification Commands

```bash
cart status
cart show master-summary
cart query 'type:master-summary'
cart mapsos patterns --field state
```
