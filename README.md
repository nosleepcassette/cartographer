# cartographer

<p align="center">
  <video src="media/cartographer-github-1.25x-render.webm" width="800" autoplay loop muted playsinline></video>
</p>

> Your agents should know how you're actually doing — and remember everything they learn.

Local-first knowledge filesystem and agent memory layer.

Plain Markdown. Git history. Queryable graph. Block-addressable text. Agents and humans write to the same substrate. Nothing is trapped in an app.

---

## There are a hundred agent memory layers. Why use this one?

Vector databases. Hosted memory APIs. Pinecone, Mem0, raw context stuffing, custom RAG pipelines. They all solve the same narrow problem: *getting context into a prompt.* They're mostly invisible, mostly opaque, mostly locked to whoever built them.

cartographer is not a memory layer. It's a **knowledge substrate** that happens to be excellent at agent memory.

**What that means in practice:**

Every conversation your agent has can be imported into a growing atlas of Markdown notes — deduped, linked to projects and day notes, indexed for full-text and semantic search. When the next session starts, `cart daily-brief` seeds it from everything accumulated so far. Context windows close; the graph stays. That's the memory layer part.

But the atlas is also *your* knowledge base. It's where you write. Where your notes live. Where tasks accumulate. Where relationships are modeled. The same files your agent writes to are the same files you read. No parallel universe of embeddings divorced from your actual documents. One substrate, multiple writers.

The graph isn't decorative. Export it as JSON and query it programmatically. Export it as HTML and navigate it interactively — 3D clustered layout, typed semantic wires, emotional topology, theme-switched rendering, privacy modes. The atlas is a living map of a mind (or a project, or a team, or a body of research) and the graph makes that structure visible.

**Why not just use a hosted memory API?**

Because when the service changes its pricing, changes its format, or goes away, your memory goes with it. cartographer is local files and SQLite. Delete cartographer and your notes are still readable Markdown with YAML frontmatter. Git is the database. The SQLite index is a cache that can be rebuilt from scratch at any time. Nothing is trapped.

**Why not just RAG over my existing notes?**

You can do that too — `cart qmd bootstrap` wires in hybrid retrieval over your atlas if you want it. But RAG alone doesn't give you semantic wires between notes, emotional metadata on relationships, block-level transclusion, idempotent session import, or the agent skills and plugin economy built on top. RAG is a search feature. This is a knowledge operating system.

---

## I don't use AI at all. I just use Obsidian, or vimwiki. Why would I care about this?

Fair question. The short answer: cartographer adds structure that Obsidian and vimwiki gestures at but never fully delivers.

**Block transclusion that actually works.** Every paragraph can be addressed by ID: `[[project-alpha#b001]]`. Backlinks tracked automatically. Transclusion rendered in the TUI. Obsidian has a version of this. It requires plugins, breaks on mobile, and the link format isn't portable. Cart's block markers are HTML comments — invisible in any Markdown renderer, machine-readable, file-native.

**Semantic wires, not just links.** A standard `[[link]]` says "these things are related." A wire says *how*: `supports`, `depends_on`, `part_of`, `intensifies_with`, `contradicts`. You can query "what does this project depend on?" or "what contradicts this belief?" and get structured answers. Teachers tracking what approaches worked for a student. Researchers mapping where their sources agree and disagree. Ops teams modeling which runbook sections relate to which incident types. The typed relationship layer is what transforms a note collection into a knowledge graph.

**A TUI built for navigation, not just editing.** `cart tui` gives you section jumps (`[`/`]`), a task overlay (`t`), semantic wire neighborhood view, block transclusion rendering, backlinks, and mapsOS handoff — all in a responsive terminal interface that doesn't require Electron.

**Compatible with what you already use.** Point Obsidian at `~/atlas`. `.cartographer/` stays implementation detail. Cart uses standard Markdown plus HTML comment block markers. `cart init` can patch vimwiki config to make the atlas your primary wiki.

**CLI-native and composable.** Every operation has a `--json` surface. `cart query 'type:project tag:active'` pipes into anything. If your workflow is already built around the terminal, cartographer extends it rather than replacing it with another GUI.

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
- **Optional semantic search without lock-in.** If `qmd` is installed, plain-language `cart query` uses hybrid retrieval over the atlas. If not, cart stays on its built-in SQLite/FTS path. The query interface is the same either way.
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
- Self-contained HTML graph — offline-safe, single exported file
- Deterministic 3D clustered layout
- Emotional-valence node coloring, avoidance-aware node sizing
- Theme system: `baseline`, `astral` (hand-drawn in-scene celestial sigils, alchemical wire labels), plus auto-loaded atlas-local themes
- Theme picker in graph sidebar — switch without re-export
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

**Session import:**
- Claude Code, Hermes, Codex — deduped, idempotent
- External: ChatGPT and Claude.ai conversation exports
- Sessions link to projects, day notes, and agents — not auto-linked to people

---

## Current status

**Phase 5 is live.** Emotional topology, therapy integration, the visual graph, and the atlas TUI are all shipped and working.

```text
session → export → cart ingest → atlas update → emotional wires → daily brief → therapy detection → next session
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
- Optional qmd-backed plain-language atlas search
- Daily brief generation

**Semantic wiring + Emotional topology:**
- File-backed semantic wires via `cart wire ...` with full emotional predicates
- Wires indexed for traversal, emotional querying, and temporal versioning
- `cart wire emotional-summary`, `cart wire query --avoidance-risk high`

**Visual graph:**
- JSON and HTML export with full emotional metadata
- Offline Firefox-safe rendering
- Theme system with auto-loaded atlas-local skins

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
│   ├── index.db        # SQLite index, NOT the source of truth
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
├── themes/             # atlas-local graph skins
└── ref/
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
cart daily-brief
cart tui
cart session-import claude --latest 1
cart graph --format html --open
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
cart ls --type project
cart show project-alpha
cart edit project-alpha
```

### query + backlinks

```zsh
cart query 'session drift in hermetica'   # plain language; uses qmd when configured
cart query 'tag:project status:active'
cart query 'modified:>2026-04-01'
cart query 'text:"release checklist"'
cart query --json 'type:agent-log'
cart backlinks project-alpha
```

### optional enhanced search with qmd

```zsh
npm install -g @tobilu/qmd
cart qmd bootstrap
cart query 'what do we know about this architecture decision'
```

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

Wires are stored inline as HTML comments — invisible in any Markdown renderer, machine-readable, file-native. `cart wire add` is idempotent: rerunning the same source/target/predicate updates the comment instead of duplicating it.

### graph export

```zsh
cart graph --export
cart graph --format html
cart graph --format html --open
```

HTML output is a self-contained, offline-safe visual graph. Theme and privacy settings come from `~/atlas/.cartographer/config.toml`:

```toml
[graph]
theme_preset = "astral"
always_visible_people = ["maps"]

[graph.privacy]
mode = "off"
never_redact_ids = ["maps"]
person_order = ["maps", "person-b", "person-c"]
```

Atlas-local theme skins live in `~/atlas/themes/*.js` and are auto-loaded. The graph sidebar theme picker switches between them at runtime.

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

Inside the TUIs: `cart tui` → `m` launches mapsOS. `maps` → `C` launches cartographer. Quitting mapsOS ingests the latest export when `cart` is available.

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

Any executable that reads JSON on stdin and writes JSON on stdout is a plugin. Drop it in `.cartographer/plugins/`. Run with `cart plugin run my-plugin`. Python, shell, Rust, Lua — anything.

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
| Graph skins | `~/atlas/themes/*.js` — auto-loaded, theme picker in graph sidebar |

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
