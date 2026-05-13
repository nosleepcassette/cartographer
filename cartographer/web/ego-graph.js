(() => {
  const TYPE_COLORS = {
    daily: "rgba(233,254,255,.58)",
    entity: "#ffb000",
    project: "#7fe3de",
    task: "#ff7070",
    ref: "#d4a7ff",
    note: "#e9feff",
    missing: "#ff7070",
  };

  const EDGE_GROUPS = {
    supports: "structural",
    contradicts: "structural",
    depends_on: "structural",
    enables: "structural",
    relates_to: "structural",
    intensifies_with: "emotional",
    co_occurs_with: "emotional",
    triggered_by: "emotional",
    resistance_against: "emotional",
    relates_to_person: "relational",
    in_love: "relational",
    friends_with: "relational",
    works_with: "relational",
    precedes: "temporal",
    follows: "temporal",
  };

  const EDGE_COLORS = {
    structural: "rgba(233,254,255,.42)",
    emotional: "#ff7070",
    relational: "#ffb000",
    temporal: "#7fe3de",
  };

  function render(container, payload, onNodeClick) {
    const nodes = (payload.nodes || []).map((node, index) => ({
      ...node,
      x: 180 + Math.cos((index / Math.max(payload.nodes.length, 1)) * Math.PI * 2) * 96,
      y: 120 + Math.sin((index / Math.max(payload.nodes.length, 1)) * Math.PI * 2) * 64,
      vx: 0,
      vy: 0,
    }));
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const edges = (payload.edges || []).filter((edge) => byId.has(edge.source_note) && byId.has(edge.target_note));
    if (!nodes.length) {
      container.innerHTML = '<p class="muted">no graph data</p>';
      return;
    }

    container.innerHTML = `
      <svg viewBox="0 0 360 240" role="img" aria-label="note ego graph">
        <g class="ego-edges"></g>
        <g class="ego-nodes"></g>
      </svg>
    `;
    const svg = container.querySelector("svg");
    const edgeLayer = container.querySelector(".ego-edges");
    const nodeLayer = container.querySelector(".ego-nodes");

    const edgeEls = edges.map((edge) => {
      const group = EDGE_GROUPS[edge.predicate] || "structural";
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("stroke", EDGE_COLORS[group] || EDGE_COLORS.structural);
      line.setAttribute("stroke-width", "1.6");
      line.setAttribute("opacity", "0.75");
      edgeLayer.appendChild(line);
      return { edge, line };
    });

    const nodeEls = nodes.map((node) => {
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      group.setAttribute("class", `ego-node ${node.id === payload.center ? "is-center" : ""}`);
      group.setAttribute("tabindex", "0");
      group.innerHTML = `
        <circle r="${node.id === payload.center ? 21 : 16}" fill="${TYPE_COLORS[node.type] || TYPE_COLORS.note}"></circle>
        <text y="34" text-anchor="middle">${escapeSvg(node.title || node.id)}</text>
      `;
      group.addEventListener("click", () => onNodeClick?.(node.id));
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter") onNodeClick?.(node.id);
      });
      nodeLayer.appendChild(group);
      return { node, group };
    });

    let ticks = 0;
    function step() {
      for (const node of nodes) {
        for (const other of nodes) {
          if (node === other) continue;
          const dx = node.x - other.x;
          const dy = node.y - other.y;
          const dist = Math.max(24, Math.hypot(dx, dy));
          const force = 70 / (dist * dist);
          node.vx += (dx / dist) * force;
          node.vy += (dy / dist) * force;
        }
      }
      for (const edge of edges) {
        const source = byId.get(edge.source_note);
        const target = byId.get(edge.target_note);
        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const dist = Math.max(1, Math.hypot(dx, dy));
        const force = (dist - 96) * 0.002;
        source.vx += dx * force;
        source.vy += dy * force;
        target.vx -= dx * force;
        target.vy -= dy * force;
      }
      for (const node of nodes) {
        node.vx += (180 - node.x) * 0.004;
        node.vy += (120 - node.y) * 0.004;
        node.vx *= 0.86;
        node.vy *= 0.86;
        node.x = Math.max(32, Math.min(328, node.x + node.vx));
        node.y = Math.max(32, Math.min(198, node.y + node.vy));
      }
      draw();
      ticks += 1;
      if (ticks < 160 && svg.isConnected) requestAnimationFrame(step);
    }

    function draw() {
      for (const { edge, line } of edgeEls) {
        const source = byId.get(edge.source_note);
        const target = byId.get(edge.target_note);
        line.setAttribute("x1", source.x);
        line.setAttribute("y1", source.y);
        line.setAttribute("x2", target.x);
        line.setAttribute("y2", target.y);
      }
      for (const { node, group } of nodeEls) {
        group.setAttribute("transform", `translate(${node.x}, ${node.y})`);
      }
    }

    step();
  }

  function escapeSvg(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  window.CartEgoGraph = { render };
})();
