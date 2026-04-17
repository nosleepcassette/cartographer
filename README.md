# cartographer

> Your agents should know how you're actually doing - and remember everything they learn.

Local-first knowledge filesystem and agent memory layer.

Plain Markdown. Git history. Queryable graph. Block-addressable text.
Agents and humans write to the same substrate. Nothing is trapped in an app.

---

Someone on Discord, after seeing an early scope sheet, wrote:
*"maybe under an orchestrator project (atlas?)"*

They arrived at the architecture without knowing it already existed.
That's the idea.

**atlas** is the substrate. cartographer is what builds and queries it.
mapsOS is what keeps it honest about how you're actually doing.

---

## why this is different

Most knowledge tools ignore AI entirely. Most AI tools ignore your history.
cartographer assumes both exist and treats them as first-class:

- **Agent memory persists.** Session import turns context windows into a growing graph. `cart daily-brief` seeds tomorrow's session from everything that happened today.
- **Files are the API.** Delete cartographer. Your notes are still readable Markdown with YAML frontmatter. Git is the database. SQLite is an index, not a prison.
- **Block-addressable by default.** `[[note-id#block-id]]` transclusion. Backlinks tracked automatically. The relational layer Obsidian promised but never fully delivered.
- **Imports are idempotent.** Run `cart session-import` a hundred times. Zero duplicates. Just an always-current graph.
- **Built for neurodivergent workflows.** Qualitative state tracking, capacity-aware context, honest about when you're not okay. Paired with mapsOS. Configurable for any brain.
- **Plugin economy.** stdin/stdout JSON contract. If it speaks that, it joins. The long-term goal is Vim-scale extensibility.

---

## what shipped in this push

This is the release where atlas starts to feel like a real operating surface instead of just a filesystem plus commands.

- **A real atlas interface.** `cart tui` gives you a Textual TUI with a structured graph pane, note pane, transclusion rendering, backlinks, tasks overlay, and vim-style movement.
- **mapsOS handoff is built in.** Hit `m` from the cartographer TUI to drop into mapsOS. Hit `C` in mapsOS to come back. mapsOS exports ingest back into the atlas on exit.
- **State is visible inside memory now.** The atlas TUI reads the latest mapsOS export directly and shows current qualitative state, active arcs, and open P0 load in the state strip.
- **The system is more clearly one thing.** mapsOS is the qualitative layer. cartographer is the memory and task layer. atlas is the substrate underneath both.
- **The developer framing is explicit.** This repo is not just "my notes tool." It is infrastructure for agents, plugins, shared memory, and weird local-first systems that need durable context.

---

## current status

**Phase 4 is live.** The closed loop is local and usable:

```text
session -> export -> cart ingest -> atlas update -> daily brief -> next session
```

### implemented

- Atlas initialization (`cart init`)
- Markdown notes with YAML frontmatter
- SQLite indexing for full-text search
- Block insertion and addressing
- Block transclusion rendering in the atlas TUI
- Task CRUD with priorities
- Plugin system (JSON stdin/stdout)
- Session import: Claude Code, Hermes, Codex (deduped)
- External import: ChatGPT, Claude.ai conversation exports
- Graph export: all notes as nodes, all links as edges (JSON)
- Textual atlas TUI (`cart tui`) with graph navigation, note rendering, backlinks, tasks overlay, and mapsOS handoff
- mapsOS bridge: ingest exports, synthesize patterns, and read state back into the atlas surface
- Daily brief generation
- Learning audit loop

### still moving

- Concurrent write protection under heavier multi-agent load
- Model-backed summary backends
- Richer shared-atlas and multi-user workflows
- Deeper mapsOS task write-back

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
cart init
cart status
cart daily-brief
cart tui
cart session-import claude --latest 1
```

---

## core commands

### atlas + status

```zsh
cart init [path]
cart status
cart tui
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
cart session-import claude --force
```

### external import

```zsh
cart import chatgpt ~/Downloads/conversations.json
cart import claude-web ~/Downloads/conversations.json
```

Both support `--latest N` and `--force`. All imports are deduped.

### graph export

```zsh
cart graph --export
```

Output: `{nodes: [{id, title, type, tags}], edges: [{source, target}]}`.

### mapsOS bridge

```zsh
cart mapsos ingest-exports --latest
cart mapsos patterns --field state
cart daily-brief
```

Inside the TUIs:

- `cart tui` -> `m` launches mapsOS
- `maps` -> `C` launches cartographer
- quitting mapsOS ingests the latest export back into the atlas when `cart` is available

---

## atlas loop

```text
agent session
  -> session import
  -> atlas note + links + tasks + learnings
  -> mapsOS export ingested as qualitative state
  -> daily brief
  -> next session starts from real memory instead of zero
```

This is the core promise of the project: context windows close, but the graph stays.

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

### developers

See `DEVELOPERS.md` for the plugin contract, extension points, and what to build on top of the atlas substrate.

Short version:

- Build agent plugins that read atlas context and write durable memory back.
- Build domain-specific atlas stacks for research, teams, therapy, operations, or neurodivergent life management.
- Build new surfaces on top of the files-and-graph layer instead of starting from another silo.

Repos:

- cartographer: <https://github.com/nosleepcassette/cartographer>
- mapsOS: <https://github.com/nosleepcassette/mapsOS>

---

## what this is not

- Not a SaaS notes app
- Not a proprietary memory store
- Not a visual knowledge graph first, even though `cart graph --export` gives you one
- Not pretending the surface area is finished

---

## repository map

- `SPEC.md` - product spec and locked decisions
- `AGENT_ONBOARDING.md` - context for any agent joining the system
- `CART_PHASE3_SPEC.md` - phase 3 implementation record
- `DEVELOPERS.md` - extension points and developer-facing framing

---

## license

MIT. See LICENSE.

---

the tape keeps rolling. the server never sleeps.
