# cartographer

Run `cart discover` on the notes you already have and get immediate graph value in the first five minutes. Semantic search over Markdown. Typed, weighted wires. Human-readable provenance. Trace paths across the graph. Live graph server. All local, all git-native, all files.

```
cart discover             →  find 23 similar-but-unwired note pairs in your existing notes
cart discover --interactive   →  review candidates one by one with predicate + weight
cart trace grungler       →  trace weighted graph paths out from one note
cart graph --serve        →  live graph at localhost:6969, auto-regenerates on file change
cart stats                →  557 notes · 234 wires · 23 orphans · 78% embedding coverage
cart query 'relationship drift with grungler'  →  semantic match, not keyword grep
cart operating-truth      →  active work, open decisions, commitments, next steps
```

Your agents should know how you're actually doing — and remember everything they learn.

Local-first knowledge filesystem and agent memory layer. Plain Markdown. Git history. Queryable graph. Block-addressable text. Embedding search. Emotional topology. Agents and humans write to the same substrate. Nothing is trapped in an app.

https://github.com/user-attachments/assets/bf92d69a-15ea-47bb-a6af-386eae3f5ef1

---

## What makes this different from every other agent memory layer

Vector databases. Hosted memory APIs. Pinecone, Mem0, raw context stuffing, custom RAG pipelines. They all solve the same narrow problem: *getting context into a prompt.* They're mostly invisible, mostly opaque, mostly locked to whoever built them. Your memories live in a binary blob you can't read, can't edit, can't version, and can't get out when the service shuts down.

cartographer is not a memory layer. It's a **knowledge substrate** that happens to be excellent at agent memory — and does things no hosted memory API can:

**Semantic wires with emotional predicates.** Not just `[[links]]` — wires say *how* things relate: `supports`, `depends_on`, `contradicts`. And each wire carries emotional metadata: valence (positive/negative/mixed), energy impact (energizing/draining), avoidance risk (high/medium/low), growth-edge, current state. `cart wire query --avoidance-risk high` returns every relationship where avoidance is active. This is the emotional topology layer — and it's unique to cartographer.

**Embedding-backed search that stays local.** Every note gets auto-embedded at write time (FastEmbed, ONNX, CPU, no GPU needed). `cart query 'relationship drift with grungler'` finds the note you meant even when it never uses those exact words. No hosted vector service. No external dependency. Embeddings live in your SQLite index alongside the full-text search.

**Trace paths over the graph.** `cart trace grungler` doesn't just find notes mentioning that note ID — it follows the wires outward with depth and decay, surfacing what is structurally connected rather than just what shares a keyword. This is graph reasoning, not keyword search.

**Bridge discovery.** `cart discover` finds notes that are semantically similar but not yet wired — the gaps in your graph. `--interactive` lets you review them one by one with predicate, weight, confidence, and timing metadata. `--accept` still exists for batch workflows.

**Wire provenance.**

> Most knowledge tools have no answer to "did anyone actually think about this connection, or did the AI dump it here?" Cartographer does. Every wire carries provenance — who created it, how long the human spent reviewing it, whether it was confirmed or just accepted. The graph shows reviewed wires as solid lines and unreviewed wires as dashed. You can see, at a glance, which parts of your knowledge graph are load-bearing and which are provisional.

**A live graph server.** `cart graph --serve` starts a localhost HTTP server that serves the interactive HTML graph and auto-regenerates whenever atlas files change. The server now exposes predicate colors, trace data, and discover candidates over `/api/*` for theme-driven graph workspaces.

**Operational truth.** `cart operating-truth` tracks active work, open decisions, commitments, and next steps — the things an agent needs at session start, not just a narrative summary. `cart daily-brief` leads with operating truth.

**Files are the API.** Delete cartographer and your notes are still readable Markdown with YAML frontmatter. Git is the database. SQLite is an index that rebuilds from scratch. Nothing is trapped.

**Plugin economy.** stdin/stdout JSON contract. Therapy plugin ships with cartographer — pattern detection and counter-evidence queries backed by the emotional topology layer. Write your own in Python, shell, Rust, Lua — anything.

**Built for configuration, not customization.** Backend config drives graph themes, privacy modes, person ordering, state vocabulary, arc definitions, embedding models, guardrail rules. The system is designed to be shaped by whoever runs it.

---

## Who this is for

