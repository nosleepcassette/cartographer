---
name: create-skill
description: Guided conversation for creating a new Claude skill with consistent frontmatter, sharp triggers, concrete inputs and outputs, model fit, and an acceptance test. Use when a new skill is needed and the user should be interviewed before any file is written.
user_invocable: true
version: 0.1.0
metadata:
  author: maps · cassette.help
  tags: [skills, claude-code, scaffolding, workflow, interviewing]
---

# create-skill

Guide the user through a six-phase interview, then write a production-ready `SKILL.md`.

Do not one-shot this. Even if the user sounds specific, you still need the full interview so the skill is reusable instead of half-shaped.

## before starting

Read one or two existing skills for shape before drafting the new one:

- `~/.claude/skills/qmd/SKILL.md`
- another nearby skill in `~/.claude/skills/` or `skills/`

Default destination:

- repo-local `skills/<skill-name>/SKILL.md` when working inside a repo
- `~/.claude/skills/<skill-name>/SKILL.md` when the user wants it installed globally

If the user already named a destination, use that.

## non-negotiables

- Ask one question at a time
- Wait for the answer before moving to the next phase
- Do not create the file before the final confirmation
- Do not use multiple choice when freeform is clearer
- Do not invent inputs, outputs, or triggers the user did not endorse
- If the user pauses halfway through, summarize captured answers and the next missing phase instead of writing a partial file

## phase protocol

### Phase 1 — Purpose

Ask:

- What problem does this skill solve for maps?
- What should the skill be called?

Rules:

- Prefer lowercase, hyphenated names
- Reject names that collide with existing skills in the destination directory
- If the user names a capability instead of a problem, push once for the actual need

### Phase 2 — Triggers

Ask for natural-language triggers.

You need:

- at least 5 phrases the user might actually say
- a short description sentence that makes the trigger boundary obvious

Push for sharp triggers. "Use when needed" is not a trigger.

### Phase 3 — Inputs

Ask what the skill reads or depends on.

Cover:

- arguments or prompt inputs
- files or directories it reads
- env vars, CLIs, APIs, or external systems
- whether missing dependencies should fail hard or degrade gracefully

### Phase 4 — Outputs

Ask what the skill should produce.

Cover:

- files it writes
- stdout or chat output shape
- whether it edits existing files
- what "done" looks like

### Phase 5 — Model Fit

Ask which model tier the skill needs and why.

Classify it as one of:

- light and mechanical
- medium reasoning
- deep reasoning

If the user has no opinion, infer it and explain the tradeoff in one sentence.

### Phase 6 — Acceptance Test

Ask for one concrete invocation and expected outcome.

The acceptance test must be specific enough that someone can tell whether the skill worked without reading the whole file.

## confirmation

Before generating, summarize:

- purpose
- triggers
- inputs
- outputs
- model fit
- acceptance test
- destination path

Ask for confirmation or corrections. Do not write the file until the user confirms.

## generation rules

When confirmed, write a `SKILL.md` with:

1. YAML frontmatter containing `name`, `description`, `user_invocable`, `version`, and useful metadata tags
2. A short explanation of what the skill does
3. A "When to use" section grounded in the triggers
4. A workflow or protocol section that tells the agent how to execute the skill
5. Failure modes or guardrails when the skill touches real systems
6. One concrete acceptance test example

Match the style of local skills:

- direct language
- no filler
- concrete commands and paths
- minimal but useful examples

## final response shape

After writing the file:

- report the path
- give a two-line summary of what the skill now does
- include the acceptance test invocation in one short code block

## example acceptance test

Example request:

`/create-skill make me an echo skill that prints a timestamp`

Expected outcome:

- writes `skills/echo-skill/SKILL.md`
- generated skill explains triggers, inputs, output format, and timestamp behavior
- acceptance example shows the invocation and a timestamp-shaped result
