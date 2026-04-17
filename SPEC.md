# cartographer — SPEC
# maps · cassette.help · MIT
# generated: 2026-04-16
# status: decisions locked · full handover in HANDOVER.md

---

## naming

**cartographer** — the tool that maps your knowledge.
**atlas** — the directory it maps. (`~/atlas` on sextile.)

CLI commands: `cart`, `cartog`, `cartographer` — all synonyms, all valid.
The atlas directory is always `~/atlas` unless overridden in config.

---

## what this is

**cartographer** is a local-first knowledge filesystem and agent memory layer.

Plain files. Git-native. Queryable. Scriptable. Block-addressable.
Integrates with vim/vimwiki, Obsidian, and AI agents (Hermes, Codex, Claude).
Designed to become the substrate that mapsOS, agents, and future tools build on.

Long-term vision: the CLI equivalent of Notion + LogSeq + Todoist, built on mapsOS,
operable from terminal, extensible by plugins, owned entirely by the user.

---

## the naming logic (worth keeping)

atlas
noun — at·las ˈat-ləs
1. A Titan forced by Zeus to support the heavens on his shoulders.
2. One who bears a heavy burden.
3. A bound collection of maps, charts, or plates.
4. The first vertebra of the neck — the one that holds the head up.
5. (pl. atlantes) A male figure used as a supporting column.

All of these are atlas. atlas is all of these.
The cartographer maps it.

---

## design philosophy

1. **Files are the API.** cartographer never owns your data. Delete it — your files remain valid Markdown.
2. **Structure is in frontmatter, not schema.** YAML frontmatter. Schema evolves per-project. No migrations.
3. **Git is the database.** Every write can be a commit. History is free. Sync is `git push`.
4. **Scripts are plugins.** Any executable that reads stdin / writes stdout is a valid plugin. Shell, Python, Lua — all valid.
5. **Agents are first-class writers.** Hermes and Codex write to the same files vim reads. No special API.
6. **Query should feel like grep but think like a graph.**
7. **Blocks are addressable.** Every paragraph is a node. `[[file#block-id]]` works. LogSeq-style, not LogSeq-dependent.

---

## locked decisions

| question | answer |
|---|---|
| CLI name | `cart` / `cartog` / `cartographer` |
| Atlas root | `~/atlas` (configurable; also accepts `~/knowledge` etc.) |
| Obsidian vault | `~/vaults` — detect on init, coexist |
| Block references | YES — core feature, phase 2 |
| Agent output format | Both prose + structured fields, autolinked |
| Summary synthesis | Hermes by default, configurable (Ollama / Claude / manual) |
| Plugin languages | Python + Lua both supported |
| Daily notes | Bidirectional mapsOS integration, user configurable, default bidirectional, easy rollback |
| Distribution | Closed source now, public project later |
| Sync | Git minimum, configurable (Tailscale, rsync, etc.) |
| Ship style | Move fast and break things. No test suite in phase 1. |
| mapsOS | Make configurable with same plugin/scripting system in parallel scope |

---

## directory structure

```
~/atlas/                         ← the atlas (cartographer's root)
├── .cartographer/
│   ├── config.toml              ← all settings
│   ├── plugins/                 ← executable plugins (Python/Lua/shell)
│   ├── templates/               ← Jinja2 note templates
│   ├── hooks/                   ← pre/post-write hooks
│   ├── index.db                 ← SQLite index (auto-maintained)
│   └── worklog.db               ← cartographer's own task + session tracking
├── index.md                     ← root note (\ww in vimwiki)
├── daily/
│   └── 2026-04-16.md
├── projects/
│   └── hopeagent.md
├── agents/
│   ├── hermes/
│   │   ├── SUMMARY.md           ← rolling master summary
│   │   ├── learnings/
│   │   │   ├── identity.md
│   │   │   ├── preferences.md
│   │   │   └── patterns.md
│   │   └── sessions/
│   │       └── 2026-04-16_001.md
│   └── codex/
├── entities/                    ← named entities: people, projects, tools
│   ├── chris.md
│   └── nhi.md
├── tasks/                       ← todoist-style task files
│   └── active.md
└── ref/                         ← reference material
```

