# cartographer

**cartographer** is a local-first knowledge filesystem and agent memory layer.

Plain Markdown files. Git-native history. Queryable notes. Block-addressable text.
Agents and humans write to the same substrate. Nothing is trapped in an app.

This is the thing that maps your knowledge.
The directory it maps is the **atlas**.

If Notion, LogSeq, Todoist, vimwiki, Obsidian, and agent memory had a terminal-native
child that refused to hold your data hostage, this would be the direction of travel.

## why this exists

maps needs a system where:

- files are the API
- agents can write durable memory without inventing a SaaS layer
- notes stay readable if cartographer disappears tomorrow
- git is the database
- query feels like grep but thinks more like a graph
- block references work without forcing a whole new editor

cartographer is meant to become substrate, not ornament.
The point is not a prettier notes app. The point is a filesystem that can hold:

- projects
- daily notes
- task state
- entity knowledge
- agent session logs
- distilled learnings
- mapsOS sync

## current status

This repo is past "spec only." It has a working local implementation.

**Implemented now**

- atlas initialization under `~/atlas` or `CARTOGRAPHER_ROOT`
- Markdown note creation from templates
- block insertion for `auto_blocks: true` notes
- SQLite indexing for notes, blocks, and backlinks
- query and backlink commands
- Markdown task CRUD
- worklog database
- plugin runner with JSON stdin/stdout contract
- built-in plugins: `summarize`, `daily-brief`, `agent-ingest`
- agent memory flows: `cart learn`, `cart agent-ingest`, `cart agent-gc`
- vimwiki patching support
- atlas-local Obsidian bootstrap
- mapsOS bridge via `cart mapsos ingest`, `cart mapsos ingest-intake`, and `cart mapsos ingest-exports`
- mapsOS state-log + trend synthesis via `cart mapsos patterns`
- atlas session brief generation via `cart daily-brief`
- learning audit loop via `cart learn confirm`, `cart learn reject`, and `cart learn pending`
- entity backlink cleanup via `cart entities clean-imports`

**Still rough / still moving**

- lightweight regression tests for backup behavior and mapsOS ingest
- synthesis is still mostly deterministic/local, not fully model-backed
- transclusion/export are not done
- concurrent write protection is not done
- hooks exist, but the ecosystem around them is still early

Ship style is still: move fast and break things.

## project scope

cartographer is trying to cover four layers at once:

### 1. personal knowledge filesystem

Projects, notes, dailies, references, entities, and tasks all live as files in one atlas.

### 2. agent memory substrate

Hermes, Codex, Claude, OpenCode, and future agents should be able to write:

- session logs
- summaries
- extracted learnings
- contribution files
- structured backlinks to entities and projects

### 3. terminal-native query surface

You should be able to ask:

- what notes mention the launch plan?
- what blocks point at `project-alpha#b001`?
- what open tasks are P0?
- what did Hermes learn this week?

And get file paths back, fast, pipeable, Unix-style.

### 4. mapsOS bridge

cartographer now has an initial mapsOS ingest path and is still the long-term landing zone for:

- mapsOS dailies
- mapsOS task exports
- mood/intake references
- synthesis across life tracking + project tracking + agent memory

Current bridge surface:

- `cart mapsos ingest export.json`
- `cart mapsos ingest-intake ~/dev/mapsOS/intakes/2026-04-13_full_intake.md`
- `cart mapsos ingest-exports --latest`
- `cart mapsos patterns`
- `cart daily-brief`
- syncs a mapsOS payload into `daily/YYYY-MM-DD.md`
- writes exported tasks to `tasks/mapsos.md`
- writes a state snapshot to `agents/mapsOS/YYYY-MM-DD.md`
- appends `agents/mapsOS/state-log.md`
- writes extracted learnings under `agents/mapsOS/learnings/`

## design rules

1. **Files are the API.** Delete cartographer and your files still make sense.
2. **Structure lives in frontmatter, not migrations.**
3. **Git is the database.**
4. **Agents are first-class writers.**
5. **Plugins are just programs.** If it reads stdin and writes stdout JSON, it can join.
6. **Blocks matter.** Paragraph-level addressability is not optional fluff.

## atlas shape

The default atlas looks like this:

```text
~/atlas/
├── .cartographer/
│   ├── config.toml
│   ├── plugins/
│   ├── templates/
│   ├── hooks/
│   ├── index.db
│   └── worklog.db
├── index.md
├── daily/
├── projects/
├── agents/
│   ├── hermes/
│   └── codex/
├── entities/
├── tasks/
└── ref/
```

## note model

Notes are Markdown with YAML frontmatter.

```markdown
---
id: project-alpha
title: Project Alpha
type: project
status: active
tags: [automation, voice, python]
links: [team-notes, launch-plan]
auto_blocks: true
created: 2026-04-16
modified: 2026-04-16
---

# Project Alpha

<!-- cart:block id="b001" -->
The release checklist is still blocked on approval copy.
<!-- /cart:block -->
```

Block refs use `[[note-id#block-id]]`.
That keeps the files Obsidian-readable while still giving cartographer something stronger than page links.

## install

Requirements:

- Python `>=3.11`
- `pipx` recommended

Install locally:

```zsh
cd ~/dev/cartographer
pipx install -e .
```

You get three equivalent entrypoints:

```zsh
cart
cartog
cartographer
```

## quickstart

### initialize a real atlas

