# AGENT_CONTRIBUTE.md
# maps · cassette.help · MIT
# generated: 2026-04-16
# purpose: contribution prompt for any agent to add to MASTER_SUMMARY.md
# version: 1

---

## how to use this

Any agent can run this. You do NOT need to regenerate the full master summary.
Your job is narrower: assess what you know that isn't already in MASTER_SUMMARY.md,
and contribute only the parts you can actually verify from your own context.

To run:
```zsh
hermes chat -q "$(cat ~/dev/cartographer/AGENT_CONTRIBUTE.md)"
```

Or paste directly into any agent session.

---

## step 1 — read the current master summary

Read: `~/atlas/agents/MASTER_SUMMARY.md`

If it doesn't exist: stop here. Run HERMES_BOOTSTRAP.md first.

Note the `updated:` date in the frontmatter and the `version:` number.

---

## step 2 — self-assess your contribution capacity

Before doing anything else, answer these questions honestly:

**A. What is your agent type?**
Options: hermes / codex / vesper-claude / opencode / other
State which you are.

**B. What unique context do you have access to?**

| Agent | Typical unique context |
|---|---|
| hermes | `~/.hermes/sessions/`, soul files, handovers, long-term memory graph |
| codex | recent code edits, build output, test results, file-level work history |
| vesper-claude | current session context, recent tool calls, file reads from this session |
| opencode | editor state, open files, recent diffs, compilation output |

Check what you actually have. Don't claim sources you can't read.

**C. Do you have anything new to contribute?**

Check:
- Session data newer than `updated:` in MASTER_SUMMARY.md
- Code changes or decisions not reflected in current summary
- Project status updates you observed
- Errors, blockers, or completions you handled
- Patterns you noticed about how maps works
- Quotes from maps worth preserving (QUOTE RULE)

If you have nothing newer than the current summary: say so clearly and stop.
Do not pad. A "nothing to add" response is a valid and useful response.

---

## step 3 — CASSETTE ONLY: mapsOS intake

**Skip this step unless you are the Cassette agent.**

Only Cassette has access to mapsOS intake data.
If you are Cassette, check:
- `~/dev/mapsOS/intakes/` — most recent intake files
- `sqlite3 ~/dev/mapsOS/maps.db "SELECT * FROM entries ORDER BY timestamp DESC LIMIT 20"`
- Any new intake entries since the `updated:` date in MASTER_SUMMARY.md

Extract: mood tracking, health notes, task completions, new project mentions, quotes.

---

## step 4 — contribute what you have

If you identified new, verifiable content in step 2 (or step 3 if Cassette):

Write your contribution to: `~/atlas/agents/[your-agent-name]/CONTRIBUTION.md`

Format:
```markdown
---
agent: [your-agent-name]
contributed: YYYY-MM-DD
master_summary_version: N  ← version you read in step 1
sources_checked: [list what you actually read]
---

## what I found

[Only verified facts. Source every claim: "(from: filename)" or "(observed in session)".]
[No speculation. No padding. If unsure, say "unconfirmed".]

### project updates
[Status changes you can verify — with dates]

### decisions made
[Any architectural/personal/project decisions you observed — with dates]

### patterns observed
[Recurring behaviors, preferences, or friction points — with examples]

### quotes
[Anything characteristic maps said, verbatim — with date and context]
[Format: "YYYY-MM-DD | context | 'verbatim quote'"]

### errors / blockers resolved
[Technical problems you saw and fixed or diagnosed]

### suggested master summary updates
[Specific lines/sections in MASTER_SUMMARY.md that should change, and how]
```

---

## step 5 — log your work

After writing your contribution file:

```zsh
cart worklog log "[your-name] contributed to MASTER_SUMMARY.md — [N] items, [N] project updates, [N] quotes"
```

If `~/atlas/` has not been fully initialized with cartographer yet, skip the CLI log
and use the Garden fallback below instead.

Or via Garden MCP:
```
remember("CONTRIBUTED: [your-agent-name] → MASTER_SUMMARY.md — [brief summary of what you added]", graph="cassette")
```

---

## step 6 — notify Hermes

Hermes is the integrator. After contributing, append to
`## contribution notices` in HERMES_BOOTSTRAP.md:

```
YYYY-MM-DD | [your-agent-name] | contribution written to ~/atlas/agents/[name]/CONTRIBUTION.md — [one line summary]
```

Hermes will incorporate your contribution on its next `--update` run.

---

## what NOT to do

- Do not rewrite MASTER_SUMMARY.md directly. That's Hermes's job.
- Do not contribute content you can't verify from your own sources.
- Do not repeat what's already in the current summary.
- Do not fabricate project status. If you don't know the current state, say "status unknown since [date]".
- Do not include negative characterizations of maps. Frame everything as working-with-maps context.

---

## prompt improvement notes

(append-only — agents write here)

2026-04-16 | vesper/claude | Initial version. Built to separate contribution from integration —
Hermes integrates, other agents contribute to their own files. Cassette-only mapsOS
intake is explicit gating. "Nothing to add" is valid output.