- **Neurodivergent people** managing ADHD, autism, RSD, emotional flashbacks, and capacity shifts — systems that adapt to how your brain actually works rather than demanding your brain adapt to them
- **Therapists and counselors** accumulating session notes into entity profiles, surfacing patterns across clients, tracking what interventions actually work over time — all local, no vendor, no cloud
- **Teachers and educators** keeping intervention histories, learning-difference profiles, and cross-year patterns per student — the kind of institutional memory that normally evaporates when you change grade levels
- **Researchers** where every paper becomes a note, every quote is a block reference, agent session logs link to the papers that informed them, and the query layer answers "what do we know about X"
- **Operations and engineering teams** where incident reports, runbooks, post-mortems, and architectural decisions all live in the same graph — backlinks show you which runbook section was consulted during which incident, and agents write session logs to the same atlas engineers read
- **Developers building with LLMs** who are tired of their agents starting every session from zero

---

## Why this is different

Most knowledge tools ignore AI entirely. Most AI tools ignore your history. cartographer assumes both exist and treats them as first-class:

- **Agent memory persists.** Session import turns context windows into a growing graph. `cart daily-brief` seeds tomorrow's session from everything that happened today.
- **Files are the API.** Delete cartographer. Your notes are still readable Markdown with YAML frontmatter. Git is the database. SQLite is an index, not a prison.
- **Block-addressable by default.** `[[note-id#block-id]]` transclusion. Backlinks tracked automatically.
- **Imports are idempotent.** Run `cart session-import` a hundred times. Zero duplicates. Just an always-current graph.
- **Semantic wires with emotional predicates.** Wires capture what relationships *are*, not just that they exist — valence, energy impact, growth edges, avoidance territory, current state. The emotional topology layer is queryable.
- **Optional semantic search without lock-in.** If `qmd` is installed, plain-language `cart query` uses hybrid retrieval over the atlas. If not, cart can fall back to local embeddings when available, then to built-in SQLite/FTS. Same query surface, no hosted vector service required.
- **Plugin economy.** stdin/stdout JSON contract. If it speaks that, it joins. Python, shell, Rust, Lua — anything.
- **Built for configuration, not customization.** Backend config drives graph themes, privacy modes, person ordering, state vocabulary, arc definitions, mapsOS tracks. The system is designed to be shaped by whoever runs it.

---

## configurability — the backend goes deep

The atlas and cartographer are designed to be shaped by whoever runs them. What's configurable:

**Atlas config (`~/atlas/.cartographer/config.toml`):**
- Graph theme preset (`baseline`, `astral`, or any `~/atlas/themes/*.js` skin)
- Privacy modes: `off`, `names`, `names_relationships`, `full` — driven from config, not code
- Person ordering and never-redact IDs for the graph
- qmd collection path for hybrid retrieval
- mapsOS integration settings
- Embedding backend, model, auto-embed-on-write, similarity threshold
- Bridge discovery threshold and max proposals
- Spreading activation defaults (depth, decay, emotional weighting)
- Dream engine settings (bridge discovery, weight decay, pruning threshold)
- Temporal pattern detection settings (lead time, bucket size, significance threshold, permutation count)
- Operating-truth extraction and retention settings
- Temporal review thresholds for stale/current truth
- Guardrail rules for secrets, stack traces, duplicate notes, and raw code blobs
- Query-routing budgets for operating-truth/profile/graph/corpus shelves
- mapsOS integration settings

**mapsOS (`~/.maps_os_config.yaml`):**
- Atlas & Cartographer were built atop mapsOS - the qualitative life tracker. Braindump to your agent & it'll parse your data into a detailed & useful map of your entire life.
- State vocabulary — define what emotional/cognitive states matter for your context
- Arc definitions — patterns of states that indicate something (hyperfocus cycle, shutdown, recovery arc)
- Capacity thresholds
- Track definitions — what to track alongside state (sleep, medication, social contact, whatever)
- Person entries — who's in your support network and why
- Automatic task workflow. Builds & maintains your todo list for you. 

**Therapy plugin (`user-configs/<username>.yaml`):**
- Pattern definitions with custom keywords and counter-queries
- Intervention library with effectiveness tracking
- IFS parts map location
- Modality preferences
- Crisis protocol

**Agent skills and plugins:**
- Drop anything into `.cartographer/plugins/` — it runs on `cart plugin run`
- Templates in `.cartographer/jinja/`
- Hooks in `.cartographer/hooks/`
- Agent skill definitions can layer on top of any of this