---

## note format

```markdown
---
id: hopeagent
title: HopeAgent
type: project
status: active
tags: [nhi, twilio, python]
links: [chris, nhi-org, twilio-backend]
created: 2026-03-01
modified: 2026-04-16
---

# HopeAgent

Twilio-based AI phone system for incarcerated people.

<!-- cart:block id="b001" -->
Conversational loop is the P0 gap. Blocked on Chris voicemail content.
<!-- /cart:block -->

<!-- cart:block id="b002" -->
Backend is running at ~/dev/hopeagent/backend/. FastAPI + SQLite.
<!-- /cart:block -->
```

Block IDs are auto-generated on write if absent. Never change once set.
`[[hopeagent#b001]]` references the exact block. Backlinks track this.

---

## block reference system

The core differentiator from standard Markdown wikis.

**Block ID format:** `<!-- cart:block id="XXXX" -->` ... `<!-- /cart:block -->`
Auto-inserted by `cart new` and `cart edit`. Invisible in Obsidian (HTML comments).

**Reference syntax:** `[[note-id#block-id]]`
At index time: cartographer resolves these and stores in `index.db`.
At query time: `cart backlinks --block b001` returns every note referencing that block.

**Transclusion (phase 2):** `![[note-id#block-id]]` embeds the block content inline.
Rendered by `cart export` and the eventual TUI view.

---

## query language

```sh
cart query 'tag:project status:active'
cart query 'links:chris'
cart query 'modified:>2026-04-01 type:log'
cart query 'text:"HopeAgent"'
cart query 'block-ref:hopeagent#b001'      ← who references this block
cart query 'type:task status:open'
```

Returns file paths. Composable:
```sh
cart query 'tag:session agent:hermes' | cart summarize --model hermes
cart query 'type:project status:active' | xargs cart export --format=obsidian
```

---

## task system (todoist layer)

Tasks live in Markdown files as structured frontmatter blocks.
cartographer indexes them. `cart todo` is the CLI interface.

```markdown
<!-- cart:block id="t001" type="task" -->
- [ ] finish HopeAgent conversational loop
  status: open
  priority: P0
  project: hopeagent
  due: 2026-04-20
<!-- /cart:block -->
```

```sh
cart todo list                       ← open tasks, sorted by priority
cart todo add "task text" -p P1      ← add task to tasks/active.md
cart todo done t001                  ← mark complete
cart todo query 'project:hopeagent'  ← filter
```

Bidirectional with mapsOS: mapsOS arc/task exports land here.
Can pipe to Taskwarrior export format (phase 3).

---

## vimwiki integration

**Backup first (always run this before any vimrc change):**
```sh
cp ~/.vimrc ~/.vimrc.bak.cart.$(date +%Y%m%d_%H%M%S)
cp -r ~/.vim ~/.vim.bak.cart.$(date +%Y%m%d_%H%M%S)
cp -r ~/vimwiki ~/vimwiki.bak.cart.$(date +%Y%m%d_%H%M%S)
cp -r ~/writing ~/writing.bak.cart.$(date +%Y%m%d_%H%M%S)
cp -r ~/therapy ~/therapy.bak.cart.$(date +%Y%m%d_%H%M%S)
```

**Vimrc change — one block, nothing else:**
```viml
""" cartographer — atlas wiki (primary)
let wiki_atlas = {}
let wiki_atlas.path = '~/atlas/'
let wiki_atlas.ext = '.md'
let wiki_atlas.syntax = 'markdown'
let wiki_atlas.auto_tags = 1
let g:vimwiki_list = [wiki_atlas, wiki_1, wiki_2, wiki_3]
```

Effect:
- `\ww` / `\wi` → `~/atlas/index.md`
- `2\ww` → `~/vimwiki/` (unchanged)
- `3\ww` → `~/writing/` (unchanged)
- `4\ww` → `~/therapy/` (was wiki_3, now wiki_4 — update diary autocmd line)

