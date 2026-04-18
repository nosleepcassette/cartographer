from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


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
    finally:
        connection.close()

    aliases = _alias_map(atlas_root, note_rows)
    edge_pairs: set[tuple[str, str]] = set()
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
            edge_pairs.add((source, target_id))

    for row in ref_rows:
        source = aliases.get(str(row["from_note"]).strip())
        target = aliases.get(str(row["to_note"]).strip())
        if source is None or target is None:
            unresolved_edge_count += 1
            continue
        if source == target:
            continue
        edge_pairs.add((source, target))

    edges = [
        {"source": source, "target": target}
        for source, target in sorted(edge_pairs)
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
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.6rem;
      padding: 0.45rem 0.55rem;
      border-radius: 0.7rem;
      background: rgba(255, 255, 255, 0.02);
    }}
    .legend-left {{
      display: inline-flex;
      align-items: center;
      gap: 0.6rem;
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
        <label class="toggle"><input id="show-labels" type="checkbox"> force labels</label>
      </div>
      <div>
        <div class="eyebrow">type legend</div>
        <div class="legend" id="legend"></div>
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
    for (const typeName of typeNames) {{
      const row = document.createElement("div");
      row.className = "legend-row";
      const left = document.createElement("div");
      left.className = "legend-left";
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = typeColors[typeName] || "#b6c2cf";
      const label = document.createElement("span");
      label.textContent = typeName;
      left.appendChild(swatch);
      left.appendChild(label);
      const count = document.createElement("span");
      count.className = "muted mono";
      count.textContent = String(atlasGraphPayload.type_counts[typeName]);
      row.appendChild(left);
      row.appendChild(count);
      legendEl.appendChild(row);
    }}

    const typeAnchors = {{
      project: [-260, -110],
      entity: [240, -140],
      learning: [-260, 170],
      session: [250, 180],
      "agent-log": [220, 180],
      daily: [-10, 260],
      note: [0, -250],
      other: [0, 0],
    }};

    const nodes = atlasGraphPayload.nodes.map((node, index) => {{
      const anchor = typeAnchors[node.type] || typeAnchors.other;
      const angle = (index * 0.73) % (Math.PI * 2);
      const radius = 80 + (index % 18) * 11;
      return {{
        ...node,
        index,
        x: anchor[0] + Math.cos(angle) * radius,
        y: anchor[1] + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
        fx: null,
        fy: null,
        matched: false,
        selected: false,
      }};
    }});
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const edges = atlasGraphPayload.edges
      .map((edge) => ({{
        source: nodeById.get(edge.source),
        target: nodeById.get(edge.target),
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
      line.setAttribute("class", "edge");
      edgeLayer.appendChild(line);
      edgeEls.push({{ edge, line }});
    }}

    const nodeEls = [];
    for (const node of nodes) {{
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("class", "node");
      g.dataset.id = node.id;
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("r", String(6 + Math.min(node.degree, 10) * 0.85));
      circle.setAttribute("fill", node.color);
      g.appendChild(circle);
      nodeLayer.appendChild(g);
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("class", "node-label");
      text.textContent = node.title;
      labelLayer.appendChild(text);
      nodeEls.push({{ node, g, circle, text }});
    }}

    let alpha = 1;
    let draggingNode = null;
    let draggingCanvas = false;
    let lastPointer = null;
    let selectedNode = null;
    let camera = {{ x: 0, y: 0, scale: 1 }};

    function resetLayout() {{
      alpha = 1;
      for (const node of nodes) {{
        const anchor = typeAnchors[node.type] || typeAnchors.other;
        const angle = (node.index * 0.73) % (Math.PI * 2);
        const radius = 80 + (node.index % 18) * 11;
        node.x = anchor[0] + Math.cos(angle) * radius;
        node.y = anchor[1] + Math.sin(angle) * radius;
        node.vx = 0;
        node.vy = 0;
        node.fx = null;
        node.fy = null;
      }}
    }}

    function applyCamera() {{
      viewport.setAttribute("transform", `translate(${{camera.x}} ${{camera.y}}) scale(${{camera.scale}})`);
    }}

    function fitView() {{
      if (!nodes.length) return;
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const node of nodes) {{
        minX = Math.min(minX, node.x);
        minY = Math.min(minY, node.y);
        maxX = Math.max(maxX, node.x);
        maxY = Math.max(maxY, node.y);
      }}
      const width = Math.max(1, maxX - minX);
      const height = Math.max(1, maxY - minY);
      const scale = Math.min(1.6, Math.max(0.45, Math.min(1300 / width, 900 / height)));
      camera = {{
        x: -(minX + maxX) / 2 * scale,
        y: -(minY + maxY) / 2 * scale,
        scale,
      }};
      applyCamera();
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
        .filter(Boolean)
        .sort((a, b) => a.title.localeCompare(b.title));
      neighborListEl.innerHTML = "";
      if (!linked.length) {{
        const item = document.createElement("li");
        item.className = "muted";
        item.textContent = "No linked neighbors.";
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
      selectedNode = node;
      for (const item of nodeEls) {{
        item.node.selected = item.node === node;
      }}
      updateDetail(node);
      if (center && node) {{
        camera.x = -node.x * camera.scale;
        camera.y = -node.y * camera.scale;
        applyCamera();
      }}
      render();
    }}

    function applySearch() {{
      const needle = searchInput.value.trim().toLowerCase();
      let matches = 0;
      for (const item of nodeEls) {{
        const haystack = [item.node.id, item.node.title, item.node.type, ...(item.node.tags || [])].join(" ").toLowerCase();
        item.node.matched = !!needle && haystack.includes(needle);
        if (item.node.matched) matches += 1;
      }}
      matchCountEl.textContent = String(matches);
      render();
      if (matches && !selectedNode) {{
        const first = nodeEls.find((item) => item.node.matched);
        if (first) selectNode(first.node, true);
      }}
    }}

    function visibleEdge(edge) {{
      const needle = searchInput.value.trim();
      if (!needle) return true;
      return edge.source.matched || edge.target.matched;
    }}

    function render() {{
      const needle = searchInput.value.trim();
      for (const item of edgeEls) {{
        const isMatch = visibleEdge(item.edge);
        item.line.setAttribute("x1", item.edge.source.x);
        item.line.setAttribute("y1", item.edge.source.y);
        item.line.setAttribute("x2", item.edge.target.x);
        item.line.setAttribute("y2", item.edge.target.y);
        item.line.setAttribute("class", `edge${{isMatch && needle ? " match" : ""}}`);
        item.line.style.opacity = !needle || isMatch ? "1" : "0.06";
      }}
      for (const item of nodeEls) {{
        item.g.setAttribute("transform", `translate(${{item.node.x}} ${{item.node.y}})`);
        const showLabel = showLabelsToggle.checked || item.node.selected || item.node.matched || item.node.degree >= 4;
        item.g.setAttribute("class", [
          "node",
          item.node.selected ? "selected" : "",
          item.node.matched ? "match" : "",
          needle && !item.node.matched && !item.node.selected ? "dimmed" : "",
        ].filter(Boolean).join(" "));
        item.text.setAttribute("x", item.node.x + 10);
        item.text.setAttribute("y", item.node.y - 10);
        item.text.style.opacity = showLabel ? "1" : "0";
      }}
    }}

    function tickPhysics() {{
      alpha *= 0.985;
      for (let i = 0; i < nodes.length; i += 1) {{
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j += 1) {{
          const b = nodes[j];
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          let dist2 = dx * dx + dy * dy + 0.01;
          let force = 4200 / dist2;
          dx *= force;
          dy *= force;
          a.vx += dx;
          a.vy += dy;
          b.vx -= dx;
          b.vy -= dy;
        }}
      }}
      for (const edge of edges) {{
        const dx = edge.target.x - edge.source.x;
        const dy = edge.target.y - edge.source.y;
        const distance = Math.sqrt(dx * dx + dy * dy) || 1;
        const desired = 85 + Math.min(edge.source.degree + edge.target.degree, 18) * 4;
        const spring = (distance - desired) * 0.0009 * alpha;
        const fx = (dx / distance) * spring;
        const fy = (dy / distance) * spring;
        edge.source.vx += fx;
        edge.source.vy += fy;
        edge.target.vx -= fx;
        edge.target.vy -= fy;
      }}
      for (const node of nodes) {{
        const anchor = typeAnchors[node.type] || typeAnchors.other;
        node.vx += (anchor[0] - node.x) * 0.0008 * alpha;
        node.vy += (anchor[1] - node.y) * 0.0008 * alpha;
        if (node.fx !== null && node.fy !== null) {{
          node.x = node.fx;
          node.y = node.fy;
          node.vx = 0;
          node.vy = 0;
        }} else {{
          node.vx *= 0.82;
          node.vy *= 0.82;
          node.x += node.vx;
          node.y += node.vy;
        }}
      }}
    }}

    function animationLoop() {{
      if (alpha > 0.02 || draggingNode) {{
        tickPhysics();
        render();
      }}
      requestAnimationFrame(animationLoop);
    }}

    function svgPoint(event) {{
      const pt = svg.createSVGPoint();
      pt.x = event.clientX;
      pt.y = event.clientY;
      return pt.matrixTransform(svg.getScreenCTM().inverse());
    }}

    svg.addEventListener("wheel", (event) => {{
      event.preventDefault();
      const zoom = event.deltaY < 0 ? 1.08 : 0.92;
      camera.scale = Math.max(0.25, Math.min(3, camera.scale * zoom));
      applyCamera();
    }}, {{ passive: false }});

    svg.addEventListener("pointerdown", (event) => {{
      const targetNode = event.target.closest(".node");
      lastPointer = svgPoint(event);
      if (targetNode) {{
        draggingNode = nodeById.get(targetNode.dataset.id);
        draggingNode.fx = lastPointer.x / camera.scale - camera.x / camera.scale;
        draggingNode.fy = lastPointer.y / camera.scale - camera.y / camera.scale;
        alpha = Math.max(alpha, 0.3);
        selectNode(draggingNode, false);
      }} else {{
        draggingCanvas = true;
        svg.classList.add("dragging");
      }}
    }});

    svg.addEventListener("pointermove", (event) => {{
      if (!lastPointer) return;
      const point = svgPoint(event);
      if (draggingNode) {{
        draggingNode.fx = point.x / camera.scale - camera.x / camera.scale;
        draggingNode.fy = point.y / camera.scale - camera.y / camera.scale;
        alpha = Math.max(alpha, 0.25);
      }} else if (draggingCanvas) {{
        camera.x += point.x - lastPointer.x;
        camera.y += point.y - lastPointer.y;
        applyCamera();
      }}
      lastPointer = point;
    }});

    function clearDragging() {{
      if (draggingNode) {{
        draggingNode.fx = null;
        draggingNode.fy = null;
      }}
      draggingNode = null;
      draggingCanvas = false;
      lastPointer = null;
      svg.classList.remove("dragging");
    }}

    svg.addEventListener("pointerup", clearDragging);
    svg.addEventListener("pointerleave", clearDragging);
    svg.addEventListener("dblclick", () => fitView());

    searchInput.addEventListener("input", applySearch);
    showLabelsToggle.addEventListener("change", render);
    document.getElementById("reset-layout").addEventListener("click", () => {{
      resetLayout();
      fitView();
    }});
    document.getElementById("fit-view").addEventListener("click", fitView);

    for (const item of nodeEls) {{
      item.g.addEventListener("click", (event) => {{
        event.stopPropagation();
        selectNode(item.node, false);
      }});
    }}

    fitView();
    updateDetail(null);
    applySearch();
    render();
    requestAnimationFrame(animationLoop);
  </script>
</body>
</html>
"""
