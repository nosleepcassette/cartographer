# cartographer — Claude/OpenCode Review Scope

Generated: 2026-04-16

## what changed in this pass

- Real plugin runner with JSON stdin/stdout contract.
- Built-in plugins: `summarize`, `daily-brief`, `agent-ingest`.
- `cart learn` writes learning blocks into `agents/<agent>/learnings/*.md`.
- `cart agent-ingest` ingests session JSON into:
  - `agents/<agent>/sessions/*.md`
  - `agents/<agent>/learnings/*.md`
  - `agents/<agent>/SUMMARY.md`
  - `entities/*.md`
- `cart agent-gc --threshold X` decays/prunes low-confidence learning blocks.
- `cart summarize` now runs through the summarize plugin.
- Notes with `auto_blocks: true` get block IDs inserted after `cart new/open/edit`.

## what to review now

### 1. session ingest schema

Current state:
- `agent-ingest` accepts loose JSON and tries to normalize `summary`, `learnings`, `entities`, and `messages`.
- This is intentionally permissive so Hermes/Claude/OpenCode can all feed it.

Review question:
- Should cartographer lock a stricter v1 session schema now, or keep the loose adapter layer and version the adapters instead?

Why it matters:
- A strict schema reduces ambiguity.
- A loose schema makes it easier to adopt across Claude/OpenCode exports quickly.

### 2. learning block format

Current state:
- Learnings are stored as Markdown blocks with attrs:
  `type`, `confidence`, `source`, `date`, `confirmed`, optional `entity`.

Review question:
- Is block-attr metadata sufficient, or should learning entries move to a richer inline YAML or nested frontmatter format?

Why it matters:
- Current format is grep-friendly and block-addressable.
- Richer metadata may be needed for review/confirmation/audit flows.

### 3. provenance and quote capture

Current gap:
- Learnings store a source tag, but not exact quote spans, message ids, or transcript offsets.

Recommended addition:
- Add optional provenance attrs:
  `session_id`, `message_id`, `speaker`, `quote`, `offset_start`, `offset_end`.

Review question:
- How much provenance is necessary before the memory layer is trustworthy enough for agent recall?

### 4. confirmation workflow

Current state:
- Confidence decay exists.
- Confirmation count is stored, but there is no `cart confirm` or human-review loop yet.

Recommended addition:
- Add `cart learn confirm <topic|block-id>` and `cart learn reject <block-id>`.
- Emit confirmation/rejection events into worklog.

Review question:
- Should confirmations attach to the learning block directly, or live as separate review events?

### 5. Claude/OpenCode transcript adapters

Current gap:
- `agent-ingest` handles generic JSON, but not explicit import adapters for:
  - Claude export formats
  - OpenCode / Codex session logs
  - plain Markdown transcripts

Recommended addition:
- `cart import claude <file>`
- `cart import opencode <file>`
- `cart import markdown-session <file>`

Review question:
- Should these be first-class commands or just plugins shipped beside `agent-ingest`?

### 6. entity consolidation

Current state:
- Entity notes append session backlinks.
- There is no alias resolution, duplicate merge, or canonical-name selection.

Recommended addition:
- Add alias metadata:
  `aliases`, `canonical`, `entity_type`.
- Add `cart entities merge foo bar`.

Review question:
- Is alias resolution core enough for phase 2, or should it wait until more real data exists?

### 7. summary synthesis backends

Current state:
- `summarize` is deterministic local extraction, not model-backed synthesis.
- `agents/<agent>/SUMMARY.md` is updated mechanically during ingest.

Recommended addition:
- Plugin backends for:
  - Hermes
  - Claude
  - local/manual
- Fallback chain in config.

Review question:
- Should synthesis stay plugin-only, or should cartographer expose a backend abstraction in core Python?

### 8. safe concurrent writes

Current gap:
- Multiple agents can write the same learning/entity/summary file without lock files or merge strategy.

Recommended addition:
- Add optimistic write guards with hash checks.
- If file changed since read, append a conflict block instead of overwriting silently.

Review question:
- Is git-level conflict handling enough, or does cartographer need app-level merge protection?

### 9. review workspace for agents

Recommended addition:
- `reviews/` directory in atlas for machine-generated review notes:
  - `reviews/claude/*.md`
  - `reviews/opencode/*.md`
- `cart review enqueue <query>`
- `cart review ingest <agent> <file>`

Why it is useful:
- Separates durable memory from speculative review output.
- Keeps Claude/OpenCode critique threads inspectable and reversible.

### 10. transclusion and citation rendering

Current gap:
- Block refs index correctly, but transclusion/export is still absent.

Recommended addition:
- `cart export --resolve-blocks`
- render `![[note#block]]`
- optional inline provenance footnotes

Review question:
- Should export happen before richer provenance, or after it?

## recommended next build order

1. Add explicit Claude/OpenCode import adapters.
2. Add confirmation/rejection commands for learnings.
3. Add provenance fields to learning blocks.
4. Add conflict-aware writes for summary/entity/learning files.
5. Add model-backed summary plugins as optional backends.

## review standard to hold

- No feature should hide provenance.
- No feature should silently overwrite higher-confidence memory.
- Claude/OpenCode additions should degrade cleanly to plain files and plugins.
- If a feature requires non-local state, it should probably stay out of cartographer core.
