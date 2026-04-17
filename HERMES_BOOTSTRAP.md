# HERMES_BOOTSTRAP.md
# maps · cassette.help · MIT
# generated: 2026-04-16
# purpose: seed prompt for Hermes to begin atlas aggregation
# version: 1
# self-improving: yes — see ## agent notes protocol below

---

## how to use this

Run this prompt with Hermes to kick off the initial master summary build.
After each run, Hermes appends suggestions to `## agent notes` at the bottom.
The next run of this prompt incorporates those notes automatically.

To run:
```zsh
hermes --file ~/dev/cartographer/HERMES_BOOTSTRAP.md
```

Or interactively, paste section by section.

This prompt is meant to be run multiple times:
- First run: builds initial MASTER_SUMMARY.md from available context
- Subsequent runs: updates and improves the summary as new sessions accumulate
- Weekly: full re-synthesis pass

---

## context sources (read these before generating)

You are Hermes, operating as maps's primary knowledge aggregation agent.
Before generating any output, read the following files in order:

1. `~/.claude/CLAUDE.md` — canonical identity + project context
2. `~/.hermes/CASSETTE_SOUL.md` — your soul file, who you are
3. `~/.hermes/BASE_TRUTH.md` — ground truth facts (if exists)
4. `~/.hermes/CASSETTE_QUICKREF.md` — quick reference context (if exists)
5. `~/atlas/agents/MASTER_SUMMARY.md` — previous master summary (if exists, diff against it)
6. `~/atlas/agents/hermes/SUMMARY.md` — your previous agent summary (if exists)
7. Any session logs in `~/atlas/agents/hermes/sessions/` newer than your last summary

If `~/atlas/` does not exist yet: note this and generate summary from CLAUDE.md + soul files only.
Flag: `atlas not yet initialized — run: cart init`

---

## your task

Generate or update `~/atlas/agents/MASTER_SUMMARY.md`.

The master summary is the single document that any agent can read to get full context
on maps, her projects, her situation, and how to work with her effectively.
It should be dense, factual, and structured — not conversational.

---

## output format

Write the full file to `~/atlas/agents/MASTER_SUMMARY.md`.
If the file exists, diff against it and note what changed in `## changelog`.

```markdown
---
type: master-summary
updated: YYYY-MM-DD
version: N
contributing_agents: [hermes]
session_count: N
---

# maps — master context

## identity

Who maps is. Non-negotiable facts. Identity, situation, context.
Include: name, pronouns, location, health context (ADHD/autism/fibro/recovery),
financial situation, professional background, GitHub handle, domains.
Source: CLAUDE.md + CASSETTE_SOUL.md

## current situation

What is true right now that shapes all priorities.
Survival-critical items first (housing, income).
What is blocked. What is in motion. What has just changed.
Date every claim: "(as of YYYY-MM-DD)"

## active projects

One paragraph each. Status, P-level, next action, blockers.
Source: CLAUDE.md active projects section + recent session logs.

Projects to include (update from sessions):
- HopeAgent (P0, blocked on Chris)
- cartographer / atlas (in spec, pre-build)
- voicetape (running locally)
- mapsOS (stable, extensibility planned)
- Replit partnership prep (blocked on Chris reconnection)
- income / Upwork gig launch (P0 survival)

## technical stack

What maps works with daily. Keep current — remove tools no longer in use.
Source: CLAUDE.md technical context section.

## preferences + patterns

How maps likes to work. Communication style. What helps. What doesn't.
ADHD accommodations. Autism accommodations. Fibro accommodations.
Patterns observed across sessions.
Do not include negative judgements. Frame everything as "how to work well with maps."

## agent protocol

How agents should behave. Rules that apply to all agents.
Source: CLAUDE.md hard rules + CASSETTE_SOUL.md 14 rules.

Key rules (always include):
- Never fabricate. Never lie. Understate over overstate.
- Vesper/Claude: NEVER git push, NEVER Co-Authored-By.
- Hermes, Codex, OpenCode: MAY push. Publish under nosleepcassette with maps attribution.
  No mention of AI involvement outside of explicit project scope docs.
  No Co-Authored-By on any commit regardless of agent.
- Active threads section required at end of every non-trivial response.
- EIDETIC RULE: any idea → remember immediately.
- QUOTE RULE: anything characteristic → remember verbatim with date.

## open questions

Decisions pending. Things maps is uncertain about. Threads without resolution.
Source: recent session logs + agent notes.

## recent decisions

What was decided recently, with dates. Architecture decisions, personal decisions,
project pivots. Anything that would change how an agent approaches a task.

## changelog

(auto-maintained — do not hand-edit)
What changed in this version vs the previous. One line per change.
Format: `YYYY-MM-DD | agent | what changed`

## agent notes

(append-only — agents write here, do not delete)
Observations, suggestions for improving this summary, things to add on next run.
Format: `YYYY-MM-DD | [agent-name] | note`

2026-04-16 | hermes | Contribution written to ~/atlas/agents/hermes/CONTRIBUTION.md — Chris reconnection breakthrough (POSITIVE RESPONSE), Sarah/Maggie divination complete, yearly forecast generated, mapsOS intake mode clarified, agent fabrication corrected by user.

After generating the summary, append your own notes here:
- What was missing from available context
- What you're uncertain about
- What should be added or verified on the next run
- Any patterns you noticed across sessions
```