**Diary autocmd fix** (find and update this line):
```viml
" Before:
au BufNewFile ~/therapy/diary/*.wiki ...
" After: no change needed — path hasn't changed, just index shifted
" BUT: if you use \w\w for diary, that's now \4w\w. Test before relying on it.
```

---

## obsidian integration

`~/vaults/` is detected on `cart init`. cartographer writes Obsidian-compatible files.
Block IDs as HTML comments are invisible to Obsidian. `[[links]]` resolve natively.

`cart obsidian-sync` — optional:
- Detects vault at `~/vaults/` (or configured path)
- Generates property index file Obsidian can use for dataview queries
- Does NOT move or copy files (atlas IS the vault if you open it in Obsidian)

Obsidian can open `~/atlas/` directly as a vault. `.cartographer/` auto-ignored.

---

## plugin system

Plugins: executables in `.cartographer/plugins/`. Stdin/stdout JSON contract.

```
.cartographer/plugins/
├── summarize          ← notes → summary (Python default)
├── daily-brief        ← yesterday → today brief
├── agent-ingest       ← session JSON → atlas notes
├── tag-cluster        ← suggest tag consolidation
└── todo-sync          ← bidirectional mapsOS tasks
```

Any language. Python and Lua have built-in runner support.
Lua plugins get a `cartographer` table injected with index/write/query helpers.

Plugin stdin:
```json
{
  "command": "summarize",
  "args": { "max_words": 300, "model": "hermes" },
  "notes": [{ "id": "...", "content": "...", "frontmatter": {} }]
}
```

Plugin stdout:
```json
{
  "output": "...",
  "writes": [{ "path": "agents/hermes/SUMMARY.md", "content": "..." }],
  "errors": []
}
```

---

## hermes learning system

After each Hermes session, `cart agent-ingest hermes session.json` runs.

Produces:
1. `agents/hermes/sessions/YYYY-MM-DD_NNN.md` — raw session log
2. `agents/hermes/learnings/TOPIC.md` — appended learnings with frontmatter:
   ```yaml
   confidence: 0.85
   source: hermes-session-2026-04-16_001
   date: 2026-04-16
   confirmed: 0
   ```
3. `agents/hermes/SUMMARY.md` — re-synthesized by Hermes (or Ollama) after ingest
4. `entities/ENTITY.md` — updated with session backlink

Confidence decay: learnings older than 30 days with 0 confirmations decay by 0.05/week.
`cart agent-gc --threshold 0.3` prunes below threshold.

---

## mapsOS integration (parallel scope)

mapsOS gets the same plugin/scripting system as cartographer.

- `mapsOS/config.toml` — TOML config with plugin hooks
- `mapsOS/plugins/` — same stdin/stdout contract
- Bidirectional daily note sync: mapsOS session → `~/atlas/daily/YYYY-MM-DD.md`
- mapsOS arc exports → `~/atlas/tasks/` as task blocks
- State snapshots → `~/atlas/agents/mapsOS/YYYY-MM-DD.md`

This is a parallel track, not a dependency. cartographer phase 1 does not require mapsOS changes.

---

## cartographer's own worklog

cartographer tracks its own operations in `.cartographer/worklog.db`.

```sh
cart worklog status         ← pending tasks, last session
cart worklog complete ID    ← mark done with result
cart worklog log "note"     ← append to current session
```

Schema mirrors hermes worklog protocol. Hermes can read/write it directly.

---

## CLI full reference

