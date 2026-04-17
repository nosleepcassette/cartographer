# cartographer — HANDOVER
# maps · cassette.help · MIT
# generated: 2026-04-16
# for: codex / opencode
# ship style: move fast and break things. no tests in phase 1.

---

## what you are building

**cartographer** — a local-first knowledge filesystem and agent memory layer.
CLI: `cart`, `cartog`, `cartographer` (all synonyms, all installed).
Atlas root: `~/atlas/`
Full spec: `SPEC.md` (read it first, this file is the build order).

Phase 1 only. Build the core. Get it running. maps will break it.

---

## pre-flight: backup (run before touching any files)

```zsh
STAMP=$(date +%Y%m%d_%H%M%S)
cp ~/.vimrc ~/.vimrc.bak.cart.$STAMP
cp -r ~/.vim ~/.vim.bak.cart.$STAMP 2>/dev/null || true
cp -r ~/vimwiki ~/vimwiki.bak.cart.$STAMP 2>/dev/null || true
cp -r ~/writing ~/writing.bak.cart.$STAMP 2>/dev/null || true
cp -r ~/therapy ~/therapy.bak.cart.$STAMP 2>/dev/null || true
echo "backups done: $STAMP"
```

Verify backups exist before any further step.

---

## repo structure to create

```
~/dev/cartographer/
├── pyproject.toml
├── README.md
├── cartographer/
│   ├── __init__.py
│   ├── cli.py              ← click entry point, all subcommands
│   ├── atlas.py            ← Atlas class: root path, config, init
│   ├── index.py            ← SQLite index: build, query, update
│   ├── notes.py            ← Note class: parse frontmatter, block IDs
│   ├── blocks.py           ← block ID generation, insertion, parsing
│   ├── tasks.py            ← todo CRUD on task block notes
│   ├── worklog.py          ← cartographer's own worklog (worklog.db)
│   ├── plugins.py          ← plugin runner (stdin/stdout JSON)
│   ├── hooks.py            ← hook runner (pre/post-write)
│   ├── templates.py        ← Jinja2 template loader + renderer
│   ├── vimwiki.py          ← vimrc patch, index.md generation
│   ├── obsidian.py         ← vault detection, sync
│   └── config.py           ← TOML config load/save/defaults
├── templates/
│   ├── note.md.j2
│   ├── daily.md.j2
│   ├── project.md.j2
│   ├── task.md.j2
│   └── agent-log.md.j2
└── plugins/
    ├── summarize.py
    ├── daily-brief.py
    └── agent-ingest.py
```

---

## pyproject.toml

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "cartographer"
version = "0.1.0"
description = "local-first knowledge filesystem"
requires-python = ">=3.11"
dependencies = [
    "click>=8.0",
    "pyyaml>=6.0",
    "jinja2>=3.0",
]

[project.scripts]
cart        = "cartographer.cli:main"
cartog      = "cartographer.cli:main"
cartographer = "cartographer.cli:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["cartographer*"]
```

Install: `pipx install -e ~/dev/cartographer`

---

## phase 1 build order

Build in this exact order. Each step should be runnable before moving to the next.

### step 1: pyproject + cli skeleton

Create `pyproject.toml` and `cartographer/cli.py` with all subcommands stubbed
(raise `NotImplementedError` or print "TODO" for unimplemented ones).
After this step: `cart --help` works and shows all commands.

```python
# cartographer/cli.py
import click

@click.group()
def main():
    """cartographer — maps your knowledge."""
    pass

@main.command()
@click.argument('path', default='~/atlas', required=False)
def init(path): ...

@main.command()
def status(): ...

@main.command()
def backup(): ...

@main.group()
def todo(): ...

@todo.command('list')
def todo_list(): ...

@todo.command('add')
@click.argument('text')
@click.option('-p', '--priority', default='P2')
def todo_add(text, priority): ...

@todo.command('done')
@click.argument('id')
def todo_done(id): ...

@main.group()
def worklog(): ...

@worklog.command('status')
def worklog_status(): ...