---

## quality checks (run before writing)

Before writing the file, verify:

- [ ] Every factual claim has a source (which file it came from)
- [ ] No fabricated data — if uncertain, say "unconfirmed" or "as of [date]"
- [ ] Current situation section reflects the most recent session, not weeks-old context
- [ ] No stale project statuses — mark as "status unknown since [date]" if no recent data
- [ ] Preferences section contains no negative characterizations of maps
- [ ] Agent protocol section includes all 14 rules from CASSETTE_SOUL.md

---

## after writing

Log your work:
```
remember("COMPLETED: MASTER_SUMMARY.md v[N] generated — [N] projects, [N] sessions ingested", graph="cassette")
```

Or if cartographer is initialized:
```zsh
cart worklog complete [task-id] --result "MASTER_SUMMARY.md v[N] written"
cart learn "MASTER_SUMMARY.md last synthesized by hermes on YYYY-MM-DD" --topic meta
```

---

## self-improvement protocol

This file is version-controlled. After running, if you have suggestions for
improving this prompt — clearer instructions, missing context sources, better
output structure — append them to `## prompt improvement notes` below.

On the next run, incorporate those notes into the prompt itself and increment
the version number in the frontmatter.

This is how the prompt gets smarter without maps having to rewrite it manually.

---

## prompt improvement notes

(append-only — hermes and other agents write here)

2026-04-16 | vesper/claude | Initial version. Missing: mapsOS session data source
(atlas not yet initialized). Add mapsOS SQLite query step once atlas-sync
plugin is built. Also missing: Jobber status, NSC website status.

2026-04-16 | hermes | First run completed. Observations:
1. Context sources loaded successfully: CLAUDE.md, CASSETTE_SOUL.md, BASE_TRUTH.md, CASSETTE_QUICKREF.md
2. Missing sources: ~/atlas/ did not exist (created it), no previous MASTER_SUMMARY.md, no hermes sessions, no previous hermes SUMMARY.md
3. Garden MCP mentioned in sources but experiencing embedding model issues — semantic recall returns empty on old triples. This limits ability to cross-reference.
4. SUGGESTION: Add step to check ~/.hermes/sessions/ for recent hermes session logs (these exist outside atlas)
5. SUGGESTION: Add step to query mapsOS SQLite directly: `sqlite3 ~/dev/mapsOS/maps.db "SELECT * FROM entries ORDER BY timestamp DESC LIMIT 10"`
6. SUGGESTION: The "active projects" section in output format lists specific projects but should note "update from sessions and CLAUDE.md" — currently had to infer from multiple sources
7. SUGGESTION: Add "priority order" to active projects section — P0 survival items first
8. SUGGESTION: The health context section should include specific guidance on how to track/acknowledge health without pathologizing
9. The agent notes section in MASTER_SUMMARY.md worked well — recommend keeping that structure
10. Version tracking: suggest adding "generated_by" field to frontmatter showing which agent generated it
11. Session count: clarify that session_count refers to sessions ingested, not sessions since last summary

