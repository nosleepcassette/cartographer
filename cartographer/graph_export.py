from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from .wires import VALID_WIRE_PREDICATES


TYPE_COLORS = {
    "project": "#d97757",
    "entity": "#6cb88f",
    "agent-log": "#7aa6d9",
    "session": "#7aa6d9",
    "daily": "#d08bd7",
    "learning": "#d5b06b",
    "note": "#b6c2cf",
}


def _alias_map(atlas_root: Path, note_rows: list[sqlite3.Row]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for row in note_rows:
        note_id = str(row["id"])
        aliases[note_id] = note_id
        raw_path = str(row["path"] or "").strip()
        if not raw_path:
            continue
        try:
            relative = Path(raw_path).resolve().relative_to(atlas_root.resolve())
        except ValueError:
            continue
        aliases[relative.with_suffix("").as_posix()] = note_id
    return aliases


def load_graph_payload(atlas_root: Path) -> dict[str, Any]:
    db_path = atlas_root / ".cartographer" / "index.db"
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        note_rows = connection.execute(
            """
            SELECT id, path, title, type, status, tags, links, modified
            FROM notes
            ORDER BY type ASC, id ASC
            """
        ).fetchall()
        ref_rows = connection.execute(
            """
            SELECT DISTINCT from_note, to_note
            FROM block_refs
            WHERE from_note != to_note
            ORDER BY from_note ASC, to_note ASC
            """
        ).fetchall()
        wire_rows = connection.execute(
            """
            SELECT source_note, target_note, predicate, bidirectional
            FROM wires
            ORDER BY source_note ASC, target_note ASC, predicate ASC
            """
        ).fetchall()
    finally:
        connection.close()

    aliases = _alias_map(atlas_root, note_rows)
    edge_pairs: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}
    unresolved_edge_count = 0
    for row in note_rows:
        source = aliases.get(str(row["id"]))
        if source is None:
            continue
        try:
            links = json.loads(row["links"]) if row["links"] else []
        except Exception:
            links = []
        if not isinstance(links, list):
            continue
        for target in links:
            target_id = aliases.get(str(target).strip())
            if target_id is None or target_id == source:
                if target_id is None:
                    unresolved_edge_count += 1
                continue
            edge_pairs[(source, target_id, "wikilink", None)] = {
                "source": source,
                "target": target_id,
                "kind": "wikilink",
            }

    for row in ref_rows:
        source = aliases.get(str(row["from_note"]).strip())
        target = aliases.get(str(row["to_note"]).strip())
        if source is None or target is None:
            unresolved_edge_count += 1
            continue
        if source == target:
            continue
        edge_pairs[(source, target, "wikilink", None)] = {
            "source": source,
            "target": target,
            "kind": "wikilink",
        }

    valid_predicates = set(VALID_WIRE_PREDICATES)
    wire_count = 0
    for row in wire_rows:
        predicate = str(row["predicate"] or "").strip()
        if predicate not in valid_predicates:
            continue
        source = aliases.get(str(row["source_note"]).strip())
        target = aliases.get(str(row["target_note"]).strip())
        if source is None or target is None:
            unresolved_edge_count += 1
            continue
        if source == target:
            continue
        edge_pairs[(source, target, "wire", predicate)] = {
            "source": source,
            "target": target,
            "kind": "wire",
            "predicate": predicate,
            "bidirectional": bool(row["bidirectional"]),
        }
        wire_count += 1

    edges = [
        edge_pairs[key]
        for key in sorted(edge_pairs)
    ]
    degree_counts: Counter[str] = Counter()
    for edge in edges:
        degree_counts.update((str(edge["source"]), str(edge["target"])))

    nodes: list[dict[str, Any]] = []
    type_counts: Counter[str] = Counter()
    for row in note_rows:
        note_type = str(row["type"] or "note")
        type_counts[note_type] += 1
        try:
            tags = json.loads(row["tags"]) if row["tags"] else []
        except Exception:
            tags = []
        node_id = str(row["id"])
        nodes.append(
            {
                "id": node_id,
                "title": str(row["title"] or node_id),
                "type": note_type,
                "status": None if row["status"] is None else str(row["status"]),
                "path": str(row["path"]),
                "tags": tags if isinstance(tags, list) else [],
                "modified": float(row["modified"] or 0.0),
                "degree": degree_counts.get(node_id, 0),
                "color": TYPE_COLORS.get(note_type, TYPE_COLORS["note"]),
            }
        )

    return {
        "generated": date.today().isoformat(),
        "atlas_root": str(atlas_root),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "wire_count": wire_count,
        "unresolved_edge_count": unresolved_edge_count,
        "type_counts": dict(sorted(type_counts.items())),
        "nodes": nodes,
        "edges": edges,
    }


