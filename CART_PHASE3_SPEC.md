# cartographer — Phase 3 Spec / Implementation Record
# maps · cassette.help · MIT
# authored: 2026-04-17
# status: IMPLEMENTED
# owner: Codex

---

## Summary

Phase 3 is no longer a proposed build. The core closed loop is implemented across `cartographer` and `mapsOS`.

The loop now looks like this:

```text
mapsOS session -> structured export -> cart ingest -> atlas update -> daily brief -> next session start
```

---

## Shipped Features

1. `cart mapsos ingest-intake`
   - Parses narrative markdown intakes from `~/dev/mapsOS/intakes/*.md`
   - Writes daily note updates, mapsOS snapshots, intake index entries, state-log entries, and learning notes

2. `cart mapsos patterns`
   - Reads the mapsOS state log and summarizes frequency / trend data
   - Supports filters like `--since` and `--field state|sleep|energy|pain|arcs`

3. `cart daily-brief`
   - Builds an atlas-derived briefing doc for session start
   - Supports `--format markdown|plain` and `--output`

4. Learning provenance
   - Learning blocks now carry `source_session` and `source_agent`
   - mapsOS-derived learnings write auditable provenance

5. `cart learn confirm|reject|pending`
   - Pending review surface for unverified observations
   - Confirm / reject rewrites learning block attrs in place

6. mapsOS structured export loop
   - `maps export` writes `~/.mapsOS/exports/session_YYYYMMDD_HHMMSS.json`
   - TUI exit also writes a structured export
   - `cart mapsos ingest-exports [--latest]` ingests those files

---

## Current Commands

```zsh
cart mapsos ingest export.json
cart mapsos ingest-intake ~/dev/mapsOS/intakes/2026-04-13_full_intake.md
cart mapsos ingest-intake --all
cart mapsos ingest-exports --latest
cart mapsos patterns
cart mapsos patterns --field state
cart daily-brief --output ~/atlas/daily/brief-$(date +%F).md
cart learn pending
cart learn confirm <topic>
cart learn reject --block <block-id>
```

---

## Files Added Or Extended

- `cartographer/intake_parser.py`
- `cartographer/patterns.py`
- `cartographer/daily_brief.py`
- `cartographer/mapsos.py`
- `cartographer/agent_memory.py`
- `cartographer/cli.py`
- `plugins/daily-brief.py`
- `~/dev/mapsOS/environments/export.py`
- `~/dev/mapsOS/bin/maps`

---

## Recommended Smoke Test

Use the next real mapsOS session as the loop test:

1. Generate a brief:

```zsh
cart daily-brief --output ~/atlas/daily/brief-$(date +%F).md
```

2. Start mapsOS with the brief loaded:

```zsh
maps check --load-brief ~/atlas/daily/brief-$(date +%F).md
```

3. Run the session normally.
   - `maps export` is available explicitly
   - TUI exit also writes the structured export automatically

4. Pull the newest export back into atlas:

```zsh
cart mapsos ingest-exports --latest
```

5. Inspect the updated state / trends:

```zsh
cart mapsos patterns --field state
cart show mapsos-$(date +%F)
```

---

## What Remains After Phase 3

These are Phase 4+ or OpenCode follow-ups, not missing Phase 3 work:

- session-import dedup / `--force`
- external imports for ChatGPT and Claude web exports
- graph export / visualization
- richer external-vault / vimwiki daily mirroring
- mapsOS knowledge-map screen and deeper bidirectional arc sync