```sh
# Init & setup
cart init [path]               ← init atlas in directory (default ~/atlas)
cart status                    ← index age, note count, pending tasks, sync status
cart backup                    ← tar.gz to ~/.cartographer_backups/

# Notes
cart new [type] [title]        ← create from template, auto-assign block IDs
cart open [id]                 ← open in $EDITOR
cart edit [id]                 ← open + re-index on close

# Query
cart query [expr]              ← search index
cart backlinks [id]            ← notes linking to id
cart backlinks --block [id#b]  ← notes referencing specific block

# Tasks
cart todo list                 ← open tasks
cart todo add "text" -p P0     ← add task
cart todo done [id]            ← complete task
cart todo query [expr]         ← filter tasks

# Agents
cart learn "fact" --topic X    ← write learning entry
cart agent-ingest [file]       ← ingest session JSON
cart agent-gc                  ← garbage collect stale learnings
cart summarize [query]         ← pipe notes through summarize plugin

# Integrations
cart vimwiki-sync              ← regenerate atlas index.md for vimwiki
cart obsidian-sync             ← generate Obsidian-compatible property index

# Plugins
cart plugin run [name] [args]  ← run plugin manually
cart plugin list               ← list available plugins

# Index
cart index rebuild             ← full rebuild from files
cart index status              ← index freshness

# Worklog
cart worklog status
cart worklog complete [id] --result "..."
cart worklog log "note"
```

---

## implementation stack

- **Language:** Python 3.11
- **Index + worklog:** SQLite (stdlib sqlite3)
- **Config:** TOML (stdlib tomllib)
- **CLI:** Click (subcommands, help text, composability)
- **Templates:** Jinja2
- **Lua runtime:** lupa (Python/Lua bridge, optional dep, graceful fallback)
- **Packaging:** pyproject.toml → pipx install

---

## phased build plan

### phase 1 — core (ship fast)
- `cart init` → creates `~/atlas/` + `.cartographer/config.toml`
- Vimrc backup + patch
- Obsidian vault detection at `~/vaults/`
- Note creation with auto block IDs (`cart new`)
- SQLite index builder (frontmatter + full text, no blocks yet)
- `cart query` basic syntax
- `cart backlinks` (page level)
- `cart status`, `cart backup`
- `cart todo` basic CRUD
- `cart worklog` basic ops

### phase 2 — blocks + plugins
- Block ID insertion + index
- `[[note#block]]` reference resolution
- Block backlinks
- Plugin runner (Python + shell, Lua optional)
- Hook system
- `cart agent-ingest`, `cart learn`, `cart agent-gc`
- Built-in plugins: `summarize`, `daily-brief`, `agent-ingest`

### phase 3 — synthesis + mapsOS
- Hermes SUMMARY.md auto-synthesis
- Confidence decay + gc
- mapsOS plugin system port
- Bidirectional daily note sync
- `cart obsidian-sync`
- Transclusion in `cart export`

### phase 4 — ecosystem
- `cart graph` (ASCII / graphviz dot)
- Template variable system
- `cart publish` (static site export)
- Lua plugin support (lupa)
- Taskwarrior export

---

---

## mapsOS extensibility (parallel scope)

### what changes

mapsOS gets the same plugin/config/scripting model as cartographer.
Goal: users customize their own life OS — states, arcs, intentions, briefing logic —
and share those configs as dotfiles. A community forms around `~/.mapsOS/` the same
way one forms around `~/.config/`.

This is NOT a rewrite. mapsOS internals stay. This adds a config layer on top.

### user-configurable schema

Currently states, arcs, body/mind/spirit dimensions are hardcoded.
Move them to `~/.mapsOS/schema.toml`:

```toml
[states]
surviving  = "minimal function, getting through"
stable     = "neutral baseline"
grounded   = "anchored, present"
thriving   = "genuine forward momentum"
tender     = "emotionally soft, post-connection warmth"
grieving   = "loss-adjacent"
manic      = "elevated, possibly unsustainable"
depleted   = "tank empty"
flooded    = "emotionally overwhelmed"
# users add their own:
building   = "deep focus, making something real"
feral      = "chaotic good, everything is on fire but it's fine"

[arcs]
# user-defined narrative arcs tracked across sessions
housing    = { label = "housing stability", emoji = "🏠" }
income     = { label = "income + survival", emoji = "💸" }
nhi        = { label = "NHI / HopeAgent", emoji = "📞" }
voice      = { label = "voice training", emoji = "🎙️" }

[tracks]
body   = ["sleep", "movement", "food", "meds", "pain"]
mind   = ["focus", "flow", "anxiety", "clarity"]
spirit = ["connection", "meaning", "creativity", "grief"]

[intentions]
water    = "hydration"
movement = "physical movement"
meds     = "medications"

[briefing]
penalize_productivity_when = ["surviving", "flooded", "depleted", "grieving"]
skip_arcs_when = ["flooded"]
max_arc_count = 3
```