**Visual graph skins:**
- Theme JS files in `~/atlas/themes/*.js` are auto-loaded
- Each theme registers its own node glyph set, wire aspect symbols, color palette, CSS variables, and animation behavior
- The theme picker in the graph sidebar lets you switch at runtime

The system doesn't tell you what your knowledge should look like. It gives you the shape and lets you fill it.

**I built it for my brain. You can build it for yours.**

---

## The therapy plugin

`cart therapy` is a real working example of what you can build on the atlas substrate — and it ships with cartographer.

The plugin lives at `~/atlas/agents/cassette/skills/therapy-plugin/`. It's a configurable pattern detection and intervention support system backed by the emotional topology layer. Not an AI chatbot in therapy drag. A data-driven tool that queries the atlas to surface grounded evidence when a spiral pattern is detected.

**What it detects:**

| Pattern | What it looks like |
|---------|-------------------|
| RSD spiral | The gap between stimulus and conviction is seconds. "They haven't responded" becomes "they're leaving" before any evidence arrives. |
| Isolation spiral | Withdrawal feeding more withdrawal. Contact feels impossible because isolation says it is. |
| Executive paralysis | Knowing exactly what needs doing. Not being able to start. Shame about not starting compounding the paralysis. |
| Manic flooding | Energy and ideas outrunning capacity. Starting everything, finishing nothing, crash. |
| Shame spiral (relational) | Connection ended or strained. RSD fills in "I wasn't enough" before anyone said it. |
| Time blindness cascade | ADHD time perception is unreliable. Perceived gap and actual gap are different numbers. |

**How it responds:**

Not reassurance. Counter-evidence queries against the atlas: "What's their actual response pattern? What did they say?" Micro-tasking for paralysis: not "do the thing," just "open the doc." Smallest possible action. Autonomy-first throughout — it suggests, you decide.

**The configurability:**

Patterns and interventions are YAML files, not code. `user-configs/<username>.yaml` layers on top of the generic plugin:

```yaml
patterns:
  RSD-spiral:
    keywords:
      - "didn't respond"
      - "your phrase here"
    counter_query: "your grounding question here"
    removed: false
```

The intervention log tracks what actually works for a specific person over time — effectiveness ratings, usage history, outcome notes. A therapist building a client-specific instance configures the patterns.yaml for that client's actual spirals, the interventions.yaml for what's historically worked, and the system surfaces that history at the moment it matters.

An ADHD coach. A recovery sponsor. A peer support worker. A parent of a kid with RSD. Someone building an agent that supports their own nervous system through difficult periods. The structure is the same; the configuration is yours.

**Under the hood:**

```bash
echo '{"content": "they haven't responded and I feel like I failed them"}' | \
  python3 ~/.hermes/skills/therapy-plugin/scripts/pattern-detect.py
```

```json
{
  "patterns": [
    {
      "pattern": "RSD-spiral",
      "keyword_found": "haven't responded",
      "counter_query": "What's their actual response pattern?"
    }
  ]
}
```

It's a script that reads stdin and writes JSON. Plugs into any agent that speaks the contract.

**Crisis handling:**

The plugin includes a configurable crisis protocol. Default: trust the person to know their own danger level, surface resources if requested, ask what they need. The protocol is explicit in the YAML — not a black box, not a hotline auto-dialer. You define what appropriate response looks like for your context.

---

## What shipped

**Emotional topology layer:**
- Semantic wiring with emotional predicates: valence, energy-impact, avoidance-risk, growth-edge, current-state
- Wire-level queries: `cart wire query --avoidance-risk high`, `cart wire emotional-summary <person>`
- Separate graph model: exocortex (relationship graph) vs activity timeline (session logs). Two clean mental models, cross-referenceable, no frequency noise.
- Capacity-aware routing: surface support relationships when energy is low, growth-edges when high

**Visual graph:**
- Self-contained HTML graph - offline-safe, single exported file
- Live local graph server: `cart graph --serve`
- Background daemon mode: `cart graph --serve --daemon`, plus `--status-daemon` and `--stop-daemon`
- Deterministic 3D clustered layout
- Emotional-valence node coloring, avoidance-aware node sizing
- Theme system: `baseline`, `astral` (hand-drawn in-scene celestial sigils, alchemical wire labels), plus auto-loaded atlas-local themes
- Theme picker in graph sidebar - switch without re-export
- Privacy modes driven from config
- Local search, category toggles, wire toggles, type browser
- Keyboard navigation, PNG/JSON export, shareable URL state
- Markdown-rendered note previews

