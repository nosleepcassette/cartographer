# Codex Initial Population Prompt

Claude is unavailable on timeout. Do not wait for Claude. Use Claude's latest session files on disk as read-only source material and proceed.

Your job: make cartographer fully operational in code and begin automated initial population.

Read these sources first:
- `~/.claude/session-data/2026-04-16-maps-session.tmp`
- `~/.claude/session-data/2026-04-15-maps-session.tmp`
- `~/.hermes/sessions/session_20260416_200632_9f9122.json`
- `~/.hermes/sessions/session_20260416_202623_036914.json`
- `~/.hermes/sessions/session_20260416_210938_ff9e72.json`
- `~/.hermes/sessions/session_20260416_214759_5b702d.json`
- `~/dev/cartographer/HERMES_BOOTSTRAP.md`
- `~/dev/cartographer/AGENT_CONTRIBUTE.md`
- `~/dev/cartographer/SPEC.md`
- `~/dev/cartographer/HANDOVER.md`
- `~/atlas/agents/MASTER_SUMMARY.md`
- `~/atlas/agents/MAPSOS_LEARNING_SUMMARY_2026-04-16.md`

Then inspect the current cartographer codebase and implement the missing operational pieces.

Ownership:
- You own code, tests, CLI, init behavior, parsers/importers, and automation helpers.
- Do not wait for Claude.
- Do not overwrite existing atlas content casually.
- Preserve existing `MASTER_SUMMARY` content while fixing parsing/indexing/integration.
- Follow `AGENT_CONTRIBUTE.md` if you write atlas content as part of the implementation.

Non-negotiable product requirements:
1. `cart init` must auto-setup vimwiki as a first-class part of init, with opt-out rather than hidden manual followup
2. `cart init` must auto-setup Obsidian as a first-class part of init, not just detect a vault
3. recent Claude and Hermes session files on disk must be ingestible as actual sources for atlas population
4. `MASTER_SUMMARY` and per-agent summaries must parse/index cleanly
5. initial population must be able to start from recent session artifacts, not just hand-authored notes

Implementation targets:
- add or finish Obsidian init/bootstrap under atlas
- make vimwiki + obsidian both explicit in init result/output
- add session import/ingest commands or helpers for:
  - latest Claude maps sessions from `~/.claude/session-data/`
  - Hermes sessions from `~/.hermes/sessions/`
- ensure imported sessions can feed:
  - daily note updates
  - project/entity/task surfaces
  - `MASTER_SUMMARY` refresh inputs
- preserve the existing canonical summary indexing work
- add tests for the new import/setup behavior
- smoke test the real commands

Suggested scope if needed:
- `cart init` flags: `--no-vimwiki`, `--no-obsidian`
- `cart session-import claude ...`
- `cart session-import hermes ...`
- `cart bootstrap-populate` or equivalent helper for first-pass population
- Obsidian workspace/settings bootstrap in atlas-local `.obsidian/`

The sessions collectively imply these next steps:
- atlas is the substrate
- mapsOS needs closed-loop synthesis and bridge surfaces
- no fabrication in intake/session summaries
- initial population should come from actual recent sessions
- operational setup should not rely on Claude being live

Output requirements:
- implement the changes
- run tests
- run smoke tests
- tell me exactly what commands now exist
- tell me what cassette and wizard still need to do after your patch
