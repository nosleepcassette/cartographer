# BUILDSHEET — cartographer + mapsOS big push
# maps · cassette.help · MIT
# session: 2026-04-17
# owner: vesper/claude (handover to codex if limit hit)

---

## goal

Ship a genuinely impressive public release of cartographer + mapsOS together:
- Textual TUI with graph navigation, note viewer, block transclusion
- Full bidirectional mapsOS ↔ cart integration
- mapsOS fully generalized (configurable state tags, dimensions, capacity labels)
- Task management built into cart (nota not required, eventually supersedes it)
- Developer-facing framing: atlas as orchestrator infrastructure, call to build on it
- Both READMEs rewritten around pitch sentence, not feature lists

---

## the pitch sentence

> Your agents should know how you're actually doing — and remember everything they learn.

- cartographer = agent memory that persists across sessions
- mapsOS = qualitative state that's honest about capacity
- atlas = the substrate that makes all tools smarter

Community insight (Discord, unprompted): "maybe under an orchestrator project (atlas?)" — 
someone independently arrived at the architecture. Lead with this.

---

## architecture decisions (LOCKED — confirmed by maps 2026-04-17)

1. TUI is Textual (already installed: 8.2.3), not urwid. No palette. Vim keys + footer hints only.
2. Graph pane: structured ASCII adjacency this pass. Force-directed is v2 sprint.
3. Both TUIs are standalone AND toggle into each other:
   - `m` in cart TUI → launches mapsOS, full terminal handoff, auto-ingest on exit
   - `C` in mapsOS TUI → launches cart TUI, full terminal handoff
   - Neither requires the other. Progressive enhancement.
4. nota is deprecated as a dependency. cart todo supersedes it over time.
   nota may remain as optional backend but nobody else will use it. Build native.
5. mapsOS state tags fully configurable via ~/.maps_os_config.yaml
6. Capacity mode label: TOGGLE in config (survival_mode: true/false).
   - true → "survival mode" (honest, ND-friendly, what maps uses)
   - false → "low capacity mode" (professional, less dire)
   - Default: false (low capacity) for new installs
   - README caveat: "built as survival mode for some brains, low capacity for others"
   - Future: init wizard that helps you pick your state vocabulary (out of scope now)
7. Plugin economy: stdin/stdout JSON contract. Vim ecosystem scale is the north star.
   In a month: first community plugin. In a year: someone plays doom in it.
8. Ethos: "built for my brain, configure for yours."
   Everything configurable, surface area only grows.
9. Schema frontmatter frozen at v1 after this push.
10. DEVELOPERS.md ships: "here's the infrastructure, here's what YOU build on it."
11. Both READMEs: no specific names/projects, pitch sentence first, CTA for devs.

---

## task list

| # | task | status | file(s) |
|---|------|--------|---------|
| 1 | BUILDSHEET.md | ✓ done | this file |
| 2 | cart TUI — Textual app | ✓ done | cartographer/tui.py |
| 3 | cart tui CLI command | ✓ done | cartographer/cli.py |
| 4 | textual dep in pyproject.toml | ✓ done | pyproject.toml |
| 5 | mapsOS cart_bridge.py | ✓ done | ~/dev/mapsOS/environments/cart_bridge.py |
| 6 | mapsOS TUI cart strip | ✓ done | ~/dev/mapsOS/environments/tui.py |
| 7 | cart mapsos write-back commands | deferred | cartographer/mapsos.py + cli.py |
| 8 | mapsOS config schema generalization | ✓ done | ~/dev/mapsOS/environments/maps_os_config.py + .yaml |
| 9 | cartographer README rewrite | ✓ done | README.md |
| 10 | mapsOS README rewrite | ✓ done | ~/dev/mapsOS/README.md |
| 11 | developer CTA doc | ✓ done | DEVELOPERS.md |
| 12 | commit + push both repos | not done | — |

Task 7 remained deferred on purpose because `OPENCODE_IMPL_SPEC.md` explicitly lists `cart mapsos push-tasks` in the "WHAT TO DEFER" section for this pass.

---

## TUI spec (task 2)

### layout

