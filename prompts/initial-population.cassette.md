# Cassette Initial Population Prompt

Claude is unavailable on timeout. Do not wait for Claude. Use Claude's latest session files on disk as read-only source material and proceed.

Your job: begin initial atlas population as the human-context and synthesis owner.

Read these actual session artifacts first, in full enough to extract signal:
- `~/.claude/session-data/2026-04-16-maps-session.tmp`
- `~/.claude/session-data/2026-04-15-maps-session.tmp`
- `~/.hermes/sessions/session_20260416_200632_9f9122.json`
- `~/.hermes/sessions/session_20260416_202623_036914.json`
- `~/.hermes/sessions/session_20260416_210938_ff9e72.json`
- `~/.hermes/sessions/session_20260416_214759_5b702d.json`
- `~/.hermes/handover-2026-04-15-late.md`
- `~/.hermes/handover_2026-04-13.md`
- `~/atlas/agents/MASTER_SUMMARY.md`
- `~/atlas/agents/MAPSOS_LEARNING_SUMMARY_2026-04-16.md`
- `~/dev/cartographer/HERMES_BOOTSTRAP.md`
- `~/dev/cartographer/AGENT_CONTRIBUTE.md`

Then do the work.

Operational note:
- Cassette has already attempted `cart init` once on 2026-04-16.
- Wizard has already attempted `cart init` once on 2026-04-16.
- Treat `~/atlas/` as an existing workspace, not a fresh bootstrap.
- Do not rerun `cart init` unless you are explicitly repairing init behavior. Inspect what already exists, update in place, and avoid duplicating scaffold notes.

Ownership:
- You own context synthesis, human continuity, and first-pass population.
- Do not wait for wizard or codex.
- Do not fabricate. Quote hygiene and source attribution matter.
- If a note already exists, update it instead of duplicating it.

Goals:
1. Make the atlas immediately useful as a living exocortex, not an empty scaffold.
2. Populate the highest-signal notes from the actual Claude/Hermes session overlap.
3. Improve `MASTER_SUMMARY.md` from the sessions, not from generic biography.
4. Seed the first project/entity/daily notes needed for real use.

Deliverables:
- Update `~/atlas/agents/MASTER_SUMMARY.md`
- Create or update `~/atlas/daily/2026-04-16.md` with current-session context
- Create or update project notes for at least:
  - `cartographer`
  - `mapsOS`
  - `HopeAgent`
  - `voicetape`
- Create or update entity notes for the highest-signal recurring people only if the sessions actually support them
- Create or update a concise "recent decisions" / "open questions" layer inside atlas notes, not just in the master summary
- Write your own contribution note per `AGENT_CONTRIBUTE.md`
- If you discover prompt/bootstrap weaknesses, append concrete notes to `HERMES_BOOTSTRAP.md`

Priorities from the sessions:
- atlas/cartographer is becoming the knowledge substrate
- mapsOS needs closed-loop synthesis, not just tracking
- no fabricated intake language, ever
- survival/income/housing context must remain legible
- session-derived decisions and blockers matter more than polished prose

Output requirements:
- Tell me exactly which atlas files you wrote or updated
- Tell me the 5 highest-signal facts you added
- Tell me what still needs codex and what still needs wizard