# etc for all commands in spec
```

### step 2: config + atlas init

`cartographer/config.py` — load/save `~/.cartographer/config.toml` or `.cartographer/config.toml` in root.

```python
# default config
DEFAULT_CONFIG = {
    "cartographer": {"version": 1, "root": "~/atlas"},
    "index": {"auto_update": True, "full_text": True},
    "agents": {"hermes": {"path": "agents/hermes", "summary": "agents/hermes/SUMMARY.md"}},
    "ignore": {"dirs": [".obsidian", ".git", "__pycache__", "node_modules", ".cartographer"],
               "extensions": [".DS_Store"]},
    "vimwiki": {"sync": True},
    "obsidian": {"vault": "~/vaults"},
    "sync": {"method": "git"},
    "daily": {"mode": "bidirectional"},  # bidirectional | mapsos-only | atlas-only | off
}
```

`cartographer/atlas.py` — `Atlas` class:
```python
class Atlas:
    def __init__(self, root=None):
        self.root = Path(root or config.get('root', '~/atlas')).expanduser()

    def init(self):
        # create ~/atlas/ directory tree
        # create .cartographer/ with config.toml
        # create index.md from template
        # create subdirs: daily/ projects/ agents/hermes/ agents/codex/ entities/ tasks/ ref/
        # init git repo if not already
        # patch vimrc (after backup)
        # detect obsidian vault
        # init worklog.db
        # print success summary
```

`cart init` should produce a working atlas root and print what it did.

### step 3: note parsing + block IDs

`cartographer/notes.py`:
```python
import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

BLOCK_PATTERN = re.compile(
    r'<!-- cart:block id="(?P<id>[^"]+)"(?P<attrs>[^>]*) -->'
    r'(?P<content>.*?)'
    r'<!-- /cart:block -->',
    re.DOTALL
)

@dataclass
class Block:
    id: str
    content: str
    type: str = "note"

@dataclass
class Note:
    path: Path
    frontmatter: dict = field(default_factory=dict)
    body: str = ""
    blocks: list[Block] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> 'Note':
        text = path.read_text()
        fm, body = parse_frontmatter(text)
        blocks = parse_blocks(body)
        return cls(path=path, frontmatter=fm, body=body, blocks=blocks)

    def write(self, ensure_blocks=True):
        if ensure_blocks:
            self.body = insert_missing_block_ids(self.body)
        path.write_text(render(self.frontmatter, self.body))
```

`cartographer/blocks.py`:
- `generate_block_id()` → 6-char hex (uuid4 truncated)
- `insert_missing_block_ids(text)` → wraps bare paragraphs in block comments if auto-block enabled
- `parse_blocks(text)` → list of Block objects

**Important:** block insertion should be opt-in per note via frontmatter `auto_blocks: true`.
Don't auto-insert blocks on every note — that's noisy. Only on `cart new` and when explicitly enabled.

### step 4: SQLite index

`cartographer/index.py`:

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    title TEXT,
    type TEXT,
    status TEXT,
    tags TEXT,          -- JSON array
    links TEXT,         -- JSON array
    modified REAL,
    word_count INTEGER,
    body TEXT           -- full text for search
);

CREATE TABLE IF NOT EXISTS blocks (
    block_id TEXT NOT NULL,
    note_id TEXT NOT NULL,
    content TEXT,
    type TEXT,
    FOREIGN KEY (note_id) REFERENCES notes(id)
);

CREATE TABLE IF NOT EXISTS block_refs (
    from_note TEXT NOT NULL,
    from_block TEXT,
    to_note TEXT NOT NULL,
    to_block TEXT,
    FOREIGN KEY (from_note) REFERENCES notes(id),
    FOREIGN KEY (to_note) REFERENCES notes(id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    id, title, body, content='notes', content_rowid='rowid'
);
"""
```

Key methods:
- `Index.rebuild(root)` — walk atlas root, parse all notes, populate tables
- `Index.update(note)` — upsert single note
- `Index.query(expr)` — parse query string, return list of paths
- `Index.backlinks(note_id)` — return notes with `note_id` in their links field
- `Index.block_backlinks(note_id, block_id)` — return notes referencing `note_id#block_id`

Query parser — handle these patterns:
```
tag:X          → WHERE tags LIKE '%"X"%'
status:X       → WHERE status = 'X'
type:X         → WHERE type = 'X'
links:X        → WHERE links LIKE '%"X"%'
modified:>DATE → WHERE modified > epoch(DATE)
text:"X"       → FTS search
block-ref:X#Y  → JOIN block_refs WHERE to_note=X AND to_block=Y
```

Multiple terms are AND'd.

### step 5: cart query + cart backlinks

Wire `cart query` and `cart backlinks` to `Index.query()` and `Index.backlinks()`.
Output: one path per line (pipeable).

```sh
$ cart query 'tag:project status:active'
/Users/maps/atlas/projects/hopeagent.md
/Users/maps/atlas/projects/voicetape.md

$ cart backlinks hopeagent
/Users/maps/atlas/agents/hermes/sessions/2026-04-16_001.md
```

### step 6: cart new + cart open