```
┌─ ATLAS ────────────────────────────────────────────────────────────┐
│ ┌─ GRAPH (40%) ────────────────┐ ┌─ NOTE (60%) ──────────────────┐ │
│ │                              │ │                                 │ │
│ │  ● hopeagent ─── ● chris     │ │ # [note title]                 │ │
│ │  │                           │ │ type: project  status: active  │ │
│ │  ●─── ● nhi                  │ │                                 │ │
│ │  cartographer                │ │ [note body, markdown rendered] │ │
│ │       │                      │ │                                 │ │
│ │  ● mapsOS ─── ● nota         │ │ ─── backlinks ──────────────── │ │
│ │                              │ │ ← hopeagent (2 refs)           │ │
│ │  [j/k] move  [/] filter      │ │ ← nhi (1 ref)                  │ │
│ │  [enter] open  [tab] pane    │ │                                 │ │
│ └──────────────────────────────┘ └─────────────────────────────────┘│
│ ┌─ STATE STRIP ──────────────────────────────────────────────────────┐│
│ │ mapsOS ● thriving · BODY stable · arcs: [deep-focus]  P0: 0 open ││
│ └────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
```

### keybindings (no palette)

| key | action |
|-----|--------|
| j/k | move cursor in focused pane |
| h/l | switch pane focus |
| tab | cycle pane focus |
| / | open filter bar (graph) |
| enter | open note in $EDITOR |
| n | new note prompt |
| m | launch mapsOS (subprocess), auto-ingest on exit |
| r | refresh atlas index |
| b | toggle backlinks panel in note pane |
| t | show tasks overlay |
| q | quit |
| ? | show keybind reference in footer |

### graph render approach

- Load nodes from SQLite index (id, title, type, tags)
- Load edges from block_refs table  
- Group by type: projects row, entities row, sessions row (most recent 10)
- Show edges as: ● node ─── ● connected-node
- Filter hides non-matching, shows match + 1-hop neighbors
- Selected node → right pane updates
- Node type colors: project=#c47c7c, entity=#7ab87e, session=#7b9eb5, daily=#9e6ba8

### transclusion rendering