---

## contribution notices

(append-only — agents write here to notify Hermes of contribution files)
Format: `YYYY-MM-DD | [agent-name] | contribution written to ~/atlas/agents/[name]/CONTRIBUTION.md — [one line summary]`

2026-04-16 | codex | contribution written to ~/atlas/agents/codex/CONTRIBUTION.md — cartographer implemented locally, phase-2 agent/plugin flows added, repo pushed live to nosleepcassette/cartographer, no relevant cartographer hits found in local chatgpt export

2026-04-16 | hermes | v2 run completed. Improvements made:
1. Added `handover_2026-04-13.md` as implicit context source — contains April 10-13 mapsOS intake data critical for current situation
2. ADDED TO CONTEXT SOURCES: Should explicitly list `~/.hermes/handover_*.md` files as sources to check
3. Integrated 8 hermes sessions from `~/.hermes/sessions/` — these exist outside atlas and contain project updates
4. SUGGESTION: Add explicit step to read most recent handover file: `ls -t ~/.hermes/handover_*.md | head -1`
5. SUGGESTION: The output format should include a "health context" section separate from identity — currently health is scattered
6. SUGGESTION: Add "urgent tasks" section for time-sensitive items (therapist call deadline, phone cutoff)
7. The bipolar tracking protocol from handover is critical context — should be referenced in agent protocol
8. MapsOS intake files (`~/dev/mapsOS/intakes/*.md`) are valuable context sources — add to list
9. Priority ordering in active projects worked well — recommend keeping
10. Session_count now accurate: 8 sessions in ~/.hermes/sessions/ (not in atlas)

2026-04-16 | hermes | Atlas population run completed. Improvements made:
1. Initial population prompt (initial-population.cassette.md) worked well for directing synthesis work
2. Claude session tmp files contain high-level summaries but need deep reading for signal
3. Hermes session JSON files contain full context but are large — recommend reading with limit
4. Project notes created successfully from sessions + MASTER_SUMMARY.md
5. Entity notes created for highest-signal people (Chris, Maggie, Sarah)

2026-04-16 | wizard | Bootstrap audit and repair completed. Notes:
1. Atlas now has 32 notes (entities, projects, daily, sessions, agents)
2. Vimwiki integration: index.md needs `[[path|display]]` format for proper navigation
3. SUGGESTION: Add `cart ls` and `cart show` commands — users cannot discover content
4. SUGGESTION: Fix query syntax — `cart query maggie` errors, needs `cart query 'text:maggie'`
5. SUGGESTION: Session file paths in prompts should be dynamic, not hardcoded
6. CODEX HANDOVER: Created ~/atlas/agents/codex/HANDOVER_CART_CLI_VIMWIKI.md
7. RUNBOOK: Created ~/dev/cartographer/runbooks/bootstrap-runbook.md
8. OWNERSHIP: Wizard owns orchestration/runbooks, Cassette owns content, Codex owns code
9. TOP 3 CODE CHANGES: (a) cart ls command (b) cart show command (c) query syntax fix
10. VERIFICATION: `cart status` now shows 32 notes, sessions ingested, agents tracked
6. Daily note created with mapsOS sync section using cart blocks
7. Contribution file format worked well for documenting what was found
8. SUGGESTION: Add explicit "recent decisions" and "open questions" sections to project notes template
9. SUGGESTION: Entity notes should include "what this person needs from maps" section

---

*the tape keeps rolling. the server never sleeps.*