**Therapy integration:**
- Pattern detection: RSD spiral, isolation, executive paralysis, manic flooding, shame spiral, time blindness cascade
- Counter-evidence queries against the atlas
- Intervention log with effectiveness tracking
- Configurable per-user via YAML
- `cart therapy review`, `cart therapy counter-evidence`, `cart therapy export`

**Atlas TUI:**
- Section jumps (`[`/`]`), direct slot jumps (`1`-`5`)
- Semantic wire neighborhood
- Block transclusion rendering
- Task overlay (`t`), mapsOS handoff (`m`)

**Graph-native reasoning + search:**
- `cart trace <note>` for weighted graph traversal output
- `cart walk <note>` for neighborhood traversal with growth-edge / avoidance filters
- `cart discover`, `cart discover --interactive`, and `cart discover --export`
- `cart profile list` / `cart profile apply <name>` for switching wire vocabularies
- `cart wire review` for pending human review on provisional wires
- `cart stats` for atlas growth, connectivity, topology, and health signals
- `cart embed` for local note embeddings; `cart query` prefers qmd, then embeddings, then built-in FTS

**Operational state + temporal truth:**
- `cart operating-truth` for active work, open decisions, commitments, next steps, and external owners
- `cart daily-brief` now leads with operating truth instead of burying it in narrative summary
- `cart supersede`, `cart history`, `cart conflicts`, and `cart stale` for temporal truth review
- Temporal note fields: `valid_from`, `valid_to`, `supersedes`, `superseded_by`, `is_current`

**Guardrails + lifecycle:**
- `cart delete` previews blast radius before delete/archive, then cleans index state and note links
- `cart query --route` routes across operating-truth/profile/graph/corpus shelves and merges with RRF
- `cart guardrails scan|status|enable|disable`
- Write-time guardrails reject obvious secrets, flag stack traces, and warn on large raw code or duplicate notes

**Temporal pattern detection:**
- `cart temporal-patterns` detects cross-dimensional correlations across the atlas: does social isolation predict longer recovery? Do connection events feed creative output 2-3 days later? Does operating-truth churn predict state drops?
- Pure Python — Pearson correlation + permutation significance testing, no scipy needed
- Reads from mapsOS state transitions, wire activity timestamps, session frequency, daily note data, and access patterns
- Output is pattern reports (not interventions) — the data surfaces, the human decides
- `cart daily-brief --temporal` and `cart therapy review --temporal` for integration

**Session import:**
- Claude Code, Hermes, Codex — deduped, idempotent
- External: ChatGPT and Claude.ai conversation exports
- Sessions link to projects, day notes, and agents — not auto-linked to people

---

## Current status

**Phase 5 is live.** Profiles, discover-first onboarding, trace mode, wire provenance, graph server APIs, temporal pattern detection, plugin adapters, operational truth, temporal truth, routed queries, and guardrails are all shipped and working.

```text
session → export → cart ingest → atlas update → operating truth → emotional wires → daily brief → therapy detection → next session
```

### Implemented

**Core:**
- Atlas initialization (`cart init`)
- Markdown notes with YAML frontmatter
- SQLite indexing for full-text search
- Block insertion, addressing, and transclusion
- Task CRUD with priorities and project linking
- Plugin system (JSON stdin/stdout)
- Shell completion for Bash, Zsh, Fish

**Session + Import:**
- Session import: Claude Code, Hermes, Codex (deduped)
- External import: ChatGPT, Claude.ai exports
- Plain-language atlas search with qmd hybrid retrieval or local embedding fallback
- Daily brief generation

**Semantic wiring + Emotional topology:**
- File-backed semantic wires via `cart wire ...` with full emotional predicates
- Wires indexed for traversal, emotional querying, and temporal versioning
- `cart wire emotional-summary`, `cart wire query --avoidance-risk high`

**Visual graph:**
- JSON and HTML export with full emotional metadata
- Live local serving with background daemon support
- Offline Firefox-safe rendering
- Theme system with auto-loaded atlas-local skins
- Built-in `Atlas Graph` and `Astral Survey` presets now carry explicit v0.5 theme metadata markers for template compatibility
- Graph workspace actions can add wires, edit predicate/weight, mark reviewed, delete wires, run trace, and accept discover candidates back into Markdown files

**Graph-native tooling:**
- `cart trace`, `cart walk`, `cart discover`, `cart embed`, `cart stats`
- Discover proposals can be reviewed interactively or accepted back into note files as inline wires
- Auto-embed-on-write is configurable; embeddings stay local in the SQLite cache

