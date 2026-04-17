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
- imported conversation history from any platform

## current status

Phase 3 is shipped. The closed loop is live.

```
mapsOS session → structured export → cart ingest → atlas update → daily brief → next session start
```

**Implemented**

- atlas initialization under `~/atlas` or `CARTOGRAPHER_ROOT`
- Markdown note creation from templates
- block insertion for `auto_blocks: true` notes
- SQLite indexing for notes, blocks, and backlinks
- full-text search and field queries
- Markdown task CRUD
- worklog database
- plugin runner with JSON stdin/stdout contract
- built-in plugins: `summarize`, `daily-brief`, `agent-ingest`
- agent memory flows: `cart learn`, `cart agent-ingest`, `cart agent-gc`
- session import: `cart session-import claude` and `cart session-import hermes`
  - deduped by default — re-running skips already-indexed sessions
  - `--force` to overwrite
- external import pipeline: `cart import chatgpt` and `cart import claude-web`
  - parses ChatGPT bulk export (`conversations.json`)
  - parses Claude.ai bulk export (`conversations.json`)
- graph export: `cart graph --export` — all notes as nodes, all links as edges (JSON)
- mapsOS bridge: `cart mapsos ingest`, `cart mapsos ingest-intake`, `cart mapsos ingest-exports`
- mapsOS trend synthesis: `cart mapsos patterns`
- session brief generation: `cart daily-brief`
- learning audit loop: `cart learn confirm`, `cart learn reject`, `cart learn pending`
- entity backlink cleanup: `cart entities clean-imports`
- vimwiki patching support
- atlas-local Obsidian bootstrap

**Still moving**

- concurrent write protection
- model-backed summary backends
- richer mapsOS bidirectional sync
- transclusion / export surface

## live atlas stats (2026-04-17)

274 notes. 232 sessions ingested (Claude Code, Hermes, Codex). 1546 link edges.

## project scope

### 1. personal knowledge filesystem

Projects, notes, dailies, references, entities, and tasks — all files, one atlas.

### 2. agent memory substrate

Hermes, Codex, Claude, OpenCode, and future agents write:

- session logs
- summaries
- extracted learnings
- contribution files
- structured backlinks to entities and projects

### 3. terminal-native query surface

```zsh
cart query 'tag:project status:active'
cart query 'text:hopeagent'
cart backlinks chris
```

File paths back, fast, pipeable, Unix-style.

### 4. external import pipeline

Import full conversation history from any platform:

```zsh
cart import chatgpt ~/Downloads/conversations.json
cart import claude-web ~/Downloads/conversations.json
cart session-import claude --all
cart session-import hermes --all
```

All imports are deduped. Run them as many times as you want.

### 5. mapsOS bridge

```zsh
maps export                                   # from inside mapsOS TUI
cart mapsos ingest-exports --latest           # pull into atlas
cart mapsos patterns --field state            # trend summary
cart daily-brief                              # atlas-derived session brief
```

## design rules

1. **Files are the API.** Delete cartographer and your files still make sense.
2. **Structure lives in frontmatter, not migrations.**
3. **Git is the database.**
4. **Agents are first-class writers.**
5. **Plugins are just programs.** If it reads stdin and writes stdout JSON, it can join.
6. **Blocks matter.** Paragraph-level addressability is not optional fluff.
7. **Imports are idempotent.** Re-running never creates duplicates.

## atlas shape

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
│   ├── claude/
│   │   └── sessions/
│   ├── hermes/
│   │   └── sessions/
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
Files stay Obsidian-readable while cartographer gets something stronger than page links.

## install

Requirements: Python `>=3.11`, `pipx` recommended.

```zsh
cd ~/dev/cartographer
pipx install -e .
```

Three equivalent entrypoints: `cart`, `cartog`, `cartographer`.

## quickstart

```zsh
cart init                    # create ~/atlas, install templates, init git
cart status                  # system health check
cart daily-brief             # atlas-derived session context
cart session-import claude --latest 1
```

