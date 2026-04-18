# cartographer + mapsOS — Bridge V2 Spec
# maps · cassette.help · MIT
# generated: 2026-04-17
# status: SCOPED / PARTIAL FOUNDATIONS LANDED

---

## Objective

Make the cartographer <-> mapsOS boundary structured, low-latency, and durable.

The current bridge works, but it is thin and lossy:

- `mapsOS/environments/cart_bridge.py` shells out to human-readable cart commands
- open tasks are scraped from `cart todo query` line output
- recent sessions are inferred from plain `cart query` path output
- bridge health is spread across multiple command and filesystem assumptions

That is enough for a prototype. It is not enough for a system that other clients should trust.

---

## Current Contract Problems

### Human text as API

The bridge currently depends on output intended for humans. That creates break risk every time the CLI gets nicer.

### One-way emphasis

mapsOS exports ingest into cart well, but the return path back into mapsOS is still mostly task hints and daily brief text.

### No explicit health budget

There is no shared notion of:

- expected latency
- stale export tolerance
- degraded but usable state
- hard failure

---

## Foundations Already Landed

These cart surfaces now exist and should become the basis for the upgraded bridge:

- `cart status --json`
- `cart doctor --json`
- `cart query --json`
- `cart todo list --json`
- `cart todo query --json`

That means mapsOS no longer needs to parse task lines or query output by string splitting once the bridge is updated.

---

## Workstream 1 — Structured CLI Contract

**Priority:** P0

mapsOS should switch from line parsing to JSON calls immediately.

Replace:

- `cart todo query ...`
- `cart query ...`

With:

- `cart todo query --json ...`
- `cart query --json ...`
- `cart doctor --json`

Bridge code should validate JSON shape and degrade to empty payloads on parse failure.

---

## Workstream 2 — Atlas Session Surface

**Priority:** P0

Add a session-focused CLI surface in cart, instead of forcing mapsOS to query generic note paths and infer meaning.

Target command family:

```zsh
cart sessions recent --limit 3 --json
cart sessions show hermes-2026-04-17-foo --json
```

Required payload:

- note id
- title
- path
- date
- source agent
- brief excerpt

---

## Workstream 3 — mapsOS State Pulls

**Priority:** P1

Let cart expose the latest ingested mapsOS snapshot as a structured read surface for clients that want atlas + state together.

Target command:

```zsh
cart mapsos latest --json
```

This should return:

- latest snapshot path
- date
- current state
- active arcs
- open tasks derived from mapsOS

---

## Workstream 4 — Health and Latency Budget

**Priority:** P1

Define the bridge service contract:

- task query: target under 2s
- daily brief: target under 5s
- bridge health probe: target under 1s
- stale exports: warn after 24h

`cart doctor --json` should feed directly into mapsOS `/check` or a sibling health surface so operators can see whether the problem is:

- cart unavailable
- atlas not initialized
- index stale
- mapsOS exports stale
- qmd optional layer unavailable

---

## Workstream 5 — Bidirectional Task Sync

**Priority:** P1

Current task write-back is only hint-level. Move to explicit state sync:

- mapsOS creates/updates tasks in cart with stable source ids
- cart completion updates write back with stable source ids
- conflict policy is explicit, not implied

This requires a durable mapping layer, not only project-name heuristics.

---

## Acceptance

- mapsOS bridge consumes only structured JSON from cart for query/task/health paths
- bridge failure modes become diagnosable in one probe
- recent sessions and task data stop relying on formatting details
- task completion sync becomes stable enough to treat as real state, not a hint