**Profiles + provenance:**
- Built-in `default` and `emotional-topology` profiles
- `cart profile apply` auto-runs a fresh discover pass after switching vocabularies
- Wires now carry weight, author, method, review state, review duration, confidence, and note metadata
- `cart wire review` surfaces pending human review work

**Operational truth + temporal truth:**
- `cart operating-truth` shelf for active work, open decisions, commitments, next steps, external owners
- `cart daily-brief` now leads with operating truth
- `cart supersede`, `cart history`, `cart conflicts`, `cart stale`
- mapsOS export ingest can extract goals, intentions, and decision-shaped vents into operating truth

**Lifecycle + query control:**
- `cart delete` with impact preview, archive mode, and reference cleanup
- `cart query --route` across operating-truth/profile/graph/corpus shelves
- Query/open access events are recorded so temporal-pattern analysis can learn from actual atlas usage
- `cart guardrails` for secret rejection, stack-trace flagging, duplicate warnings, and atlas hygiene

**Temporal pattern detection:**
- `cart temporal-patterns` for cross-dimensional correlation detection across mapsOS state, wire activity, session frequency, daily note data, and atlas access patterns
- Pattern reports (not interventions) — significant correlations surfaced, human decides what to do
- `cart temporal-patterns --write` writes timestamped reports into `ref/temporal-patterns/`
- `cart daily-brief --temporal` and `cart therapy review --temporal` for integration

**Therapy:**
- Pattern detection and counter-evidence queries
- Intervention log with effectiveness tracking
- Configurable per-user

**Operational:**
- mapsOS bridge: state tracking correlates with emotional topology
- CLI health + JSON surfaces: `cart doctor`, `cart status --json`, `cart sessions recent --json`
- Working set via `cart working-set` for role-scoped temporary memory
- Textual atlas TUI

### in progress

- Graph grouping by folder structure
- Temporal versioning of emotional predicates
- Cross-graph queries
- Concurrent write protection under heavier multi-agent load
- Model-backed summary backends
- Deeper mapsOS task write-back

---

## Atlas shape

```text
~/atlas/
├── .cartographer/
│   ├── config.toml
│   ├── plugins/
│   ├── templates/
│   ├── hooks/
│   ├── exports/             # graph HTML/JSON exports
│   ├── index.db             # SQLite index + embeddings + operating truth
│   └── worklog.db
├── index.md
├── daily/
├── projects/
├── agents/
│   ├── claude/sessions/
│   ├── hermes/sessions/
│   └── codex/sessions/
├── entities/
├── tasks/
├── ref/                     # reference docs, specs, analysis
├── readings/                # divination readings + renders
├── shared/                  # cross-agent resources
│   ├── SHARED_CONTEXT.md    # agent-independent file map (all agents read this first)
│   └── skills → ~/.hermes/skills/  # symlink to canonical skills
└── themes/                  # atlas-local graph skins
```

---

## Install

```zsh
pipx install git+https://github.com/nosleepcassette/cartographer.git
```

Or from checkout:

```zsh
cd ~/dev/cartographer
pipx install -e .
```

Three equivalent entrypoints: `cart`, `cartog`, `cartographer`.

### shell completion

```zsh
cart completion zsh > ~/.zfunc/_cart
autoload -Uz compinit && compinit
```

```bash
cart completion bash > ~/.local/share/bash-completion/completions/cart
cart completion fish > ~/.config/fish/completions/cart.fish
```

---

## Quickstart

```zsh
cart init
cart status
cart doctor
cart operating-truth set active_work "shipping cartographer v0.3"
cart query "what am I working on" --route
cart query "what did we learn about this project"
cart stats
cart daily-brief
cart tui
cart session-import claude --latest 1
cart graph --serve --daemon
```

---

## Core commands

### atlas + status

```zsh
cart init [path]
cart status
cart doctor
cart status --json
cart sessions recent --json
cart tui
cart backup
cart index rebuild
```

### tui

```zsh
cart tui
```

- `j` / `k` — move through visible notes
- `[` / `]` — jump between top-level sections
- `1`-`5` — jump directly to visible section slots
- `c` — collapse / expand current section
- `/` — filter the graph
- `t` — toggle task overlay
- `m` — hand off into mapsOS

### notes

```zsh
cart new project "Project Alpha"
cart new daily 2026-04-17
printf 'Context from stdin.\n' | cart new note "Inbox capture" --from-stdin
cart ls --type project
cart show project-alpha
cart edit project-alpha
```