`cart new [type] [title]`
- Look up template in `.cartographer/templates/` (fall back to built-ins)
- Render with Jinja2: inject title, date, generated id, empty frontmatter
- Write to appropriate subdirectory based on type
- Open in `$EDITOR`
- Re-index on editor close

`cart open [id]`
- Query index for id
- Open in `$EDITOR`
- Re-index on close

Type → directory mapping:
```
note     → atlas root
daily    → daily/
project  → projects/
task     → tasks/
agent-log → agents/{agent}/sessions/
ref      → ref/
entity   → entities/
```

### step 7: cart todo

Task files: `tasks/active.md` (default), `tasks/YYYY-MM-DD.md` for dated.

Task block format:
```markdown
<!-- cart:block id="t001" type="task" -->
- [ ] finish HopeAgent conversational loop
  status: open
  priority: P0
  project: hopeagent
  due: 2026-04-20
<!-- /cart:block -->
```

`cart todo list` — query index for `type:task status:open`, parse priority, sort P0→P3 then by due date.
`cart todo add "text" -p P0` — append task block to `tasks/active.md`, re-index.
`cart todo done t001` — find block by id, replace `- [ ]` with `- [x]`, update `status: done`, re-index.
`cart todo query 'project:hopeagent'` — filter task blocks by inline attributes.

### step 8: cart status + cart backup

`cart status`:
```
atlas: ~/atlas (312 notes, 1.4MB)
index: up to date (rebuilt 2026-04-16 14:22)
tasks: 4 open (1 P0, 2 P1, 1 P2)
agents: hermes (last session 2026-04-16), codex (no sessions)
git: clean (last commit 2h ago)
worklog: 2 in-progress
```

`cart backup`:
```zsh
STAMP=$(date +%Y%m%d_%H%M%S)
DEST=~/.cartographer_backups/atlas_$STAMP.tar.gz
mkdir -p ~/.cartographer_backups
tar -czf $DEST --exclude='~/atlas/.cartographer/index.db' ~/atlas/
echo "backup: $DEST"
```

Exclude index.db (rebuilds from files). Include config.toml.

### step 9: worklog

`cartographer/worklog.py` — tracks cartographer's own operations.
Schema in `.cartographer/worklog.db`:

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    started REAL,
    ended REAL,
    summary TEXT
);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    description TEXT,
    status TEXT DEFAULT 'pending',  -- pending | in_progress | completed | failed
    result TEXT,
    created REAL,
    completed REAL
);
```

CLI:
- `cart worklog status` — in_progress tasks + last session summary
- `cart worklog complete ID --result "text"` — mark task done
- `cart worklog log "text"` — append note to current session

Hermes can call this directly to log its operations in the same worklog.

### step 10: vimwiki patch

`cartographer/vimwiki.py`:

```python
def patch_vimrc(vimrc_path: Path, atlas_root: Path):
    """
    Backup vimrc, then prepend wiki_atlas definition and
    insert it at the front of vimwiki_list.

    Idempotent: if wiki_atlas already present, do nothing.
    """
    content = vimrc_path.read_text()
    
    if 'wiki_atlas' in content:
        return "already patched"

    # Find vimwiki_list line and inject
    ATLAS_BLOCK = f'''
""" cartographer — atlas wiki (primary, added by cart init)
let wiki_atlas = {{}}
let wiki_atlas.path = '{atlas_root}/'
let wiki_atlas.ext = '.md'
let wiki_atlas.syntax = 'markdown'
let wiki_atlas.auto_tags = 1
'''
    # Insert before existing g:vimwiki_list definition
    content = re.sub(
        r'(let g:vimwiki_list\s*=\s*\[)',
        ATLAS_BLOCK + r'\n\\1wiki_atlas, ',
        content,
        count=1
    )
    vimrc_path.write_text(content)
    return "patched"
```

Run during `cart init`. Print before/after diff for user confirmation.
If user declines, skip — note in status that vimwiki is not configured.

### step 11: obsidian detection

`cartographer/obsidian.py`:

```python
DEFAULT_VAULT_PATHS = [
    Path.home() / 'vaults',
    Path.home() / 'Documents' / 'vaults',
    Path.home() / 'Obsidian',
]

def detect_vault() -> Path | None:
    # check config first
    # then check DEFAULT_VAULT_PATHS
    # return first that exists and contains .obsidian/
    ...

def sync(atlas_root: Path, vault_path: Path):
    """
    Generate a _cartographer_index.md in vault root with links to all
    atlas notes by type. Obsidian can use this as a dataview source.
    Does NOT copy or move files.
    """
    ...
