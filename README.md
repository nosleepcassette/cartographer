# cartographer

**cartographer** is a local-first knowledge filesystem and agent memory layer.

Plain Markdown files. Git-native history. Queryable notes. Block-addressable text.
Agents and humans write to the same substrate. Nothing is trapped in an app.

This is the thing that maps your knowledge.
The directory it maps is the **atlas**.

---

## the pitch

If you've ever:

- Switched note apps and lost your tags/links/backlinks
- Wanted agents to remember things without a SaaS subscription
- Needed to query your own brain from the terminal
- Been burned by proprietary lock-in on your own thoughts

cartographer is the direction of travel.

**Files are the API.** Delete cartographer tomorrow and your notes are still readable Markdown. Git is the database. SQLite is an index, not a prison.

---

## what makes this different

### 1. agents are first-class citizens

Most knowledge tools pretend AI doesn't exist. cartographer assumes:

- Multiple AI agents will read and write to the same knowledge base
- Sessions should be ingested, not siloed
- Learnings deserve durable files, not invisible context windows
- Agents should be able to query their own memory

Built-in flows for Hermes, Claude Code, Codex, and any agent that can write Markdown.

### 2. block-addressable by default

Every paragraph gets a block ID. Transclude with `[[note-id#block-id]]`. Your files stay Obsidian-readable while cartographer gives you something stronger than page links.

### 3. imports are idempotent

Run imports as many times as you want. Session deduplication is built in. No duplicates, no manual cleanup.

### 4. the daily brief

`cart daily-brief` generates session context from your atlas:
- Open tasks by priority
- Active projects with last-touched dates
- Recent patterns and learnings
- Things you might have forgotten

### 5. mapsOS integration

cartographer is the memory layer for [mapsOS](https://github.com/nosleepcassette/mapsOS):
- Ingest qualitative state exports
- Track arcs and patterns
- Surface survival mode context
- Bridge personal analytics to agent memory

---

## current status

**Phase 3 shipped.** The closed loop is live:

```
session → export → cart ingest → atlas update → daily brief → next session
```

### implemented

- Atlas initialization (`cart init`)
- Markdown notes with YAML frontmatter
- SQLite indexing for full-text search
- Block insertion and addressing
- Task CRUD with priorities
- Plugin system (JSON stdin/stdout)
- Session import: Claude Code, Hermes (deduped)
- External import: ChatGPT, Claude.ai conversation exports
- Graph export: all notes as nodes, all links as edges (JSON)
- mapsOS bridge: ingest exports, synthesize patterns
- Daily brief generation
- Learning audit loop

### still moving

- Concurrent write protection
- Model-backed summary backends
- Richer mapsOS bidirectional sync
- Transclusion rendering

---

## atlas shape

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
└── ref/
```

---

## install

```zsh
pipx install git+https://github.com/nosleepcassette/cartographer.git
```

Or from checkout:

```zsh
cd ~/dev/cartographer
pipx install -e .
```

Three equivalent entrypoints: `cart`, `cartog`, `cartographer`.

---

## quickstart

```zsh
cart init                    # create ~/atlas, install templates, init git
cart status                  # system health check
cart daily-brief             # generate session context
cart session-import claude --latest 1
```

---

## core commands

### atlas + status

```zsh
cart init [path]
cart status
cart backup
cart index rebuild
```

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
cart query 'tag:project status:active'
cart query 'modified:>2026-04-01'
cart query 'text:"release checklist"'
cart backlinks project-alpha
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
cart session-import claude --force   # re-import even if indexed
```

### external import

```zsh
# ChatGPT: Settings → Data controls → Export
cart import chatgpt ~/Downloads/conversations.json

# Claude.ai: Settings → Account → Export
cart import claude-web ~/Downloads/conversations.json
```

Both support `--latest N` and `--force`. All imports are deduped.

### graph export

```zsh
cart graph --export    # writes ~/atlas/graph-export.json
```

Output: `{nodes: [{id, title, type, tags}], edges: [{source, target}]}` — feed into D3, Gephi, Obsidian Graph, etc.

### mapsOS bridge

```zsh
cart mapsos ingest-exports --latest
cart mapsos patterns --field state
cart daily-brief
```

---

## design rules

1. **Files are the API.** Delete cartographer and your files still make sense.
2. **Structure lives in frontmatter, not migrations.**
3. **Git is the database.**
4. **Agents are first-class writers.**
5. **Plugins are just programs.** Anything that reads stdin and writes stdout JSON can join.
6. **Blocks matter.** Paragraph-level addressability is not optional.
7. **Imports are idempotent.** Re-running never creates duplicates.

---

## note model

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

## plugin contract

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

Python, shell, Lua, anything that speaks JSON on stdin/stdout.

---

## hermes integration

cartographer is the canonical memory layer for Hermes agents:

- **Session import:** `cart session-import hermes --all`
- **Learning capture:** `cart learn "observation" --topic slug`
- **Daily brief:** Loaded at session start via `cart daily-brief`
- **Context awareness:** See `skills/context-awareness/SKILL.md` in the Hermes profile

When Hermes learns something durable, it writes to the atlas. When it starts a session, it reads from the atlas. No invisible memory. No context loss between sessions.

---

## integrations

### vimwiki

`cart init` can patch `~/.vimrc` to make the atlas your primary wiki. Skip with:

```zsh
export CARTOGRAPHER_SKIP_VIMWIKI_PATCH=1
```

### obsidian

cartographer uses Markdown plus HTML comment block markers. Point Obsidian at `~/atlas`. `.cartographer/` stays implementation detail.

---

## what this is not

- Not a SaaS notes app
- Not a proprietary memory store
- Not a visual knowledge graph first (but `cart graph --export` gives you one)
- Not pretending phase 4 is shipped

---

## repository map

- `SPEC.md` — product spec and locked decisions
- `AGENT_ONBOARDING.md` — context for any agent joining the system
- `CART_PHASE3_SPEC.md` — phase 3 implementation record

---

## license

MIT. See LICENSE.

---

the tape keeps rolling. the server never sleeps.
