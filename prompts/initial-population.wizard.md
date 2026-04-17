# Wizard Initial Population Prompt

Claude is unavailable on timeout. Do not wait for Claude. Use Claude's latest session files on disk as read-only source material and proceed.

Your job: make atlas operational as a system, not just a pile of notes.

Read these actual session artifacts first:
- `~/.claude/session-data/2026-04-16-maps-session.tmp`
- `~/.claude/session-data/2026-04-15-maps-session.tmp`
- `~/.hermes/sessions/session_20260416_200632_9f9122.json`
- `~/.hermes/sessions/session_20260416_202623_036914.json`
- `~/.hermes/sessions/session_20260416_210938_ff9e72.json`
- `~/.hermes/sessions/session_20260416_214759_5b702d.json`
- `~/.hermes/WIZARD_SESSION_NOTES.md`
- `~/.hermes/handover-wizard-2026-04-15.md`
- `~/.hermes/handover-2026-04-15-late.md`
- `~/dev/cartographer/HERMES_BOOTSTRAP.md`
- `~/dev/cartographer/HANDOVER.md`
- `~/dev/cartographer/AGENT_CONTRIBUTE.md`
- `~/atlas/agents/MASTER_SUMMARY.md`
- `~/atlas/agents/MAPSOS_LEARNING_SUMMARY_2026-04-16.md`

Then do the work.

Operational note:
- Wizard has already attempted `cart init` once on 2026-04-16.
- Cassette has already attempted `cart init` once on 2026-04-16.
- Treat `~/atlas/` as an existing initialized workspace with partial population already on disk.
- Do not treat this as a first-run bootstrap. Audit and repair what init produced, then continue population/update work in place.

Ownership:
- You own orchestration, runbooks, workflow hardening, bootstrap quality, and source-of-truth rules.
- Do not spend time writing project content notes that cassette should own.
- Do not spend time implementing repo code that codex should own unless absolutely necessary.
- Convert ambiguity into concrete operational rules.

Primary goal:
Make atlas initial population and recurring refresh operational with explicit ownership, source paths, and execution order.

Required outputs:
1. A concrete runbook for initial population and recurring refresh
2. A source inventory for actual session inputs, including exact file paths and precedence
3. Explicit ownership boundaries:
   - cassette
   - wizard
   - codex
4. A bootstrap/update loop for:
   - Claude session ingestion from on-disk session files
   - Hermes session ingestion from `~/.hermes/sessions/`
   - `MASTER_SUMMARY` refresh
   - contribution-note flow
5. Prompt/bootstrap improvements appended into `HERMES_BOOTSTRAP.md`
6. If needed, patch or create Hermes skills so this workflow is reusable next run

You must directly address these user requirements:
- vimwiki should be auto-setup as part of init
- obsidian should be auto-setup as part of init
- atlas should be operational immediately after init, not after manual cleanup
- Claude may be unavailable; local session files are still first-class sources
- initial population should begin from actual recent sessions, not aspirational docs

Deliverables should include at least:
- one durable runbook file
- one source/prioritization file or section
- one explicit execution sequence with commands or exact agent prompts
- bootstrap notes that reduce future ambiguity

Output requirements:
- list every file you wrote or updated
- give me the exact execution order you recommend for cassette, wizard, codex
- identify the top 3 remaining code changes codex must make
