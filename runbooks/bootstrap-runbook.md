# Atlas Bootstrap Runbook

This is the current operational runbook, not the historical init transcript.

---

## One-Time Setup

Use `cart init` only when creating or repairing an atlas:

```bash
cart init
```

What it does now:

- creates the atlas directory structure
- writes `.cartographer/config.toml`
- bootstraps atlas-local `.obsidian/`
- patches vimwiki unless explicitly opted out
- creates index/worklog databases
- writes section index notes and `MASTER_SUMMARY.md`

Opt-out flags:

```bash
cart init --no-vimwiki
cart init --no-obsidian
```

---

## Initial Population

Recommended order:

```bash
cart bootstrap-populate
cart mapsos ingest-intake --all
cart entities clean-imports
cart daily-brief --output ~/atlas/daily/brief-$(date +%F).md
```

If you need explicit imports instead of the bootstrap helper:

```bash
cart session-import claude --latest 2
cart session-import hermes --latest 4
```

---

## Verification

```bash
cart status
cart ls --type entity --limit 10
cart show master-summary
cart query 'type:master-summary'
```

mapsOS bridge verification:

```bash
cart mapsos patterns --field state
```

---

## Recurring Refresh

After new Claude/Hermes activity:

```bash
cart session-import claude --latest 1
cart session-import hermes --latest 1
```

After a mapsOS session:

```bash
cart mapsos ingest-exports --latest
cart daily-brief --output ~/atlas/daily/brief-$(date +%F).md
```

Periodic maintenance:

```bash
cart index rebuild
cart learn pending
```

---

## Ownership

- Cassette: summaries, entities, context synthesis
- Wizard: runbooks, orchestration, source-of-truth rules
- Codex: code, tests, CLI behavior, importers, bridge logic
- OpenCode: next build sprint after the shipped Phase 3 baseline