mapsOS reads at startup. Falls back to hardcoded defaults if absent.
`maps schema edit` opens in `$EDITOR`. `maps schema validate` checks conflicts.

### plugin system (same contract as cartographer)

`~/.mapsOS/plugins/` — stdin/stdout JSON contract identical to cartographer.

Built-in plugins to build (pinned — after cartographer phase 1):

| plugin | what it does |
|---|---|
| `pattern-digest` | weekly pattern summary → cartographer atlas note |
| `arc-tracker` | arc momentum scoring, trend detection |
| `state-forecast` | recent states + context → tomorrow prediction |
| `briefing-custom` | user-defined briefing template renderer |
| `atlas-sync` | session → `~/atlas/daily/YYYY-MM-DD.md` |
| `intention-coach` | missed intention patterns → gentle intervention |
| `crisis-detect` | sustained low states → surface resources, disable productivity nags |
| `discord-log` | daily summary → private Discord channel |
| `taskwarrior-sync` | arc tasks → Taskwarrior |

### hooks

`~/.mapsOS/hooks/`: `post-session`, `post-pattern`, `pre-briefing`, `post-arc-update`

### community / dotfile economy

Users publish `~/.mapsOS/` configs as GitHub repos.
A schema.toml adding custom states is a 5-star repo.
A plugin syncing to Apple Health or Obsidian gets forked immediately.

`maps plugin add github.com/user/repo` — no registry needed in phase 1, just document the contract.

---

## agent aggregation pipeline

### the meta-summary

Every agent that works with maps produces outputs.
The meta-summary aggregates all of them into one living document.

Location: `~/atlas/agents/MASTER_SUMMARY.md`

```markdown
---
type: master-summary
updated: YYYY-MM-DD
version: N
contributing_agents: [hermes, codex, claude, opencode]
---

# maps — master context

## identity
## current situation
## active projects
## technical stack
## preferences + patterns
## open questions
## recent decisions
## agent notes
```

### aggregation flow

```
session ends
  → agent writes ~/atlas/agents/{agent}/sessions/YYYY-MM-DD_NNN.md
  → hermes: cart agent-ingest hermes session.json
  → hermes synthesizes ~/atlas/agents/hermes/SUMMARY.md
  → periodically: hermes runs aggregator against all agent summaries
  → output: ~/atlas/agents/MASTER_SUMMARY.md
  → next session: agent reads MASTER_SUMMARY.md as context
```

### self-improvement loop

The aggregator prompt includes: "What is missing or stale in this summary?
What should be added, removed, or weighted differently?"

Each agent appends suggestions under `## agent notes`.
Next aggregation run incorporates those notes.
Summary gets more accurate and more reflective of how maps actually works over time.

### agent routing (configurable)

Phase 1: Hermes only (see HERMES_BOOTSTRAP.md).
Phase 2+: configurable pipeline via `~/atlas/.cartographer/aggregation.toml`:

```toml
[pipeline]
default_agent = "hermes"

[[pipeline.stages]]
name = "session-ingest"
agent = "hermes"
trigger = "post-session"

[[pipeline.stages]]
name = "summary-synthesis"
agent = "hermes"
trigger = "daily"

[[pipeline.stages]]
name = "code-review"
agent = "opencode"
trigger = "on-demand"

[[pipeline.stages]]
name = "deep-synthesis"
agent = "claude"
trigger = "weekly"
```

---

*the tape keeps rolling. the server never sleeps.*