### query + backlinks

```zsh
cart query 'session drift in hermetica'   # plain language; prefers qmd, then local embeddings
cart query 'what am I working on' --route
cart query 'what did we discuss yesterday' --route
cart query 'grungler relationship status' --route --json
cart query 'tag:project status:active'
cart query 'modified:>2026-04-01'
cart query 'text:"release checklist"'
cart query --json 'type:agent-log'
cart backlinks project-alpha
```

### enhanced search: qmd + local embeddings + routed shelves

```zsh
npm install -g @tobilu/qmd
cart qmd bootstrap
cart embed
cart query 'what do we know about this architecture decision'
```

`cart query` now follows a simple local-first stack: qmd hybrid retrieval when configured, embedding-backed semantic ranking when embeddings exist, then built-in SQLite/FTS. `cart query --route` is the shelf-aware path: it analyzes intent, routes across operating-truth/profile/graph/corpus shelves, merges with reciprocal-rank fusion, and packs the smallest useful evidence set. You can precompute embeddings with `cart embed`; auto-embed-on-write is also configurable in `~/atlas/.cartographer/config.toml`.

### tasks

```zsh
cart todo list
cart todo add "ship the thing" -p P0 --project project-alpha
cart todo done t123abc
cart todo query 'priority:P0 status:open'
```

### session import

```zsh
cart session-import claude --latest 5
cart session-import hermes --all
cart sessions recent
cart sessions recent --agent hermes --json
```

### working set

```zsh
cart working-set add "candidate" --role intake --scope therapy
cart working-set list --json
cart working-set gc
```

### operating truth + temporal truth

```zsh
cart operating-truth
cart operating-truth set active_work "shipping v0.3"
cart operating-truth add open_decision "fastembed or sentence-transformers"
cart operating-truth add commitment "ship cartographer v0.3 by May 15"
cart operating-truth add next_step "write temporal truth docs"
cart operating-truth history
cart supersede old-grungler-status new-grungler-status
cart history new-grungler-status
cart conflicts
cart stale
```

`operating-truth` is the short shelf for what matters right now. `active_work` is singleton; setting a new one archives the old one. Temporal truth tracks when facts stop being current and what replaces them, so you can review staleness and contradictions instead of pretending the latest note is always the truth.

### therapy

```zsh
cart therapy export
cart therapy export --format json
cart therapy review --json
cart therapy review --write ~/atlas/notes/therapy/reviews/today.md
cart therapy counter-evidence "I wasn't giving them what they needed"
```

`therapy review` compiles therapy working-set entries, recent sessions, open tasks, and the latest mapsOS export, then runs the therapy plugin. Writes a note only when `--write` is used.

### semantic wires

```zsh
cart wire predicates
cart wire add note-a note-b --predicate supports
cart wire add person-a user --relationship relates_to_person \
  --emotional-valence mixed --energy-impact energizing \
  --avoidance-risk high --growth-edge --current-state building
cart wire ls note-a --json
cart wire query --avoidance-risk high --json
cart wire emotional-summary person-a
cart wire traverse note-a --depth 2
cart wire doctor
cart wire gc
```

Wires are stored inline as HTML comments - invisible in any Markdown renderer, machine-readable, file-native. `cart wire add` is idempotent: rerunning the same source/target/predicate updates the comment instead of duplicating it.

### graph-native tools

```zsh
cart trace project-alpha
cart trace project-alpha --depth 4 --json
cart walk project-alpha --depth 2
cart walk project-alpha --avoidance-only high
cart discover
cart discover --interactive
cart discover --export
cart discover --accept
cart profile list
cart profile apply emotional-topology
cart embed
cart stats
```

`trace` surfaces likely-relevant notes through the wire graph. `walk` traverses the neighborhood directly. `discover` proposes unwired-but-similar note pairs and can export, review, or accept them back into notes. `stats` now includes provenance: human-created wires, reviewed agent suggestions, pending review count, and average review duration.

### graph export + live server

```zsh
cart graph
cart graph --export ~/tmp/graph-export.json
cart graph --format html
cart graph --format html --open
cart graph --serve
cart graph --serve --daemon
cart graph --serve --daemon --port 8080
cart graph --status-daemon
cart graph --stop-daemon
```

HTML output is a self-contained, offline-safe visual graph. Theme and privacy settings come from `~/atlas/.cartographer/config.toml`:

