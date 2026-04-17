# OPENCODE IMPLEMENTATION SPEC
# maps · cassette.help · MIT
# 2026-04-17 — written by vesper for OpenCode to implement, Codex to review

Read BUILDSHEET.md first. This is the HOW. That is the WHAT and WHY.

Also read: AGENT_ONBOARDING.md, README.md, cartographer/cli.py, cartographer/session_import.py

---

## CONTEXT YOU NEED

- cartographer is a Python CLI (`cart`). Entry: `cartographer/cli.py`. Atlas at `~/atlas/`.
- mapsOS is a separate Python project at `~/dev/mapsOS/`. Entry: `bin/maps`, TUI in `environments/tui.py`.
- Both use Rich. Textual 8.2.3 is installed. No urwid for the new TUI.
- Atlas SQLite index: `~/atlas/.cartographer/index.db`. Tables: `notes`, `block_refs`, `blocks`.
- mapsOS config: `~/.maps_os_config.yaml`, loader in `environments/maps_os_config.py`.
- maps · cassette.help · MIT header on all new files.
- No Co-Authored-By. No git push.
- Run `cart status` and `python3 -m pytest tests/ -x -q` in cartographer before and after.
- Run `python3 -m pytest tests/ -x -q` in mapsOS before and after.

---

## TASK 1 — cartographer/tui.py (NEW FILE)

Create `~/dev/cartographer/cartographer/tui.py`.

This is a Textual app. `cart tui` launches it.

### Layout (do not deviate)

```
App (full terminal)
├── Header (1 line): "ATLAS" left, note count + date right, amber on dark
├── Horizontal(ratio):
│   ├── GraphPane (40% width) — left
│   └── NotePane (60% width) — right
└── StateStrip (3 lines) — bottom
```

No sidebar. No palette. Footer shows keybind hints (updated based on focused pane).

### GraphPane

Widget: `ScrollableContainer` subclass. Custom `render()`.

Data source: read `~/atlas/.cartographer/index.db` directly via sqlite3.

```python
# fetch nodes
SELECT id, title, type, tags FROM notes ORDER BY type, modified DESC

# fetch edges  
SELECT DISTINCT from_note, to_note FROM block_refs WHERE from_note != to_note
```

Display — structured rows by type, NOT force-directed:

```
PROJECTS
  ● hopeagent ──── ● cartographer
  ● mapsOS ──── ● nota

ENTITIES
  ● chris ──── ● hopeagent
  ● maggie

SESSIONS (most recent 8)
  ○ 2026-04-17-cartographer-session
  ○ 2026-04-17-maps-session
```

Node symbols: `●` project/entity, `○` session/daily, `◆` learning
Colors (Rich markup):
- project: `#c47c7c`
- entity: `#7ab87e`  
- session/agent-log: `#7b9eb5`
- daily: `#9e6ba8`
- learning: `#c4a87c`

Cursor: highlight selected row with reverse video. j/k moves cursor within pane.
On cursor move: fire `NoteSelected(note_id)` message to update NotePane.

Filter bar: `/` activates an Input widget at top of GraphPane. Typing filters nodes
in real-time (match on id + title, case-insensitive). Show matching nodes + their
direct neighbors. Clear with Escape.

### NotePane

Shows currently selected note. Reads the `.md` file from atlas.

Sections (in order):
1. **Header bar**: `# [title]` large, type badge, status badge
2. **Body**: note.body rendered as markdown (Textual Markdown widget)
   - Parse `![[note-id]]` and `![[note-id#block-id]]` before passing to Markdown
   - Resolve transclusions: look up note/block in index, insert content inline
   - Transclusion style: `dim` text, prefixed with `┊ ` on each line
   - After the block: `┊ ↩ [[source-note-id]]` in dim italic