- Parse ![[note-id]] and ![[note-id#block-id]] in note body
- Replace with dimmed, indented block content from atlas
- Visual indicator: `┊ [transcluded from [[note-id]]]`

---

## mapsOS bidirectional bridge spec (task 5+6)

### cart → mapsOS direction (new)

file: `~/dev/mapsOS/environments/cart_bridge.py`

```python
def cart_available() -> bool  # checks cart CLI on PATH
def get_open_tasks(priority: str = None) -> list[dict]  # reads cart todo list
def get_daily_brief() -> str  # runs cart daily-brief, returns text
def get_recent_sessions(n: int = 3) -> list[dict]  # reads atlas session index
def push_intention(text: str, category: str = "mind") -> bool  # cart task → mapsOS intention
```

mapsOS TUI changes:
- Bottom of dashboard: "atlas context" strip — P0 open tasks count, last session date
- `C` key in mapsOS TUI → shows cart context panel (recent sessions, open P0/P1 tasks)
- On mapsOS exit → runs `cart mapsos ingest-exports --latest` if cart available

### mapsOS → cart direction (existing, extend)

Already works: `maps export` → `cart mapsos ingest-exports --latest`

New: `cart mapsos push-tasks` — reads mapsOS intentions log, writes to cart tasks/mapsos.md
     (bidirectional sync of intention→task and task→intention)

---

## mapsOS config generalization spec (task 8)

### ~/.maps_os_config.yaml full schema

```yaml
# mapsOS configuration
# all keys optional — defaults shown

identity:
  name: "maps"                    # your name, used in greetings
  timezone: "America/Los_Angeles"

state:
  tags:                           # fully configurable state vocabulary
    surviving: "minimal function, getting through"
    stable: "neutral baseline"
    grounded: "anchored, present"
    thriving: "genuine forward momentum"
    tender: "emotionally open"
    grieving: "loss-adjacent"
    manic: "elevated, fast"
    depleted: "tank empty"
    flooded: "overwhelmed, can't process"
    clear: "sharp, minimal noise"
  default: "stable"

capacity:
  mode_label: "low capacity"      # what to call survival mode (configurable)
  low_states: [depleted, grieving, surviving]
  threshold: 3                    # sessions in low state before mode activates
  window: 5                       # sessions to look back

tracks:
  - name: BODY
    categories: [sleep, pain, energy, movement, food, substance]
  - name: MIND
    categories: [focus, anxiety, clarity, load, creativity]
  - name: SPIRIT
    categories: [connection, meaning, play, solitude, gratitude]

  # add your own:
  # - name: WORK
  #   categories: [output, meetings, blockers, wins]

arcs:
  enabled: true
  max_active: 5
  # define custom arc patterns:
  # patterns:
  #   - name: "crunch-mode"
  #     signals: [focus:hyper, sleep:none, energy:depleted]

integrations:
  cart:
    enabled: true
    atlas_root: "~/atlas"         # where your atlas lives
    auto_ingest: true             # ingest to cart on exit
    show_tasks: true              # show cart P0 tasks in dashboard
  nota:
    enabled: false                # nota integration (optional)
  garden:
    enabled: false                # garden MCP integration (optional)
    graph: "cassette"

ui:
  theme: amber                    # amber | phosphor | trans | lesbian | plain
  splash: true
  logo: true
```

### what this unlocks

- Someone with different neurodivergent profile → different state tags
- Someone without survival-mode context → different label, different thresholds
- Teams using mapsOS together → different track categories
- Developers extending it → custom arcs, custom tracks

### hardcoded to config migration targets

- tui.py: STATE_COLORS dict → read from config + defaults
- tui.py: survival mode label → read from config.capacity.mode_label
- vent_parser.py: VALID_STATE_TAGS → read from config.state.tags keys
- survival_mode.py: low_states → read from config.capacity.low_states

---

## developer CTA framing

file: DEVELOPERS.md (cartographer repo)

Key message: this is infrastructure. Here's what you could build on it:

- A neurodiversity-specific life OS (different arcs, different state vocab, different capacity model)
- A team knowledge graph where multiple people's agents write to shared atlas
- A research assistant where every paper you read gets block-referenced and linked
- A therapist tool where session notes accumulate into patterns over months
- An agent evaluation harness where you track how your agents perform over time
- A CRM where every customer interaction becomes a linked entity note
- An ops runbook system where incidents link to entities, tags, learnings

Plugin API is the hook: if it reads stdin and writes stdout JSON, it joins.

---

## commit plan

### cartographer
```
git add cartographer/tui.py cartographer/cli.py pyproject.toml BUILDSHEET.md DEVELOPERS.md README.md
git commit -m "feat: TUI, mapsOS bidirectional bridge, graph navigation, transclusion scaffold"
git push
```

### mapsOS
```
git add environments/cart_bridge.py environments/tui.py environments/maps_os_config.py environments/maps_os_config.yaml README.md
git commit -m "feat: cart bidirectional bridge, full config generalization, atlas context strip"
git push
```

---

## handover instructions (for codex or next agent)

If picking this up mid-session:

1. Read this file
2. Read ~/dev/cartographer/AGENT_ONBOARDING.md
3. Run `cart status` to see current atlas state
4. Check task list above — find first ⬜ pending item
5. Key files:
   - cartographer/tui.py — NEW, the Textual TUI
   - cartographer/cli.py — add `cart tui` command
   - cartographer/mapsos.py — extend for write-back
   - ~/dev/mapsOS/environments/cart_bridge.py — NEW, bidirectional bridge
   - ~/dev/mapsOS/environments/tui.py — add cart strip + C-key
   - ~/dev/mapsOS/environments/maps_os_config.py — generalize
6. Smoke test: `cart tui` should launch without crashing
7. Smoke test: `maps` → `C` → should show cart context panel
8. No Co-Authored-By. No git push from Claude Code (vesper may push, codex may push).

---

## changelog

| date | agent | what |
|------|-------|------|
| 2026-04-17 | vesper | buildsheet written, tasks created |

(agents: append here as you complete tasks)
