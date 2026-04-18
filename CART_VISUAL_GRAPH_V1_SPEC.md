# cartographer — Visual Graph V1
# maps · cassette.help · MIT
# generated: 2026-04-17
# status: BUILT

---

## goal

Ship the first real visual knowledge graph for atlas without adding a web stack or third-party JS dependency.

This is not a graph-native editor. It is a local export surface that makes the atlas legible as a network.

---

## shipped surface

```zsh
cart graph --format html
cart graph --format html --open
```

Default output path:

- `~/atlas/graph-view.html` for HTML
- `~/atlas/graph-export.json` for JSON

---

## v1 capabilities

- interactive SVG graph rendered from the atlas SQLite index
- node colors by note type
- node size scaled by graph degree
- pan and zoom
- drag nodes
- local search by id, title, type, or tags
- detail pane with metadata and linked neighbors
- fully local output: one self-contained HTML file

---

## design constraints

- no CDN
- no build step
- no extra Python dependency
- keep JSON export working for downstream tooling

---

## non-goals

- no live editing inside the graph
- no real-time sync
- no force-directed TUI inside Textual yet
- no thousand-node performance guarantees beyond "works for a real atlas"

---

## likely v2 upgrades

- open-note links back into the filesystem or editor
- degree/type filters
- focused subgraph mode from a note id
- timeline/session-only lenses
- cluster collapse by type, project, or agent
- TUI handoff into the visual graph