3. **Backlinks section** (toggle with `b`): 
   - Query: `SELECT DISTINCT from_note FROM block_refs WHERE to_note = ?`
   - Show as: `← [[from-note-id]] (N refs)`
   - If no backlinks: show nothing (don't show empty section)

### StateStrip

3-line panel at bottom. Reads mapsOS state.

```python
def _read_mapsos_state() -> dict:
    # try ~/.mapsOS/exports/ for most recent JSON
    export_dir = Path.home() / ".mapsOS" / "exports"
    if export_dir.exists():
        files = sorted(export_dir.glob("*.json"))
        if files:
            data = json.loads(files[-1].read_text())
            return data
    return {}
```

Display:
```
mapsOS  ● thriving  ·  BODY stable  ·  arcs: [deep-focus] [late-night]  ·  P0: 0 open
[last session: 2026-04-17]                            [cart 303 notes  ·  232 sessions]
```

If no mapsOS data: `mapsOS  ○ not connected  (run: maps)` dimmed.
If cart not initialized: show note count from sqlite directly.

### Keybindings

Implement as `on_key` handler or `BINDINGS`. No Modal dialogs. No palette.

| key | action |
|-----|--------|
| j / ↓ | move cursor down in focused pane |
| k / ↑ | move cursor up in focused pane |
| h / left | focus GraphPane |
| l / right | focus NotePane |
| tab | cycle focus |
| / | activate filter in GraphPane |
| enter | open selected note in $EDITOR (subprocess) |
| n | prompt for new note title at bottom, run `cart new note <title>` |
| m | launch mapsOS (see Task 3 — bidirectional) |
| r | rebuild index (`cart index rebuild`), refresh display |
| b | toggle backlinks panel in NotePane |
| t | show tasks overlay (simple scrollable list from `cart todo list`) |
| q / ctrl+c | quit |
| ? | toggle keybind reference in footer |

Footer (1 line at very bottom, not StateStrip):
Default: `[h/l] panes  [j/k] move  [/] filter  [enter] edit  [m] mapsOS  [q] quit`
Show `[?] for all keys` at right edge.

### App class

```python
class CartTUI(App):
    CSS_PATH = None  # inline CSS only
    TITLE = "atlas"
    
    CSS = """
    GraphPane {
        width: 40%;
        border-right: solid #3a3a3a;
    }
    NotePane {
        width: 60%;
    }
    StateStrip {
        height: 3;
        background: #1a1a1a;
        border-top: solid #3a3a3a;
        color: #c8a96e;
    }
    """
```

Amber CRT theme throughout: background `#0d0d0d`, primary text `#c8a96e`, dim `#5a4a2a`,
highlight `#e8c87e`, muted blue `#7b9eb5`.

---

## TASK 2 — Wire `cart tui` command

In `cartographer/cli.py`, add:

```python
@main.command("tui")
def tui_command() -> None:
    """Launch the atlas TUI."""
    try:
        from .tui import CartTUI
    except ImportError as exc:
        raise click.ClickException(
            "textual is required for the TUI: pip install textual"
        ) from exc
    app = CartTUI()
    app.run()
```

In `pyproject.toml`, add to dependencies:
```
"textual>=0.50.0",
```

---

## TASK 3 — mapsOS bidirectional bridge

### 3a. New file: `~/dev/mapsOS/environments/cart_bridge.py`

```python
# maps · cassette.help · MIT
"""
cart_bridge.py — Bidirectional bridge between mapsOS and cartographer atlas.

All functions degrade gracefully. If cart is unavailable, returns empty/False.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Any


def cart_available() -> bool:
    """Check if cart CLI is on PATH."""
    try:
        r = subprocess.run(["cart", "--help"], capture_output=True, timeout=3)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_open_tasks(priority: str | None = None) -> list[dict]:
    """
    Return open tasks from cart atlas.
    priority: "P0", "P1", etc. or None for all open.
    """
    try:
        expr = f"priority:{priority} status:open" if priority else "status:open"
        r = subprocess.run(
            ["cart", "todo", "query", expr],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            return []
        tasks = []
        for line in r.stdout.strip().splitlines():
            line = line.strip()
            if line:
                tasks.append({"text": line})
        return tasks
    except Exception:
        return []


def get_daily_brief() -> str:
    """Return cart daily-brief output as a string."""
    try:
        r = subprocess.run(
            ["cart", "daily-brief", "--format", "plain"],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def get_recent_sessions(n: int = 3) -> list[dict]:
    """Return N most recent session notes from atlas index."""
    try:
        r = subprocess.run(
            ["cart", "query", "type:agent-log"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            return []
        lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
        return [{"path": p} for p in lines[-n:]]
    except Exception:
        return []


def ingest_export(export_path: str | None = None) -> bool:
    """
    Tell cart to ingest the latest mapsOS export.
    Called automatically on mapsOS TUI exit.
    """
    try:
        if export_path:
            cmd = ["cart", "mapsos", "ingest", export_path]
        else:
            cmd = ["cart", "mapsos", "ingest-exports", "--latest"]
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def push_intention_to_tasks(text: str, priority: str = "P2") -> bool:
    """Write a mapsOS intention as a cart task."""
    try:
        r = subprocess.run(
            ["cart", "todo", "add", text, "-p", priority],
            capture_output=True, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False
```

### 3b. mapsOS TUI changes (`environments/tui.py`)

Find the main `run()` / main loop function (it's near the bottom of tui.py).
Find where the TUI exits (after the main while loop ends or on `q`).

**On exit, add:**
```python
# auto-ingest to cart if available
try:
    from environments.cart_bridge import cart_available, ingest_export
    if cart_available():
        ingest_export()
except Exception:
    pass
```

**Add `C` key handler** in the main key-reading loop (find where `q` is handled):

```python
elif key == "C":
    # launch cart TUI, return to mapsOS on exit
    import subprocess, shutil
    if shutil.which("cart"):
        clr()
        subprocess.run(["cart", "tui"])
        # redraw mapsOS after returning
        clr()
        _draw_banner()
```

**Add cart context panel** — new function `_draw_cart_panel()`:

```python
def _draw_cart_panel() -> None:
    """Show atlas context: open tasks, recent sessions."""
    try:
        from environments.cart_bridge import cart_available, get_open_tasks, get_recent_sessions
    except ImportError:
        _content("[dim]cart not available[/dim]")
        return

    if not cart_available():
        _content("[dim]cart not installed[/dim]")
        return

    con().print(Rule("atlas context", style=AMBER_DIM))
    tasks = get_open_tasks("P0") + get_open_tasks("P1")
    if tasks:
        con().print(Text("open tasks:", style=AMBER_DIM))
        for t in tasks[:8]:
            _content(f"  · {t['text']}")
    else:
        _content("[dim]no open P0/P1 tasks[/dim]")

    sessions = get_recent_sessions(3)
    if sessions:
        con().print(Text("\nrecent sessions:", style=AMBER_DIM))
        for s in sessions:
            _content(f"  ○ {Path(s['path']).stem}")
    con().print(Rule(style=AMBER_DIM))
    _content("[dim]press any key[/dim]")
    _read_key()
```

Add to hotkey bar: `C → atlas` alongside existing keys.

**Find the hotkey display** (around line 545 `_draw_hotkey_bar`) and add `("C", "atlas")` to the pairs list.

---

## TASK 4 — mapsOS config generalization

### 4a. `~/dev/mapsOS/environments/maps_os_config.py`

Add these functions after existing ones:

```python
def load_state_tags(cfg: dict[str, Any]) -> dict[str, str]:
    """
    Returns {tag: description} from config.state.tags.
    Falls back to default mapsOS tag set.
    """
    DEFAULT_TAGS = {
        "surviving": "minimal function, getting through",
        "stable": "neutral baseline",
        "grounded": "anchored, present",
        "thriving": "genuine forward momentum",
        "tender": "emotionally open, soft",
        "grieving": "loss-adjacent",
        "manic": "elevated, fast, possibly unsustainable",
        "depleted": "tank empty",
        "flooded": "overwhelmed, can't process",
        "clear": "sharp, minimal noise",
    }
    state = cfg.get("state", {}) if isinstance(cfg, dict) else {}
    tags = state.get("tags", {}) if isinstance(state, dict) else {}
    if isinstance(tags, dict) and tags:
        return {str(k): str(v) for k, v in tags.items()}
    return DEFAULT_TAGS


def load_capacity_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Returns capacity/survival mode config.
    
    survival_mode: true → "survival mode" label (honest, ND-friendly)
    survival_mode: false → "low capacity mode" label (default for new installs)
    """
    cap = cfg.get("capacity", {}) if isinstance(cfg, dict) else {}
    if not isinstance(cap, dict):
        cap = {}
    
    survival_mode = cap.get("survival_mode", False)  # default: low capacity
    
    if survival_mode:
        mode_label = "survival mode"
        mode_short = "survival"
    else:
        mode_label = cap.get("mode_label", "low capacity")
        mode_short = "low capacity"
    
    return {
        "survival_mode": bool(survival_mode),
        "mode_label": mode_label,
        "mode_short": mode_short,
        "low_states": load_survival_config(cfg)["low_states"],
        "threshold": load_survival_config(cfg)["threshold"],
        "window": load_survival_config(cfg)["window"],
    }


def load_tracks_config(cfg: dict[str, Any]) -> list[dict]:
    """Returns track definitions from config or defaults."""
    DEFAULT_TRACKS = [
        {"name": "BODY", "categories": ["sleep", "pain", "energy", "movement", "food", "substance"]},
        {"name": "MIND", "categories": ["focus", "anxiety", "clarity", "load", "creativity"]},
        {"name": "SPIRIT", "categories": ["connection", "meaning", "play", "solitude", "gratitude"]},
    ]
    tracks = cfg.get("tracks", []) if isinstance(cfg, dict) else []
    if isinstance(tracks, list) and tracks:
        return tracks
    return DEFAULT_TRACKS
```

### 4b. `~/.maps_os_config.yaml` — ship a documented example

Write `~/dev/mapsOS/environments/maps_os_config.example.yaml`:

```yaml
# mapsOS configuration — copy to ~/.maps_os_config.yaml and edit
# all keys are optional — defaults shown

identity:
  name: "maps"                     # used in greetings and session headers
  timezone: "America/Los_Angeles"

state:
  # Customize your state vocabulary. Each tag needs a short description.
  # These are the defaults — change or add freely.
  tags:
    surviving: "minimal function, getting through"
    stable: "neutral baseline, nothing wrong, nothing lit"
    grounded: "anchored, present — active quality distinct from stable"
    thriving: "genuine forward momentum, things clicking"
    tender: "emotionally soft, open, post-connection warmth"
    grieving: "loss-adjacent (person, phase, possibility)"
    manic: "elevated, fast, possibly unsustainable"
    depleted: "tank empty, may still be functional"
    flooded: "overwhelmed, can't process"
    clear: "sharp, minimal noise"
  default: stable

capacity:
  # survival_mode: true  → labels this "survival mode" (honest, ND language)
  # survival_mode: false → labels this "low capacity mode" (default)
  # Built as survival mode for some brains; low capacity for others. Your call.
  survival_mode: false
  low_states: [depleted, grieving, surviving]
  threshold: 3      # sessions in low state before mode activates
  window: 5         # sessions to look back

tracks:
  - name: BODY
    categories: [sleep, pain, energy, movement, food, substance]
  - name: MIND
    categories: [focus, anxiety, clarity, load, creativity]
  - name: SPIRIT
    categories: [connection, meaning, play, solitude, gratitude]
  # Add your own tracks:
  # - name: WORK
  #   categories: [output, meetings, blockers, wins]
  # - name: CREATIVE
  #   categories: [flow, blocks, output, inspiration]

integrations:
  cart:
    enabled: true
    atlas_root: "~/atlas"
    auto_ingest: true        # ingest to atlas on mapsOS exit
    show_tasks: true         # show P0/P1 tasks in dashboard
  nota:
    enabled: false           # optional — cart tasks supersede this over time
  garden:
    enabled: false           # Garden MCP knowledge graph
    graph: "cassette"

ui:
  theme: amber               # amber | phosphor | plain
  splash: true
  logo: true
```

### 4c. Update `tui.py` to use configurable labels

In `tui.py`, find where "survival mode" is displayed as a string. There are roughly 3 spots:
- The capacity mode banner (when active)
- The hotkey description
- Any `_content()` calls that hardcode "survival mode"

Replace hardcoded strings with:
```python
from environments.maps_os_config import load_config, load_capacity_config
_cap = load_capacity_config(load_config())
CAPACITY_LABEL = _cap["mode_label"]        # "survival mode" or "low capacity"
CAPACITY_SHORT = _cap["mode_short"]
```

Then use `CAPACITY_LABEL` / `CAPACITY_SHORT` in display strings instead of literals.

Do this at module level so it loads once.

---

## TASK 5 — DEVELOPERS.md (new file in cartographer repo)

Create `~/dev/cartographer/DEVELOPERS.md`:

```markdown
# DEVELOPERS.md
# maps · cassette.help · MIT

## this is infrastructure. what are you going to build?

cartographer + mapsOS started as one person's attempt to make their tools
actually know them — their projects, their history, their state.

The result is a local-first knowledge graph with a qualitative life OS
sitting underneath it. Everything agent-aware. Everything configurable.
Everything yours.

Now it's yours to build on.

---

## the plugin API (30 seconds)

Any executable that reads JSON on stdin and writes JSON on stdout is a plugin.

```json
// stdin
{
  "command": "my-plugin",
  "args": {"option": "value"},
  "notes": [{"id": "project-alpha", "content": "..."}]
}

// stdout
{
  "output": "result text",
  "writes": [{"path": "agents/my-agent/output.md", "content": "..."}],
  "errors": []
}
```

Drop it in `.cartographer/plugins/`. Run with `cart plugin run my-plugin`.
Python, shell, Rust, Lua — anything that speaks JSON.

---

## things you could build

**For neurodivergent communities:**
A mapsOS profile tuned for ADHD hyperfocus cycles, autism sensory load,
bipolar energy tracking, BPD emotional intensity. Different state vocabulary.
Different arc definitions. Different capacity thresholds. Same substrate.

**For teams:**
A shared atlas where multiple engineers' agents all write session logs to the
same knowledge graph. Entity notes for shared concepts. Cross-agent backlinks.
A `cart query` that answers "what did any agent learn about this component?"

**For researchers:**
Every paper you read becomes a note. Every quote is a block reference.
`cart query 'tag:paper links:transformer-architecture'` returns your reading list.
Your agent's session logs link to the papers that informed them.

**For therapists / coaches:**
Session notes accumulate into entity profiles. Patterns surface automatically.
`cart mapsos patterns --field state` across clients (with consent). No cloud.
No vendor. Files on your machine.

**For ops teams:**
Incident reports are notes. Runbooks are notes. Every incident links to the
entities and projects it touched. Backlinks show you which runbook sections
were consulted during which incidents. Post-mortems write themselves.

**For anyone building with LLMs:**
Your agents forget everything when the context window closes. cartographer is
what they leave behind. Session import means every conversation accumulates
into a queryable graph. `cart daily-brief` seeds the next session from the last.
Your AI tools get smarter because they actually remember.

---

## extension points

| surface | how |
|---------|-----|
| Plugins | executable in `.cartographer/plugins/` |
| Templates | Jinja2 in `.cartographer/jinja/` |
| Hooks | shell scripts in `.cartographer/hooks/` |
| mapsOS tracks | `tracks:` in `~/.maps_os_config.yaml` |
| mapsOS state vocab | `state.tags:` in config |
| mapsOS arcs | custom patterns in config (coming) |
| Agent adapters | `cart session-import` reads any agent that writes the ECC session format |

---

## the ethos

This was built for one brain, configured for that brain's specific needs.
The whole point is that you configure it for yours.

In a month, the first community config drops and someone else's brain
works better because of it. In a year, someone's building something
we haven't imagined on top of this substrate.

That's the goal. Come build.

→ [github.com/nosleepcassette/cartographer](https://github.com/nosleepcassette/cartographer)
→ [github.com/nosleepcassette/mapsOS](https://github.com/nosleepcassette/mapsOS)
```

---

## TASK 6 — README rewrites

### cartographer README.md

**Replace the current README with this lead section** (keep the command reference, replace everything before "## current status"):

```markdown
# cartographer

> Your agents should know how you're actually doing — and remember everything they learn.

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

- **Agent memory persists.** Session import turns context windows into a
  growing graph. `cart daily-brief` seeds tomorrow's session from everything
  that happened today.

- **Files are the API.** Delete cartographer. Your notes are still readable
  Markdown with YAML frontmatter. Git is the database. SQLite is an index,
  not a prison.

- **Block-addressable by default.** `[[note-id#block-id]]` transclusion.
  Backlinks tracked automatically. The relational layer Obsidian promised
  but never fully delivered.

- **Imports are idempotent.** Run `cart session-import` a hundred times.
  Zero duplicates. Just an always-current graph.

- **Built for neurodivergent workflows.** Qualitative state tracking,
  capacity-aware context, honest about when you're not okay.
  Paired with mapsOS. Configurable for any brain.

- **Plugin economy.** stdin/stdout JSON contract. If it speaks that, it joins.
  The long-term goal is Vim-scale extensibility.

---
```

Then keep existing sections from "## current status" onward, updated with latest features.

### mapsOS README.md

Replace the "Why this exists" section opener with:

```markdown
## why this exists

Most life-tracking tools assume you have capacity.
mapsOS doesn't.

It tracks qualitative state — not scores, not percentages — and adjusts
what it asks of you based on where you actually are. Built during a period
of genuine crisis, by someone for whom "surviving" is a real state that
needed a name.

That origin is why it works better than most tools even when things are fine.
It was tested at the edges first.

---

**Built for one brain, configured for yours.**

Every state tag is configurable. Every track dimension is configurable.
"Survival mode" is what it's called by default — but if that language
doesn't fit your situation, a single config line turns it into
"low capacity mode." Your call. Your vocabulary.

The state vocabulary ships with 10 tags that cover a lot of human experience.
Replace them all. Add your own. Build a profile for your specific neurodivergent
pattern. Share it with your community.

→ See `~/.maps_os_config.yaml` and [DEVELOPERS.md](../cartographer/DEVELOPERS.md)
```

---

## TASK 7 — Commit plan

### cartographer
```zsh
cd ~/dev/cartographer
git add cartographer/tui.py cartographer/cli.py pyproject.toml \
        BUILDSHEET.md OPENCODE_IMPL_SPEC.md DEVELOPERS.md README.md \
        AGENT_ONBOARDING.md
git commit -m "feat: TUI, mapsOS bidirectional bridge, graph navigation, transclusion, config generalization, developer CTA"
git push
```

### mapsOS
```zsh
cd ~/dev/mapsOS
git add environments/cart_bridge.py environments/tui.py \
        environments/maps_os_config.py environments/maps_os_config.example.yaml \
        README.md
git commit -m "feat: cart bidirectional bridge, config generalization, capacity mode label, atlas context strip"
git push
```

---

## SMOKE TESTS (run before committing)

```zsh
# cartographer
cd ~/dev/cartographer
python3 -m pytest tests/ -x -q           # must be 14/14
cart tui                                 # must launch without crash
# navigate with j/k, press /, press m, press q

# mapsOS  
cd ~/dev/mapsOS
python3 -m pytest tests/ -x -q           # must be 174/174
maps                                     # launch TUI
# press C — should launch cart tui
# press q in cart tui — should return to mapsOS
# press q in mapsOS — cart should auto-ingest
```

---

## WHAT TO DEFER (do not build in this pass)

- Force-directed graph rendering (v2 sprint)
- Init wizard / state vocabulary intake flow
- nota as optional backend for cart tasks
- `cart mapsos push-tasks` write-back (bidirectional task sync)
- mapsOS arc pattern customization via config
- Graph path queries (`cart graph path a → b`)
- Multi-user / shared atlas
- Any network features

---

## IF YOU HIT YOUR LIMIT

Update the task list in BUILDSHEET.md before stopping:
- Mark completed tasks ✓
- Mark in-progress task with current state
- Add a note in the changelog row

Next agent reads BUILDSHEET.md → OPENCODE_IMPL_SPEC.md → picks up at first ⬜.