def render_graph_html(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>atlas graph</title>
  <style>
    :root {{
      --bg: #0a0b0f;
      --panel: rgba(18, 20, 28, 0.92);
      --panel-border: rgba(233, 196, 106, 0.18);
      --text: #f3e8d0;
      --muted: #9f9688;
      --accent: #e9c46a;
      --accent-strong: #f4a261;
      --line: rgba(255, 255, 255, 0.1);
      --grid: rgba(255, 255, 255, 0.03);
      --surface: rgba(255, 255, 255, 0.02);
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; margin: 0; }}
    body {{
      background:
        radial-gradient(circle at top left, rgba(233, 196, 106, 0.09), transparent 24rem),
        radial-gradient(circle at bottom right, rgba(122, 166, 217, 0.1), transparent 28rem),
        linear-gradient(180deg, #0a0b0f 0%, #11141c 100%);
      color: var(--text);
      font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
      overflow: hidden;
    }}
    .app {{
      display: grid;
      grid-template-columns: 22rem 1fr 20rem;
      height: 100%;
      gap: 0.85rem;
      padding: 0.85rem;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--panel-border);
      border-radius: 1rem;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
      backdrop-filter: blur(10px);
    }}
    .sidebar, .detail {{
      display: flex;
      flex-direction: column;
      min-height: 0;
    }}
    .sidebar {{
      padding: 1rem;
      gap: 1rem;
    }}
    .graph-wrap {{
      position: relative;
      overflow: hidden;
    }}
    .detail {{
      padding: 1rem;
      gap: 0.85rem;
    }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{
      font-family: "Baskerville", "Iowan Old Style", serif;
      font-size: 1.75rem;
      letter-spacing: 0.02em;
      color: var(--accent);
    }}
    .eyebrow {{
      color: var(--muted);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.16em;
    }}
    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.7rem;
    }}
    .stat {{
      background: var(--surface);
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 0.8rem;
      padding: 0.8rem;
    }}
    .stat strong {{
      display: block;
      font-size: 1.35rem;
      color: var(--accent);
    }}
    .label {{
      display: block;
      color: var(--muted);
      font-size: 0.8rem;
      margin-top: 0.2rem;
    }}
    .search-wrap {{
      display: grid;
      gap: 0.45rem;
    }}
    input[type="search"] {{
      width: 100%;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(0, 0, 0, 0.25);
      color: var(--text);
      border-radius: 0.75rem;
      padding: 0.75rem 0.9rem;
      outline: none;
    }}
    input[type="search"]:focus {{
      border-color: rgba(233, 196, 106, 0.45);
      box-shadow: 0 0 0 4px rgba(233, 196, 106, 0.08);
    }}
    .controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      align-items: center;
    }}
    button {{
      border: 0;
      border-radius: 999px;
      padding: 0.55rem 0.9rem;
      background: linear-gradient(135deg, rgba(233, 196, 106, 0.22), rgba(244, 162, 97, 0.2));
      color: var(--text);
      cursor: pointer;
    }}
    button:hover {{
      filter: brightness(1.08);
    }}
    label.toggle {{
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      color: var(--muted);
      font-size: 0.86rem;
    }}
    .legend {{
      display: grid;
      gap: 0.45rem;
      max-height: 16rem;
      overflow: auto;
      padding-right: 0.25rem;
    }}
    .legend-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 0.6rem;
      padding: 0.45rem 0.55rem;
      border-radius: 0.7rem;
      background: rgba(255, 255, 255, 0.02);
    }}
    .legend-row.active {{
      border: 1px solid rgba(233, 196, 106, 0.26);
      background: rgba(233, 196, 106, 0.08);
    }}
    .legend-left {{
      display: inline-flex;
      align-items: center;
      gap: 0.6rem;
    }}
    .legend-main {{
      border: 0;
      background: transparent;
      color: var(--text);
      padding: 0;
      display: inline-flex;
      align-items: center;
      gap: 0.6rem;
      text-align: left;
      cursor: pointer;
    }}
    .legend-main:hover {{
      filter: none;
      color: var(--accent);
    }}
    .legend-actions {{
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
    }}
    .legend-toggle {{
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(255, 255, 255, 0.04);
      padding: 0.22rem 0.6rem;
      font-size: 0.76rem;
    }}
    .swatch {{
      width: 0.8rem;
      height: 0.8rem;
      border-radius: 999px;
      display: inline-block;
    }}
    .detail-card {{
      background: var(--surface);
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 0.9rem;
      padding: 0.85rem;
      display: grid;
      gap: 0.5rem;
    }}
    .muted {{
      color: var(--muted);
    }}
    .mono {{
      font-family: "SFMono-Regular", "Menlo", "Monaco", monospace;
      font-size: 0.84rem;
    }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.45rem;
    }}
    .chip {{
      padding: 0.28rem 0.55rem;
      border-radius: 999px;
      background: rgba(233, 196, 106, 0.12);
      color: var(--text);
      font-size: 0.78rem;
    }}
    .neighbor-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 0.4rem;
      max-height: 18rem;
      overflow: auto;
    }}
    .neighbor-list li {{
      padding: 0.5rem 0.6rem;
      border-radius: 0.65rem;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.04);
      cursor: pointer;
    }}
    .neighbor-list li.type-browser-empty {{
      cursor: default;
    }}
    .graph-toolbar {{
      position: absolute;
      top: 0.9rem;
      left: 0.9rem;
      z-index: 3;
      padding: 0.7rem 0.8rem;
      display: inline-flex;
      gap: 0.7rem;
      align-items: center;
      background: rgba(9, 10, 14, 0.74);
      border: 1px solid rgba(255, 255, 255, 0.07);
      border-radius: 999px;
      backdrop-filter: blur(8px);
    }}
    .graph-toolbar span {{
      color: var(--muted);
      font-size: 0.82rem;
    }}
    svg {{
      width: 100%;
      height: 100%;
      display: block;
      cursor: grab;
      background:
        linear-gradient(var(--grid) 1px, transparent 1px) 0 0 / 2rem 2rem,
        linear-gradient(90deg, var(--grid) 1px, transparent 1px) 0 0 / 2rem 2rem;
    }}
    svg.dragging {{
      cursor: grabbing;
    }}
    .edge {{
      stroke: var(--line);
      stroke-width: 1.1;
    }}
    .edge.match {{
      stroke: rgba(233, 196, 106, 0.45);
      stroke-width: 1.6;
    }}
    .edge.edge-wire {{
      stroke: rgba(244, 162, 97, 0.5);
      stroke-dasharray: 6 4;
    }}
    .node-hit {{
      fill: rgba(0, 0, 0, 0);
      cursor: pointer;
    }}
    .node circle {{
      stroke: rgba(0, 0, 0, 0.55);
      stroke-width: 1.4;
    }}
    .node.selected circle {{
      stroke: rgba(233, 196, 106, 0.96);
      stroke-width: 2.8;
    }}
    .node.match circle {{
      stroke: rgba(255, 255, 255, 0.88);
      stroke-width: 2.4;
    }}
    .node.dimmed {{
      opacity: 0.18;
    }}
    .node-label {{
      fill: rgba(243, 232, 208, 0.9);
      font-size: 11px;
      pointer-events: none;
      paint-order: stroke;
      stroke: rgba(10, 11, 15, 0.92);
      stroke-width: 4px;
      stroke-linejoin: round;
    }}
    @media (max-width: 1100px) {{
      .app {{
        grid-template-columns: 18rem 1fr;
        grid-template-rows: minmax(0, 1fr) minmax(18rem, 28vh);
      }}
      .detail {{
        grid-column: 1 / -1;
      }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar panel">
      <div>
        <div class="eyebrow">atlas visual graph</div>
        <h1>Knowledge Graph V1</h1>
      </div>
      <div class="stat-grid">
        <div class="stat"><strong id="node-count"></strong><span class="label">nodes</span></div>
        <div class="stat"><strong id="edge-count"></strong><span class="label">edges</span></div>
        <div class="stat"><strong id="type-count"></strong><span class="label">types</span></div>
        <div class="stat"><strong id="match-count"></strong><span class="label">matches</span></div>
      </div>
      <div class="search-wrap">
        <label class="eyebrow" for="search">search</label>
        <input id="search" type="search" placeholder="project, agent, tag, note title">
      </div>
      <div class="controls">
        <button id="reset-layout" type="button">re-layout</button>
        <button id="fit-view" type="button">fit view</button>
        <button id="show-all-types" type="button">show all</button>
        <label class="toggle"><input id="show-labels" type="checkbox"> force labels</label>
      </div>
      <div>
        <div class="eyebrow">type legend</div>
        <div class="legend" id="legend"></div>
      </div>
      <div class="detail-card">
        <div class="eyebrow">type browser</div>
        <div class="mono" id="type-browser-title">Click a category to browse its nodes.</div>
        <ul class="neighbor-list" id="type-node-list"></ul>
      </div>
      <div class="detail-card">
        <div class="eyebrow">atlas root</div>
        <div class="mono" id="atlas-root"></div>
      </div>
    </aside>
    <main class="graph-wrap panel">
      <div class="graph-toolbar">
        <span>drag nodes</span>
        <span>drag background to pan</span>
        <span>wheel to zoom</span>
        <span>j/k or arrows to move</span>
        <span>/ to search</span>
      </div>
      <svg id="graph" viewBox="-800 -520 1600 1040">
        <g id="viewport">
          <g id="edge-layer"></g>
          <g id="node-layer"></g>
          <g id="label-layer"></g>
        </g>
      </svg>
    </main>
    <aside class="detail panel">
      <div>
        <div class="eyebrow">selected note</div>
        <h2 id="detail-title">Nothing selected</h2>
        <p class="muted" id="detail-subtitle">Click a node to inspect it.</p>
      </div>
      <div class="detail-card">
        <div class="eyebrow">metadata</div>
        <div class="mono" id="detail-path">—</div>
        <div class="chips" id="detail-tags"></div>
      </div>
      <div class="detail-card">
        <div class="eyebrow">neighbors</div>
        <ul class="neighbor-list" id="neighbor-list"></ul>
      </div>
    </aside>
  </div>
  <script>
    const atlasGraphPayload = {payload_json};
    const GOLDEN_ANGLE = 2.399963229728653;
    const typeColors = Object.fromEntries(atlasGraphPayload.nodes.map((node) => [node.type, node.color]));
    const searchInput = document.getElementById("search");
    const showLabelsToggle = document.getElementById("show-labels");
    const nodeCountEl = document.getElementById("node-count");
    const edgeCountEl = document.getElementById("edge-count");
    const typeCountEl = document.getElementById("type-count");
    const matchCountEl = document.getElementById("match-count");
    const legendEl = document.getElementById("legend");
    const atlasRootEl = document.getElementById("atlas-root");
    const detailTitleEl = document.getElementById("detail-title");
    const detailSubtitleEl = document.getElementById("detail-subtitle");
    const detailPathEl = document.getElementById("detail-path");
    const detailTagsEl = document.getElementById("detail-tags");
    const neighborListEl = document.getElementById("neighbor-list");
    const typeBrowserTitleEl = document.getElementById("type-browser-title");
    const typeNodeListEl = document.getElementById("type-node-list");
    const svg = document.getElementById("graph");
    const viewport = document.getElementById("viewport");
    const edgeLayer = document.getElementById("edge-layer");
    const nodeLayer = document.getElementById("node-layer");
    const labelLayer = document.getElementById("label-layer");

    nodeCountEl.textContent = String(atlasGraphPayload.node_count);
    edgeCountEl.textContent = String(atlasGraphPayload.edge_count);
    typeCountEl.textContent = String(Object.keys(atlasGraphPayload.type_counts).length);
    atlasRootEl.textContent = atlasGraphPayload.atlas_root;

    const typeNames = Object.keys(atlasGraphPayload.type_counts).sort((a, b) => atlasGraphPayload.type_counts[b] - atlasGraphPayload.type_counts[a]);
    const hiddenTypes = new Set();
    let browserType = null;

    const nodes = atlasGraphPayload.nodes.map((node, index) => ({{
      ...node,
      index,
      x: 0,
      y: 0,
      matched: false,
      selected: false,
    }}));
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const edges = atlasGraphPayload.edges
      .map((edge) => ({{
        source: nodeById.get(edge.source),
        target: nodeById.get(edge.target),
        kind: edge.kind || "wikilink",
        predicate: edge.predicate || "",
      }}))
      .filter((edge) => edge.source && edge.target);

    const neighbors = new Map(nodes.map((node) => [node.id, new Set()]));
    for (const edge of edges) {{
      neighbors.get(edge.source.id).add(edge.target.id);
      neighbors.get(edge.target.id).add(edge.source.id);
    }}

    const edgeEls = [];
    for (const edge of edges) {{
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("class", edge.kind === "wire" ? "edge edge-wire" : "edge");
      edgeLayer.appendChild(line);
      edgeEls.push({{ edge, line }});
    }}

    const nodeEls = [];
    for (const node of nodes) {{
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("class", "node");
      g.dataset.id = node.id;
      const hit = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      hit.setAttribute("class", "node-hit");
      hit.setAttribute("r", String(14 + Math.min(node.degree, 10) * 1.05));
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("r", String(6 + Math.min(node.degree, 10) * 0.85));
      circle.setAttribute("fill", node.color);
      g.appendChild(hit);
      g.appendChild(circle);
      nodeLayer.appendChild(g);
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("class", "node-label");
      text.textContent = node.title;
      labelLayer.appendChild(text);
      nodeEls.push({{ node, g, circle, text }});
    }}

    let draggingNode = null;
    let draggingCanvas = false;
    let lastPointer = null;
    let selectedNode = null;
    let camera = {{ x: 0, y: 0, scale: 1 }};

    function sortNodes(items) {{
      return [...items].sort((a, b) => {{
        if (a.type !== b.type) {{
          return a.type.localeCompare(b.type);
        }}
        if (b.degree !== a.degree) {{
          return b.degree - a.degree;
        }}
        return a.title.localeCompare(b.title);
      }});
    }}

    function visibleNodes() {{
      return nodes.filter((node) => !hiddenTypes.has(node.type));
    }}

    function computeTypeAnchors(activeTypes) {{
      const anchors = new Map();
      if (!activeTypes.length) {{
        return anchors;
      }}
      if (activeTypes.length === 1) {{
        anchors.set(activeTypes[0], [0, 0]);
        return anchors;
      }}
      const radiusX = 360;
      const radiusY = 240;
      activeTypes.forEach((typeName, index) => {{
        const angle = -Math.PI / 2 + (index * 2 * Math.PI) / activeTypes.length;
        anchors.set(typeName, [
          Math.cos(angle) * radiusX,
          Math.sin(angle) * radiusY,
        ]);
      }});
      return anchors;
    }}

    function layoutNodes() {{
      const activeTypes = typeNames.filter((typeName) => !hiddenTypes.has(typeName));
      const anchors = computeTypeAnchors(activeTypes);
      for (const typeName of activeTypes) {{
        const anchor = anchors.get(typeName) || [0, 0];
        const cluster = sortNodes(nodes.filter((node) => node.type === typeName));
        cluster.forEach((node, index) => {{
          if (node === draggingNode) {{
            return;
          }}
          if (index === 0) {{
            node.x = anchor[0];
            node.y = anchor[1];
            return;
          }}
          const radius = 42 + Math.floor((index - 1) / 8) * 48 + ((index - 1) % 8) * 3;
          const angle = (index - 1) * GOLDEN_ANGLE;
          node.x = anchor[0] + Math.cos(angle) * radius;
          node.y = anchor[1] + Math.sin(angle) * radius * 0.72;
        }});
      }}
    }}

    function applyCamera() {{
      viewport.setAttribute("transform", `translate(${{camera.x}} ${{camera.y}}) scale(${{camera.scale}})`);
    }}

    function fitView() {{
      const visible = visibleNodes();
      if (!visible.length) {{
        return;
      }}
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const node of visible) {{
        minX = Math.min(minX, node.x);
        minY = Math.min(minY, node.y);
        maxX = Math.max(maxX, node.x);
        maxY = Math.max(maxY, node.y);
      }}
      const width = Math.max(1, maxX - minX);
      const height = Math.max(1, maxY - minY);
      const scale = Math.min(1.35, Math.max(0.42, Math.min(1280 / width, 900 / height)));
      camera = {{
        x: -((minX + maxX) / 2) * scale,
        y: -((minY + maxY) / 2) * scale,
        scale,
      }};
      applyCamera();
    }}

    function ensureSelectedNodeVisible() {{
      if (selectedNode && hiddenTypes.has(selectedNode.type)) {{
        selectedNode = null;
      }}
      const candidates = keyboardCandidates();
      if (!selectedNode && candidates.length) {{
        selectNode(candidates[0], false);
        return;
      }}
      if (!candidates.length) {{
        selectNode(null, false);
      }}
    }}

    function updateDetail(node) {{
      if (!node) {{
        detailTitleEl.textContent = "Nothing selected";
        detailSubtitleEl.textContent = "Click a node to inspect it.";
        detailPathEl.textContent = "—";
        detailTagsEl.innerHTML = "";
        neighborListEl.innerHTML = "";
        return;
      }}
      detailTitleEl.textContent = node.title;
      detailSubtitleEl.textContent = `${{node.type}} · degree ${{node.degree}}${{node.status ? " · " + node.status : ""}}`;
      detailPathEl.textContent = node.path;
      detailTagsEl.innerHTML = "";
      for (const value of [node.type, ...(node.tags || []).slice(0, 8)]) {{
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = value;
        detailTagsEl.appendChild(chip);
      }}
      const linked = Array.from(neighbors.get(node.id) || [])
        .map((id) => nodeById.get(id))
        .filter((candidate) => candidate && !hiddenTypes.has(candidate.type))
        .sort((a, b) => a.title.localeCompare(b.title));
      neighborListEl.innerHTML = "";
      if (!linked.length) {{
        const item = document.createElement("li");
        item.className = "muted type-browser-empty";
        item.textContent = "No visible linked neighbors.";
        neighborListEl.appendChild(item);
      }}
      for (const linkedNode of linked.slice(0, 20)) {{
        const item = document.createElement("li");
        item.innerHTML = `<strong>${{linkedNode.title}}</strong><div class="muted mono">${{linkedNode.type}} · degree ${{linkedNode.degree}}</div>`;
        item.addEventListener("click", () => selectNode(linkedNode, true));
        neighborListEl.appendChild(item);
      }}
    }}

    function selectNode(node, center = false) {{
      selectedNode = node && !hiddenTypes.has(node.type) ? node : null;
      for (const item of nodeEls) {{
        item.node.selected = !!selectedNode && item.node.id === selectedNode.id;
      }}
      updateDetail(selectedNode);
      if (center && selectedNode) {{
        camera.x = -selectedNode.x * camera.scale;
        camera.y = -selectedNode.y * camera.scale;
        applyCamera();
      }}
      render();
    }}

    function renderTypeBrowser() {{
      typeNodeListEl.innerHTML = "";
      if (!browserType || hiddenTypes.has(browserType)) {{
        typeBrowserTitleEl.textContent = "Click a category to browse its nodes.";
        const item = document.createElement("li");
        item.className = "muted type-browser-empty";
        item.textContent = "No type selected.";
        typeNodeListEl.appendChild(item);
        return;
      }}
      const typedNodes = sortNodes(nodes.filter((node) => node.type === browserType));
      typeBrowserTitleEl.textContent = `${{browserType}} · ${{typedNodes.length}} nodes`;
      for (const node of typedNodes.slice(0, 48)) {{
        const item = document.createElement("li");
        item.innerHTML = `<strong>${{node.title}}</strong><div class="muted mono">${{node.id}} · degree ${{node.degree}}</div>`;
        item.addEventListener("click", () => selectNode(node, true));
        typeNodeListEl.appendChild(item);
      }}
      if (!typedNodes.length) {{
        const item = document.createElement("li");
        item.className = "muted type-browser-empty";
        item.textContent = "No nodes in this category.";
        typeNodeListEl.appendChild(item);
      }}
    }}

    function renderLegend() {{
      legendEl.innerHTML = "";
      for (const typeName of typeNames) {{
        const row = document.createElement("div");
        row.className = `legend-row${{browserType === typeName ? " active" : ""}}`;

        const main = document.createElement("button");
        main.type = "button";
        main.className = "legend-main";
        const left = document.createElement("span");
        left.className = "legend-left";
        const swatch = document.createElement("span");
        swatch.className = "swatch";
        swatch.style.background = typeColors[typeName] || "#b6c2cf";
        const label = document.createElement("span");
        label.textContent = typeName;
        left.appendChild(swatch);
        left.appendChild(label);
        main.appendChild(left);
        main.addEventListener("click", () => {{
          if (hiddenTypes.has(typeName)) {{
            hiddenTypes.delete(typeName);
          }}
          browserType = browserType === typeName ? null : typeName;
          renderLegend();
          renderTypeBrowser();
          render();
        }});

        const actions = document.createElement("div");
        actions.className = "legend-actions";
        const count = document.createElement("span");
        count.className = "muted mono";
        count.textContent = String(atlasGraphPayload.type_counts[typeName]);
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "legend-toggle";
        toggle.textContent = hiddenTypes.has(typeName) ? "show" : "hide";
        toggle.addEventListener("click", (event) => {{
          event.stopPropagation();
          if (hiddenTypes.has(typeName)) {{
            hiddenTypes.delete(typeName);
          }} else {{
            hiddenTypes.add(typeName);
          }}
          if (browserType === typeName && hiddenTypes.has(typeName)) {{
            browserType = null;
          }}
          layoutNodes();
          fitView();
          renderLegend();
          renderTypeBrowser();
          ensureSelectedNodeVisible();
          render();
        }});
        actions.appendChild(count);
        actions.appendChild(toggle);
        row.appendChild(main);
        row.appendChild(actions);
        legendEl.appendChild(row);
      }}
    }}

    function applySearch() {{
      const needle = searchInput.value.trim().toLowerCase();
      let matches = 0;
      for (const item of nodeEls) {{
        const haystack = [item.node.id, item.node.title, item.node.type, ...(item.node.tags || [])].join(" ").toLowerCase();
        item.node.matched = !!needle && haystack.includes(needle) && !hiddenTypes.has(item.node.type);
        if (item.node.matched) {{
          matches += 1;
        }}
      }}
      matchCountEl.textContent = String(matches);
      const candidates = keyboardCandidates();
      if ((!selectedNode || (needle && !selectedNode.matched)) && candidates.length) {{
        selectNode(candidates[0], false);
      }} else if (!candidates.length) {{
        selectNode(null, false);
      }} else {{
        render();
      }}
    }}

    function keyboardCandidates() {{
      const visible = sortNodes(visibleNodes());
      const matched = visible.filter((node) => node.matched);
      return matched.length ? matched : visible;
    }}

    function cycleSelection(delta) {{
      const candidates = keyboardCandidates();
      if (!candidates.length) {{
        selectNode(null, false);
        return;
      }}
      let currentIndex = selectedNode ? candidates.findIndex((node) => node.id === selectedNode.id) : -1;
      if (currentIndex < 0) {{
        currentIndex = delta > 0 ? -1 : 0;
      }}
      const nextIndex = (currentIndex + delta + candidates.length) % candidates.length;
      selectNode(candidates[nextIndex], true);
    }}

    function visibleEdge(edge) {{
      return !hiddenTypes.has(edge.source.type) && !hiddenTypes.has(edge.target.type);
    }}

    function render() {{
      const needle = searchInput.value.trim();
      const spotlightType = browserType && !hiddenTypes.has(browserType) ? browserType : null;
      for (const item of edgeEls) {{
        const visible = visibleEdge(item.edge);
        const matched = !needle || item.edge.source.matched || item.edge.target.matched;
        item.line.setAttribute("x1", item.edge.source.x);
        item.line.setAttribute("y1", item.edge.source.y);
        item.line.setAttribute("x2", item.edge.target.x);
        item.line.setAttribute("y2", item.edge.target.y);
        item.line.setAttribute(
          "class",
          [
            "edge",
            item.edge.kind === "wire" ? "edge-wire" : "",
            visible && needle && matched ? "match" : "",
          ].filter(Boolean).join(" "),
        );
        item.line.style.display = visible ? "block" : "none";
        item.line.style.opacity = visible && matched ? "1" : "0.05";
      }}
      for (const item of nodeEls) {{
        const visible = !hiddenTypes.has(item.node.type);
        const dimForSearch = needle && !item.node.matched && !item.node.selected;
        const dimForBrowser = spotlightType && spotlightType !== item.node.type && !item.node.selected;
        item.g.style.display = visible ? "block" : "none";
        item.text.style.display = visible ? "block" : "none";
        if (!visible) {{
          continue;
        }}
        item.g.setAttribute("transform", `translate(${{item.node.x}} ${{item.node.y}})`);
        const showLabel = showLabelsToggle.checked || item.node.selected || item.node.matched || item.node.degree >= 4 || spotlightType === item.node.type;
        item.g.setAttribute(
          "class",
          [
            "node",
            item.node.selected ? "selected" : "",
            item.node.matched ? "match" : "",
            dimForSearch || dimForBrowser ? "dimmed" : "",
          ].filter(Boolean).join(" "),
        );
        item.text.setAttribute("x", item.node.x + 11);
        item.text.setAttribute("y", item.node.y - 10);
        item.text.style.opacity = showLabel ? "1" : "0";
      }}
    }}

    function svgPoint(event) {{
      const pt = svg.createSVGPoint();
      pt.x = event.clientX;
      pt.y = event.clientY;
      return pt.matrixTransform(svg.getScreenCTM().inverse());
    }}

    function graphCoordinates(point) {{
      return {{
        x: (point.x - camera.x) / camera.scale,
        y: (point.y - camera.y) / camera.scale,
      }};
    }}

    svg.addEventListener("wheel", (event) => {{
      event.preventDefault();
      const point = svgPoint(event);
      const graphPoint = graphCoordinates(point);
      const zoom = event.deltaY < 0 ? 1.08 : 0.92;
      camera.scale = Math.max(0.24, Math.min(3, camera.scale * zoom));
      camera.x = point.x - graphPoint.x * camera.scale;
      camera.y = point.y - graphPoint.y * camera.scale;
      applyCamera();
    }}, {{ passive: false }});

    svg.addEventListener("pointerdown", (event) => {{
      const targetNode = event.target.closest(".node");
      lastPointer = svgPoint(event);
      if (targetNode) {{
        draggingNode = nodeById.get(targetNode.dataset.id);
        selectNode(draggingNode, false);
      }} else {{
        draggingCanvas = true;
        svg.classList.add("dragging");
      }}
    }});

    svg.addEventListener("pointermove", (event) => {{
      if (!lastPointer) {{
        return;
      }}
      const point = svgPoint(event);
      if (draggingNode) {{
        const graphPoint = graphCoordinates(point);
        draggingNode.x = graphPoint.x;
        draggingNode.y = graphPoint.y;
        render();
      }} else if (draggingCanvas) {{
        camera.x += point.x - lastPointer.x;
        camera.y += point.y - lastPointer.y;
        applyCamera();
      }}
      lastPointer = point;
    }});

    function clearDragging() {{
      draggingNode = null;
      draggingCanvas = false;
      lastPointer = null;
      svg.classList.remove("dragging");
    }}

    svg.addEventListener("pointerup", clearDragging);
    svg.addEventListener("pointerleave", clearDragging);
    svg.addEventListener("dblclick", () => fitView());

    searchInput.addEventListener("input", applySearch);
    searchInput.addEventListener("keydown", (event) => {{
      if (event.key === "Escape") {{
        searchInput.value = "";
        applySearch();
        searchInput.blur();
      }}
    }});
    showLabelsToggle.addEventListener("change", render);
    document.getElementById("reset-layout").addEventListener("click", () => {{
      layoutNodes();
      fitView();
      render();
    }});
    document.getElementById("fit-view").addEventListener("click", fitView);
    document.getElementById("show-all-types").addEventListener("click", () => {{
      hiddenTypes.clear();
      browserType = null;
      layoutNodes();
      fitView();
      renderLegend();
      renderTypeBrowser();
      ensureSelectedNodeVisible();
      render();
    }});

    for (const item of nodeEls) {{
      item.g.addEventListener("click", (event) => {{
        event.stopPropagation();
        selectNode(item.node, false);
      }});
    }}

    document.addEventListener("keydown", (event) => {{
      if (event.metaKey || event.ctrlKey || event.altKey) {{
        return;
      }}
      if (document.activeElement === searchInput) {{
        return;
      }}
      if (event.key === "/") {{
        event.preventDefault();
        searchInput.focus();
        searchInput.select();
        return;
      }}
      if (event.key === "j" || event.key === "ArrowDown") {{
        event.preventDefault();
        cycleSelection(1);
        return;
      }}
      if (event.key === "k" || event.key === "ArrowUp") {{
        event.preventDefault();
        cycleSelection(-1);
        return;
      }}
      if (event.key === "Enter" || event.key === " ") {{
        if (selectedNode) {{
          event.preventDefault();
          selectNode(selectedNode, true);
        }}
        return;
      }}
      if (event.key === "f") {{
        event.preventDefault();
        fitView();
        return;
      }}
      if (event.key === "0") {{
        event.preventDefault();
        hiddenTypes.clear();
        renderLegend();
        renderTypeBrowser();
        layoutNodes();
        fitView();
        ensureSelectedNodeVisible();
        render();
      }}
    }});

    renderLegend();
    layoutNodes();
    fitView();
    renderTypeBrowser();
    updateDetail(null);
    applySearch();
    render();
  </script>
</body>
</html>
"""