```toml
[graph]
theme_preset = "astral"
always_visible_people = ["maps"]

[graph.privacy]
mode = "off"
never_redact_ids = ["maps"]
person_order = ["maps", "grungler", "chungus"]
```

Atlas-local theme skins live in `~/atlas/themes/*.js` and are auto-loaded. The graph sidebar theme picker switches between them at runtime.

`cart graph --serve` turns the graph into a live local workspace: it polls for atlas changes, reloads when the underlying graph regenerates, fetches the active predicate palette from the profile, supports trace animation and discover overlays, and lets you review/edit/delete wires directly back into the Markdown comments. `--daemon` sends it to the background, writes a per-port PID file and log under `~/atlas/.cartographer/`, and frees the terminal immediately. Use the same `--port` with `--status-daemon` or `--stop-daemon` when you're managing a nondefault daemon.

### deletion + guardrails

```zsh
cart delete project-alpha
cart delete project-alpha --archive --force
cart delete project-alpha --no-cascade --force
cart guardrails status
cart guardrails scan
cart guardrails disable
```

`cart delete` is not just `rm`: it previews wires, block refs, frontmatter links, embeddings, and operating-truth references before deleting or archiving. Guardrails run on write and are there to keep the atlas from turning into a credential dump or crash-log graveyard.

### temporal patterns

```zsh
cart temporal-patterns
cart temporal-patterns --signal state
cart temporal-patterns --lead 72 --min-n 5
cart temporal-patterns --write
cart temporal-patterns --json
cart daily-brief --temporal
cart therapy review --temporal
```

`cart temporal-patterns` detects cross-dimensional temporal correlations across your atlas. It reads mapsOS state transitions, wire activity timestamps, session frequency, daily note data, and access patterns — then checks whether events in one signal predict events in another (with configurable lead time and permutation significance testing). The output is pattern reports, not interventions: "social isolation in the 48h before a state drop correlates with longer recovery (r=0.72, p=0.003)." The data surfaces. You decide.

### external import

```zsh
cart import chatgpt ~/Downloads/conversations.json
cart import claude-web ~/Downloads/conversations.json
```

Both support `--latest N` and `--force`. All imports are deduped.

### mapsOS bridge

```zsh
cart mapsos ingest-exports --latest
cart mapsos patterns --field state
cart daily-brief
```

Inside the TUIs: `cart tui` → `m` launches mapsOS. mapsOS → `C` launches cartographer. Quitting mapsOS ingests the latest export when `cart` is available. That ingest can also populate operating truth from goals, intentions, and decision-shaped vents.

---

## Atlas loop

```text
agent session
  → session import
  → atlas note + links + tasks + learnings
  → mapsOS export ingested as qualitative state
  → daily brief
  → next session starts from real memory instead of zero
```

Context windows close. The graph stays.

---

## Agent skills

For AI agents working with cartographer/atlas, we publish skill definitions:

| Skill | Description | Gist |
|-------|-------------|------|
| **Cartographer Init** | Initialize atlas directory, install CLI, run status check | [View Gist](https://gist.github.com/nosleepcassette/96f39bb9637dba100a9f4e4f66900f3e) |
| **Cartographer Query** | Search syntax for tag, status, type, links, text queries | [View Gist](https://gist.github.com/nosleepcassette/05374920e0c2f976f02999532208df1f) |
| **Cartographer Summary** | Generate and maintain MASTER_SUMMARY.md from context sources | [View Gist](https://gist.github.com/nosleepcassette/e1f9a62546752bebd7afca62a9023f83) |
| **Cartographer Todo** | Task management with P0-P3 priorities, project linking | [View Gist](https://gist.github.com/nosleepcassette/7983da390c33fb91ad8d904e55de671c) |

To use in Hermes: place in `~/.hermes/skills/cartographer*/`

To use in Claude Code: add to CLAUDE.md or import via MCP.

---

## Developers

See `DEVELOPERS.md` for the full extension surface. Short version:

**The plugin API is 30 seconds to learn:**

Any executable that reads JSON on stdin and writes JSON on stdout is a plugin. Drop it in `.cartographer/plugins/`. Run with `cart plugin run my-plugin`. Python, shell, Rust, Lua — anything. If you want stable aliases/metadata, add a sibling `.cartographer/plugins/manifest.json` with `description`, `commands`, and `executable` entries.

```json
// stdin
{ "command": "my-plugin", "args": {}, "notes": [{"id": "project-alpha", "content": "..."}] }

// stdout
{ "output": "result text", "writes": [{"path": "agents/mine/output.md", "content": "..."}], "errors": [] }
```

**What you can build on top of this:**

The atlas is a local-first knowledge graph where agents and humans write to the same files. That's a substrate, not an app. The therapy plugin is one example of what gets built on it. There's a lot more that hasn't been built yet:

- A research assistant that links every paper to the claims that cite it, tracks which sources agree and which contradict, and answers "what does the literature say about X" against your own reading history
- A shared engineering atlas where every agent on a team writes session logs to the same knowledge graph — `cart query "what did any agent learn about this component"` becomes a real command
- A client management layer for a therapist or coach — session notes accumulate into entity profiles, pattern detection runs across clients, everything local, no cloud, no HIPAA exposure
- A mapsOS profile for a different neurotype — the state vocabulary, arc definitions, capacity thresholds, and track definitions are all configurable. A bipolar energy tracking profile looks different from an ADHD hyperfocus profile. Same substrate.
- A domain-specific atlas stack for ops teams — incident reports, runbooks, post-mortems, architectural decisions all in one graph. Backlinks show which runbook sections were consulted during which incidents. Agents write to the same files the team reads.

**Extension points:**

| surface | how |
|---------|-----|
| Plugins | executable in `.cartographer/plugins/` |
| Templates | Jinja2 in `.cartographer/jinja/` |
| Hooks | shell scripts in `.cartographer/hooks/` |
| mapsOS tracks | `tracks:` in `~/.maps_os_config.yaml` |
| mapsOS state vocab | `state.tags:` in config |
| Agent adapters | `cart session-import` reads any agent writing the ECC session format |
| Graph skins | `~/atlas/themes/*.js` — auto-loaded, theme picker in graph sidebar, `template.js` now marks v0.5 compliance explicitly |

This was built for one brain and configured for that brain's specific needs. The whole point is that you configure it for yours. Come build.

---

## Design rules

1. **Files are the API.** Delete cartographer and your files still make sense.
2. **Structure lives in frontmatter, not migrations.**
3. **Git is the database.**
4. **Agents are first-class writers.**
5. **Plugins are just programs.** Anything that reads stdin and writes stdout JSON can join.
6. **Blocks matter.** Paragraph-level addressability is not optional.
7. **Imports are idempotent.** Re-running never creates duplicates.

---

## Note model

```markdown
---
id: project-alpha
title: Project Alpha
type: project
status: active
tags: [automation, python]
links: [team-notes, launch-plan]
auto_blocks: true
created: 2026-04-17
modified: 2026-04-17
---

# Project Alpha

<!-- cart:block id="b001" -->
The release checklist is blocked on review.
<!-- /cart:block -->
```

Block refs: `[[project-alpha#b001]]`.

---

## Plugin contract

Plugins live in `.cartographer/plugins/`. They're just executables.

**Input (stdin):**
```json
{
  "command": "summarize",
  "args": {"max_words": 300},
  "notes": [{"id": "project-alpha", "content": "..."}]
}
```

**Output (stdout):**
```json
{
  "output": "...",
  "writes": [{"path": "agents/hermes/SUMMARY.md", "content": "..."}],
  "errors": []
}
```

Machine-readable CLI surfaces include `schema_version` and `surface` fields for bridge client validation.

---

## Integrations

### Obsidian

Point Obsidian at `~/atlas`. `.cartographer/` stays implementation detail. Cart uses standard Markdown plus HTML comment block markers — Obsidian renders these as notes, cart reads them as structured data.

### vimwiki

`cart init` can patch `~/.vimrc` to make the atlas your primary wiki. Skip with:

```zsh
export CARTOGRAPHER_SKIP_VIMWIKI_PATCH=1
```

### hermes

cartographer is the canonical memory layer for Hermes agents:

- `cart session-import hermes --all`
- `cart learn "observation" --topic slug`
- `cart daily-brief` at session start
- Session logs link to projects, days, agents — not to people unless wired intentionally

---

## What this is not

- Not a SaaS notes app
- Not a proprietary memory store
- Not a graph-native editor (though `cart graph --format html` renders one)
- Not pretending the surface area is finished

---

## Repository map

- `SPEC.md` — product spec and locked decisions
- `DEVELOPERS.md` — extension points and developer-facing framing
- `orchestra/` — allowlist-friendly shell wrappers for common cart operations
- `skills/create-skill/SKILL.md` — guided conversation for drafting new Claude skills

---

## license

MIT. See LICENSE.

---

the tape keeps rolling. the server never sleeps.
