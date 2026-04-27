# Emotional Topology Plugin

**Version:** 0.1.0
**Author:** wizard, cassette
**Extends:** emotional-topology profile
**Type:** graph-rendering plugin for cartographer

---

## What This Does

Person-to-person wires in the atlas graph all render as "relates to person" — 26 identical labels that convey zero emotional information. This plugin fixes that by:

1. **Love spectrum predicates** with visual mapping (color + thickness per tier)
2. **Predicate + note snippet** as the default wire label
3. **Directional edge styling** — asymmetric relationships rendered as two directed edges
4. **Edge grouping** when a node has many person-wires (collapsible bundles)
5. **Hover-to-expand** for full wire provenance (author, method, confidence, review status)
6. **Three-tier privacy** per wire (public / inner-circle / private)
7. **Emotional styling toggle** (`E` key, default OFF, per-session)
8. **Template hook system** for clean plugin injection into the graph renderer

## Plugin Structure

```
cartographer/plugins/emotional-topology/
├── plugin.toml              # metadata, hooks, config
├── predicates.toml          # love spectrum + person predicates + state modifiers
├── graph_extensions.py      # wire styling logic (thickness, color, grouping)
├── privacy.py               # three-tier privacy layer
├── ui_extensions.py         # hover-to-expand, E key toggle, edge grouping JS/CSS
├── templates/
│   ├── wire_label.html      # partial: predicate + note snippet rendering
│   ├── wire_styling.html    # partial: edge color/thickness/direction
│   ├── wire_expand.html     # partial: hover/click provenance detail
│   ├── privacy_controls.html # partial: per-wire privacy dropdown
│   └── emotional_toggle.html # partial: E key toggle + status indicator
└── README.md                # this file
```

## Love Spectrum Predicates

Ordered by intensity — position determines default thickness:

| Predicate    | Label         | Thickness | Color          | Hex     | Description                                    |
|-------------|---------------|-----------|----------------|---------|------------------------------------------------|
| crushing_on | crushing on   | 1         | violet         | #a78bfa | Low-key attraction, may not be fully admitted  |
| smitten     | smitten       | 2         | rose           | #f43f5e | High chemistry, wanting-without-having         |
| in_love     | in love       | 3         | amber          | #f59e0b | Deep, established romantic love with history   |
| loves       | loves         | 2         | stone          | #78716c | Deep affection, may be formerly romantic       |
| loved       | loved         | 1         | stone-light    | #a8a29e | Settled affection, no bad blood, both moved on |
| cherishes   | cherishes     | 1         | stone          | #78716c | Quiet, settled love — no longer active         |

## Non-Love Person Predicates

| Predicate    | Label         | Thickness | Color    | Hex     |
|-------------|---------------|-----------|----------|---------|
| works_with  | works with    | 1         | blue     | #3b82f6 |
| avoids      | avoids        | 1         | red      | #ef4444 |
| ghosted     | ghosted       | 1         | zinc     | #71717a |
| friends_with| friends with  | 1         | emerald  | #10b981 |
| family      | family        | 2         | teal     | #14b8a6 |
| relates_to  | relates to    | 1         | zinc     | #71717a |

## State Modifiers

Applied on top of a base predicate. Add suffix to label + visual overlay:

| Modifier          | Suffix            | Visual                |
|-------------------|-------------------|-----------------------|
| separated         | separated         | dot-dash overlay      |
| wants_reunion     | wants reunion     | arrowhead emphasis    |
| formerly_romantic | formerly romantic | faded endpoint        |
| unexplored        | unexplored        | question mark         |

## Wire Label Format

`{predicate} · {state_modifier} · {note_snippet}`

Examples:
- `in love · separated · wants reunion · ex-partner` → grungler
- `smitten · unexplored · still thinking about it` → chungus
- `loves · formerly romantic · once love of life` → another-person
- `loved · formerly romantic` → old-flame
- `crushing on · unexplored` → someone-new
- `works with · co-founder` → collaborator
- `relates to` → fallback (no predicate defined)

Fallback chain: predicate+modifiers+note → predicate+modifiers → note only → "relates to person"

## Privacy Tiers

| Tier          | Wire visible | Styling visible | Label              | Hover detail       |
|---------------|-------------|-----------------|--------------------|--------------------|
| public        | yes         | yes (if toggle) | predicate only     | none               |
| inner-circle  | yes         | yes (if toggle) | predicate + note   | full provenance    |
| private       | no          | no              | —                  | —                  |

Privacy is **separate** from the emotional styling toggle.

## Emotional Styling Toggle

- **Default: OFF** — all edges render as neutral gray (#71717a), uniform 1px
- Toggle with `E` key in graph view
- Per-session, **NOT sticky** — reverts to OFF on page load
- Status badge: bottom-right corner `🔒 emotional: off` / `🔓 emotional: on`

## Dash Patterns

Reserved for review status ONLY (not overloaded for intensity):
- **solid** = reviewed
- **dashed** = unreviewed

## Template Hooks

The base graph HTML defines insertion points:

```html
<!-- PLUGIN_HOOK:wire_label -->
<!-- PLUGIN_HOOK:wire_styling -->
<!-- PLUGIN_HOOK:edge_rendering -->
<!-- PLUGIN_HOOK:privacy_controls -->
<!-- PLUGIN_HOOK:toolbar -->
```

Server-side hooks use HTML comments. Client-side hooks use `data-plugin-hook` attributes
(because comment hooks get stripped by minifiers and can't be queried from JS).

Resolution order: **plugin partial → user override → default content**

## CLI Integration

```bash
# Set privacy on a wire
cart wire privacy <wire_id> --tier inner-circle

# Launch graph with this plugin loaded
cart graph --serve --plugin emotional-topology

# Auto-load when using the emotional-topology profile
cart profile apply emotional-topology
```

## Python API

```python
from cartographer.plugins.emotional_topology.graph_extensions import (
    compute_emotional_edges,
    format_wire_label,
    resolve_edge_style,
)
from cartographer.plugins.emotional_topology.privacy import (
    apply_privacy_filter,
    PrivacyTier,
    set_wire_privacy,
)
from cartographer.plugins.emotional_topology.ui_extensions import (
    inject_ui_extensions,
)

# Compute styled edges for the graph renderer
result = compute_emotional_edges(wires, emotional_styling_on=True)

# Format a single label
label = format_wire_label(predicate="in_love", state_modifiers=["separated", "wants_reunion"], note_snippet="ex-partner")

# Apply privacy filter
visible = apply_privacy_filter(edges, viewer_tier=PrivacyTier.PUBLIC)

# Get CSS + JS for injection
ui = inject_ui_extensions()
```

## Configuration (plugin.toml)

| Key                       | Default  | Description                                      |
|---------------------------|----------|--------------------------------------------------|
| grouping_threshold        | 5        | Wires per node before grouping kicks in          |
| default_privacy           | public   | Privacy tier for new person-to-person wires      |
| emotional_styling_default | false    | Whether emotional styling starts on (always OFF) |

---

*Spec and build: wizard + cassette — 2026-04-22/23*
