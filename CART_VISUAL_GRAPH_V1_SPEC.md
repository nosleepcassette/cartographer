# cartographer — Visual Graph V1
# maps · cassette.help · MIT
# generated: 2026-04-18
# status: BUILT

---

## goal

Ship the first real visual knowledge graph for atlas without adding a web stack, build step, or browser dependency beyond a local HTML export.

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

## shipped capabilities

- self-contained Three.js 3D graph export rendered directly from the atlas SQLite index
- Firefox-safe local-file rendering with vendored JS and no CDN dependency
- deterministic clustered layout with type-aware anchors instead of free-floating SVG drift
- node colors by note type and node size scaled by graph degree
- semantic wire edges visually separated from plain wikilinks
- local search by id, title, type, or tags
- type browser, hide/show type controls, session hiding, and anonymized labels
- smarter auto-fit that prefers search matches, the active type lens, or the selected node neighborhood
- keyboard navigation for search, traversal, camera reset, session toggle, wire toggle, and recentring
- detail pane with metadata, linked neighbors, recent sessions, and markdown-rendered previews
- PNG export, JSON export, and shareable camera/filter state in the URL hash
- fully local output: one self-contained HTML file

---

## design constraints

- no CDN
- no build step
- no extra Python dependency
- keep JSON export working for downstream tooling
- work from `file://` in Firefox as well as Chromium-family browsers

---

## non-goals

- no live editing inside the graph
- no real-time sync
- no graph embedded back into the Textual TUI
- no thousand-node performance guarantees beyond "works for a real atlas"

---

## likely v2 upgrades

- editor-deep-link support beyond `file://` paths
- richer markdown preview surfaces like callouts, nested tables, and transclusion expansion
- focused subgraph URLs from a note id or query
- timeline/session-only lenses
- larger-atlas layout tuning and browser FPS profiling for 500+ note graphs
- cluster collapse by type, project, or agent
