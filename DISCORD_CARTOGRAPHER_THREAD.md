# atlas / cartographer discord thread

```md
alright hermes gang listen up because this one actually matters

separate thread because this is the infrastructure layer. mapsOS is the human. cartographer is the brain.

mapsOS thread:
<https://discord.com/channels/1053877538025386074/1492209844185338077>

---

**the problem: your agents have fucking amnesia.**

every session starts from zero. every conversation dies when the context window fills. everything your agent learned about you, your projects, your life, your patterns? gone the second you close that terminal.

**cartographer is the cure.**

it's a local-first knowledge filesystem and agent memory layer that actually persists. plain markdown. git history. queryable graph. block-addressable text. humans and agents write to the same substrate.

but here's the part that should make you pay attention:

**it's built for Hermes agents specifically.**

- `cart session-import hermes --all` — pull every session your agent has ever had into a graph
- `cart daily-brief` — your next session starts with actual context instead of "who are you again"
- `cart learn "observation" --topic <slug>` — durable learnings that don't evaporate
- `cart query 'tag:project status:active'` — query your own memory like it's a database
- `cart graph --export` — all notes as nodes, all links as edges, feed it into whatever viz you want

this isn't "i made a notes app." this is the memory layer that Hermes agents have been missing.

---

**the loop is the killer feature:**

```
session → mapsOS / notes / tasks / exports → cartographer ingests → daily brief → next session with real memory
```

your agents stop forgetting. your patterns become visible. your state data stops being a dead-end dashboard and becomes part of an actual memory topology.

---

**for mapsOS users:**

this is a massive upgrade. before: mapsOS could tell you how you were doing. now: that data feeds into a durable memory system.

- qualitative state is no longer trapped in one app
- session exports become atlas context
- tasks, notes, learnings, and state all live in the same loop
- your next session inherits everything instead of starting from zero

most "agent memory" projects completely miss the human-state context. they know your projects but not that you're in survival mode. they know your tasks but not that you've been depleted for three days. mapsOS + cartographer fixes that.

---

**for Hermes users specifically:**

- session import means conversations accumulate into a graph, not flat logs
- learnings become durable notes with provenance, not invisible vibes
- project/entity/backlink structure gives your agent actual memory topology
- block references and backlinks instead of giant context dumps
- plugin surface for building weird local-first agent systems
- everything is files. delete cartographer and your brain still works.

---

**new in this push:**

- `cart tui` — Textual atlas interface with graph navigation
- note rendering with transclusions
- backlinks panel
- tasks overlay
- mapsOS handoff from inside the TUI
- state visible inside the atlas surface
- ChatGPT and Claude.ai bulk import (deduped by default)
- graph export for d3/gephi/obsidian
- mapsOS bridge: `cart mapsos ingest-exports --latest`

---

**this is the layer i want people building on.**

if you're building Hermes-adjacent tools, agent plugins, local memory systems, or anything that needs context to survive across sessions:

cartographer:
<https://github.com/nosleepcassette/cartographer>

mapsOS:
<https://github.com/nosleepcassette/mapsOS>

install both. run `cart init` and `maps check`. see what happens when your agent actually remembers you.

the tape keeps rolling. the server never sleeps.
```