```zsh
cart init
```

This will:

- create `~/atlas`
- create `.cartographer/config.toml`
- install built-in templates and plugins
- initialize a git repo in the atlas if needed
- optionally patch vimwiki config
- create the initial index + worklog databases

### initialize a disposable atlas

Useful for smoke tests:

```zsh
export CARTOGRAPHER_ROOT=/tmp/cartographer-demo
export CARTOGRAPHER_SKIP_VIMWIKI_PATCH=1
export CARTOGRAPHER_SKIP_EDITOR=1
cart init /tmp/cartographer-demo
```

## core commands

### atlas + status

```zsh
cart init [path]
cart init [path] --no-vimwiki --no-obsidian
cart status
cart backup
cart index rebuild
cart index status
```

### notes

```zsh
cart new note "Voice System"
cart new project "Project Alpha"
cart new daily 2026-04-16
cart ls --type project --limit 10
cart open project-alpha
cart show master-summary
cart edit project-alpha
```

### query + graph-ish lookup

```zsh
cart query 'tag:project status:active'
cart query 'links:launch-plan'
cart query 'modified:>2026-04-01'
cart query 'text:"Project Alpha"'
cart query 'block-ref:project-alpha#b001'
cart backlinks project-alpha
cart backlinks --block project-alpha#b001
```

### tasks

```zsh
cart todo list
cart todo add "finish release checklist" -p P0 --project project-alpha --due 2026-04-20
cart todo done t123abc
cart todo query 'project:project-alpha status:open'
```

### worklog

```zsh
cart worklog status
cart worklog log "rebuilt atlas after import"
cart worklog complete w1234567 --result "done"
```

### agent memory

```zsh
cart session-import claude --latest 1
cart session-import hermes --latest 1
cart bootstrap-populate
cart learn "Release copy is still waiting on review" --topic project-alpha --agent hermes --entity reviewer
cart learn pending
cart learn confirm project-alpha
cart learn reject --block l123abc
cart agent-ingest hermes session.json
cart agent-gc --threshold 0.30
cart summarize 'type:project status:active'
```

### mapsOS bridge

```zsh
cart mapsos ingest export.json
cat export.json | cart mapsos ingest -
cart mapsos ingest-intake ~/dev/mapsOS/intakes/2026-04-13_full_intake.md
cart mapsos ingest-exports --latest
cart mapsos patterns --field state
cart entities clean-imports
cart daily-brief --output ~/atlas/daily/brief-$(date +%F).md
```

### plugins

```zsh
cart plugin list
cart plugin run summarize max_words=120 < payload.json
```

## plugin contract

Plugins are normal executables inside `.cartographer/plugins/`.

Input:

```json
{
  "command": "summarize",
  "args": { "max_words": 300, "model": "hermes" },
  "notes": [
    {
      "id": "project-alpha",
      "frontmatter": { "title": "Project Alpha", "type": "project" },
      "content": "..."
    }
  ]
}
```

Output:

```json
{
  "output": "...",
  "writes": [
    { "path": "agents/hermes/SUMMARY.md", "content": "..." }
  ],
  "errors": []
}
```

This is deliberately boring. Boring is good here.
It means Python, shell, Lua, or anything else can plug in without ceremony.

## agent workflow

cartographer is opinionated about one thing:
agents should contribute to files, not to invisible memory only.

Current patterns in this repo:

- Hermes owns `MASTER_SUMMARY.md` integration
- other agents contribute via contribution files
- session logs can be ingested into durable notes
- learnings get their own topic files
- entities get backlinks from session memory

The goal is simple:
if an agent learns something durable, it should leave a trace a human can inspect.

## integrations

### vimwiki

`cart init` can patch `~/.vimrc` to make the atlas the primary wiki.

Backups happen first.
If you want a safer first run, use:

```zsh
export CARTOGRAPHER_SKIP_VIMWIKI_PATCH=1
```

### obsidian

cartographer uses normal Markdown plus HTML comment block markers, so Obsidian can coexist with it.

You can point Obsidian directly at `~/atlas`.
`.cartographer/` stays implementation detail.

## roadmap

### now

- make the local core solid
- keep atlas files readable
- keep agent memory durable
- iterate on query + ingestion flows

### next

- stronger provenance for learnings
- model-backed summary backends
- better import adapters for Claude/OpenCode sessions
- safer concurrent writes
- richer mapsOS sync and bidirectional flows
- export / transclusion

### later

- graph views
- publish/export surface
- richer review workflows
- broader plugin ecosystem

## what this is not

- not a SaaS notes app
- not a proprietary memory store
- not a visual knowledge graph first
- not a polished desktop product yet
- not pretending phase 4 is already shipped

## repository map

- [SPEC.md](SPEC.md): product spec and locked decisions
- [HANDOVER.md](HANDOVER.md): original build order
- [CLAUDE_OPENCODE_REVIEW.md](CLAUDE_OPENCODE_REVIEW.md): scoped future additions for Claude/OpenCode review
- [AGENT_CONTRIBUTE.md](AGENT_CONTRIBUTE.md): contribution workflow for non-Hermes agents

## tone check

This project is ambitious on purpose.
It is also allowed to be a little dangerous while the core takes shape.

The promise is not "perfect knowledge management."
The promise is:

- your files stay yours
- your agents can leave durable memory
- your system can grow without getting trapped in somebody else's product

the tape keeps rolling. the server never sleeps.
