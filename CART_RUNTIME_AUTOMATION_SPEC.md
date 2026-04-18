# cartographer — Runtime Automation Spec
# maps · cassette.help · MIT
# generated: 2026-04-17
# status: SCOPED / READY FOR FOLLOW-UP

---

## Objective

Strengthen cart’s operator loop with lightweight runtime automation:

- protect critical files
- validate note writes
- surface attention prompts when background work needs a human
- give agent-style workflows a small continuity layer

The repo already has hooks. This spec is about making them feel like a system instead of an empty extension point.

---

## Missed-but-Useful Patterns

### Protected write surfaces

Critical atlas files should be guardable by policy before write:

- dispatcher or operator registry files
- managed summaries
- generated graph exports
- shared config files

This should be opt-in and atlas-local, not hardcoded globally.

### Frontmatter validation

Markdown writes should be able to trigger a validation pass after write:

- YAML parses
- required ids stay present
- known frontmatter fields keep expected types

Warn first. Do not silently rewrite broken data unless a dedicated fixer is invoked.

### Attention hooks

Long-running or background workflows should have a way to raise local attention:

- desktop notification
- log line in a known file
- queue entry for later triage

This is especially useful once cart grows more background indexing and summary refresh work.

### Agent continuity

If cart grows stronger agent-native workflows, a small per-agent scratchpad model is worth standardizing:

- one state file per operator/agent/tool role
- overwrite, not append forever
- short enough to stay readable

This is not a transcript replacement. It is a resumable post-it.

### Structured registry

The current dispatcher docs are useful, but a machine-readable registry would make automation safer:

- command / wrapper registry
- agent / role registry
- hook registry

That unlocks better CLI discovery and validation.

---

## Proposed Phases

### Phase 1

- ship sample `pre-write` and `post-write` hooks
- add frontmatter validator reference hook
- add protected-files reference hook

### Phase 2

- add `cart hooks doctor`
- document hook payloads and event names
- add notification hook examples

### Phase 3

- add structured registry files for agents, wrappers, and hooks
- add lightweight post-it convention for long-running agent workflows

---

## Acceptance

- cart hooks become discoverable and reusable
- operators can turn on guardrails without editing core code
- write failures become clearer
- future agent workflows have a small continuity primitive ready
