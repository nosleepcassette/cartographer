# cartographer — Model Summaries Spec
# maps · cassette.help · MIT
# generated: 2026-04-17
# status: SCOPED / READY FOR IMPLEMENTATION

---

## Objective

Turn `cart summarize` from a single loose plugin call into a stable summary system with repeatable profiles, explicit inputs, and durable outputs.

The system already has a summary hook point. What it lacks is structure:

- summary intent is underspecified
- model choice is a free string with no profile semantics
- outputs are ephemeral unless the operator manually writes them somewhere
- there is no cache or provenance for when a summary should be refreshed

---

## Scope

### Summary profiles

Add named profiles on top of the existing `--model` flag:

- `brief` — fast operator recap
- `handoff` — for agent transitions and session restarts
- `decision` — decision log with rationale and open questions
- `daily` — synthesis across notes, tasks, and mapsOS state
- `entity` — who/what/why summary for a single entity or project

Each profile defines:

- prompt contract
- preferred max words
- expected output sections
- whether citations are required

### Input selection

Support summary input modes beyond raw query results:

- direct query results
- explicit note ids / paths
- stdin path lists
- current day bundle
- recent sessions
- project/entity scoped bundles

### Output durability

Add first-class write targets:

- stdout only
- note section update
- sibling summary note
- managed summary block inside an existing note

Every written summary should include:

- generated timestamp
- source query or source note list
- selected model
- profile name

### Freshness and caching

Cache summaries by:

- summary profile
- model
- ordered source note ids
- source mtimes or content hash

If nothing changed, cart should be able to say the existing summary is still fresh instead of regenerating it.

---

## CLI Surface

Target shape:

```zsh
cart summarize "type:project status:active" --profile handoff
cart summarize alpha beta --profile entity --write projects/alpha-summary.md
cart summarize --profile daily --today
```

Follow-on flags:

- `--profile`
- `--json`
- `--refresh`
- `--write-mode managed|replace|stdout`

`--model` stays, but profiles become the primary operator concept.

---

## Data Model

Add a lightweight summary record store under `.cartographer/`:

- profile
- model
- source ids
- source hash
- output path
- generated at

This should remain metadata only. The summary itself still lives in Markdown files or stdout.

---

## Acceptance

- operators can ask for the same summary shape repeatedly without prompt drift
- written summaries carry provenance
- stale vs fresh summaries are distinguishable
- the command remains usable without any external model backend changes

---

## Non-Goals

- building a proprietary summary store
- forcing one summary format for every workflow
- tying summaries to qmd