```

Atlas root can BE the vault — if `~/atlas` has `.obsidian/`, cartographer adds it to ignore list and coexists.

---

## templates (built-in defaults)

### templates/note.md.j2
```
---
id: {{ id }}
title: {{ title }}
type: note
tags: []
links: []
created: {{ date }}
modified: {{ date }}
---

# {{ title }}

```

### templates/daily.md.j2
```
---
id: daily-{{ date }}
title: {{ date }}
type: daily
tags: [daily]
links: {% if yesterday %}[daily-{{ yesterday }}]{% else %}[]{% endif %}

created: {{ date }}
modified: {{ date }}
---

# {{ date }}

## today

## notes

## tasks

{% if yesterday %}← [[daily-{{ yesterday }}]]{% endif %}
```

### templates/project.md.j2
```
---
id: {{ id }}
title: {{ title }}
type: project
status: active
tags: [project]
links: []
created: {{ date }}
modified: {{ date }}
---

# {{ title }}

## status

## next

## notes

```

### templates/task.md.j2
```
---
id: {{ id }}
title: Tasks — {{ date }}
type: task-list
created: {{ date }}
modified: {{ date }}
---

# Tasks

<!-- cart:block id="{{ block_id }}" type="task" -->
- [ ] {{ title }}
  status: open
  priority: {{ priority }}
<!-- /cart:block -->
```

---

## self-tracking: cartographer's own worklog

From the moment `cart init` runs, cartographer tracks its own state.

On `cart init`:
```python
wl = Worklog(atlas_root / '.cartographer' / 'worklog.db')
session = wl.start_session()
wl.add_task(session.id, "init atlas root")
# ... do init work ...
wl.complete_task(task_id, result="created ~/atlas, patched vimrc, detected ~/vaults")
wl.end_session(session.id, summary="initial atlas setup")
```

Every subsequent `cart` command that modifies state logs to worklog.
Hermes reads `cart worklog status` to see what cartographer has been doing.

---

## error handling policy (phase 1)

- Missing atlas root: prompt to run `cart init`
- Unparseable frontmatter: skip note, print warning, continue
- Index out of date: auto-rebuild (print "rebuilding index..." to stderr)
- Plugin not found: clear error, list available plugins
- vimrc already patched: skip silently, note in status
- No `$EDITOR` set: fall back to `vim`, then `vi`, then error with instruction

---

## git integration (minimal, phase 1)

On `cart backup`: check if atlas root is a git repo. If yes, print `git status`.
On `cart init`: run `git init ~/atlas` if not already a repo. Add `.cartographer/index.db` and `worklog.db` to `.gitignore`.

```
# ~/atlas/.gitignore
.cartographer/index.db
.cartographer/worklog.db
.obsidian/
```

No auto-commit in phase 1. User runs `git commit` manually.

---

## what to NOT build in phase 1

- Plugin system (phase 2)
- Hooks (phase 2)
- `cart learn` / `cart agent-ingest` (phase 2)
- `cart summarize` (phase 2)
- `cart graph` (phase 4)
- `cart publish` (phase 4)
- Lua support (phase 4)
- mapsOS plugin port (phase 3)
- Transclusion rendering (phase 3)
- Confidence decay (phase 2)

Stub these commands with a clear "coming in phase 2" message.

---

## install instructions (for maps, after build)

```zsh
cd ~/dev/cartographer
pipx install -e .
cart init
# follow prompts for vimrc patch
# open vim, test \ww → should open ~/atlas/index.md
```

---

## handover checklist

- [ ] `pyproject.toml` created
- [ ] `cart --help` works, all commands listed
- [ ] `cart init ~/atlas` creates full directory tree
- [ ] `~/.vimrc` backed up + patched (wiki_atlas at index 0)
- [ ] `~/vaults/` detected and noted in config
- [ ] `cart new note "test"` creates a note in `~/atlas/`
- [ ] `cart query 'tag:project'` returns results
- [ ] `cart backlinks [id]` works
- [ ] `cart todo list` / `add` / `done` work
- [ ] `cart status` shows real data
- [ ] `cart backup` creates tar.gz
- [ ] `cart worklog status` shows init session

---

## files in this repo

```
~/dev/grove/
├── SPEC.md       ← full spec with all decisions (read this)
└── HANDOVER.md   ← this file (build order)
```

Note: repo dir is `grove/` (working name). Project is `cartographer`. Rename `~/dev/grove/` to `~/dev/cartographer/` before starting build.

---

*the tape keeps rolling. the server never sleeps.*