For a disposable test atlas:

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
cart ls --type entity
cart open project-alpha
cart show master-summary
cart edit project-alpha
```

### query + backlinks

```zsh
cart query 'tag:project status:active'
cart query 'links:launch-plan'
cart query 'modified:>2026-04-01'
cart query 'text:"Project Alpha"'
cart query 'block-ref:project-alpha#b001'
cart backlinks project-alpha
cart backlinks --block project-alpha#b001
```

### graph export

```zsh
cart graph --export                           # ~/atlas/graph-export.json
cart graph --export /path/to/output.json
```

Output: `{nodes: [{id, title, type, tags}], edges: [{source, target}]}` — feed into d3, gephi, etc.

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

### session import (Claude Code + Hermes)

```zsh
cart session-import claude --latest 1         # latest session, skip if already indexed
cart session-import claude --latest 5
cart session-import claude --all              # all sessions, deduped
cart session-import claude --force            # re-import even if already indexed
cart session-import hermes --latest 1
cart session-import hermes --all
cart bootstrap-populate                       # seed atlas from recent sessions across all agents
```

### external import (ChatGPT, Claude.ai)

```zsh
# ChatGPT: Settings → Data controls → Export data → conversations.json
cart import chatgpt ~/Downloads/conversations.json
cart import chatgpt ~/Downloads/conversations.json --latest 10

# Claude.ai: Settings → Account → Export data → conversations.json
cart import claude-web ~/Downloads/conversations.json
cart import claude-web ~/Downloads/conversations.json --latest 10

# Both support --force to re-import skipped sessions
```

### agent memory + learnings

```zsh
cart learn "Release copy is still waiting on review" --topic project-alpha --agent hermes
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
cart mapsos ingest-intake --all
cart mapsos ingest-exports --latest
cart mapsos patterns
cart mapsos patterns --field state
cart entities clean-imports
cart daily-brief
cart daily-brief --output ~/atlas/daily/brief-$(date +%F).md
```

### plugins

```zsh
cart plugin list
cart plugin run summarize max_words=120 < payload.json
```

## plugin contract

Plugins are executables inside `.cartographer/plugins/`.

Input:

```json
{
  "command": "summarize",
  "args": { "max_words": 300, "model": "hermes" },
  "notes": [
    { "id": "project-alpha", "frontmatter": {}, "content": "..." }
  ]
}
```

Output:

```json
{
  "output": "...",
  "writes": [{ "path": "agents/hermes/SUMMARY.md", "content": "..." }],
  "errors": []
}
```

Python, shell, Lua, anything that reads stdin and writes stdout JSON can plug in.

## agent workflow

cartographer is opinionated about one thing:
agents should contribute to files, not to invisible memory only.

Patterns in this repo:

- Hermes owns `MASTER_SUMMARY.md` synthesis
- agents contribute via contribution files under `agents/<name>/`
- session logs are ingested into durable, queryable notes
- learnings get their own topic files with provenance
- entities accumulate backlinks from every session that mentions them

If an agent learns something durable, it leaves a trace a human can inspect.

### onboarding a new agent

Read `AGENT_ONBOARDING.md` in this repo. It covers the full system, all projects,
all people, current priorities, and agent protocol. Any agent that reads it and runs
`cart daily-brief` is fully context-loaded.

## integrations

### vimwiki

`cart init` can patch `~/.vimrc` to make the atlas the primary wiki.

```zsh
export CARTOGRAPHER_SKIP_VIMWIKI_PATCH=1   # skip if you don't want this
```

### obsidian

cartographer uses normal Markdown plus HTML comment block markers.
Point Obsidian directly at `~/atlas`. `.cartographer/` stays implementation detail.

## what this is not

- not a SaaS notes app
- not a proprietary memory store
- not a visual knowledge graph first
- not a polished desktop product yet
- not pretending phase 4 is already shipped

## repository map

- [SPEC.md](SPEC.md) — product spec and locked decisions
- [AGENT_ONBOARDING.md](AGENT_ONBOARDING.md) — full system context for any agent
- [AGENT_CONTRIBUTE.md](AGENT_CONTRIBUTE.md) — contribution workflow for non-Hermes agents
- [CART_PHASE3_SPEC.md](CART_PHASE3_SPEC.md) — phase 3 implementation record
- [CART_SYSTEM_HANDOVER_2026-04-17.md](CART_SYSTEM_HANDOVER_2026-04-17.md) — current system state

the tape keeps rolling. the server never sleeps.
