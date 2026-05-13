(() => {
  const PREDICATE_INFO = {
    supports: { group: "structural", desc: "A provides evidence or backing for B" },
    contradicts: { group: "structural", desc: "A conflicts with or opposes B" },
    depends_on: { group: "structural", desc: "A requires B to be true or complete" },
    enables: { group: "structural", desc: "A makes B possible" },
    precedes: { group: "temporal", desc: "A happens before B" },
    follows: { group: "temporal", desc: "A happens after B" },
    questions: { group: "structural", desc: "A raises uncertainty about B" },
    extends: { group: "structural", desc: "A expands or continues B" },
    instances: { group: "structural", desc: "A is an example of B" },
    relates_to: { group: "structural", desc: "A is generally related to B" },
    qualifies: { group: "structural", desc: "A narrows or qualifies B" },
    part_of: { group: "structural", desc: "A is a component of B" },
    grounds: { group: "structural", desc: "A gives grounding or context for B" },
    relates_to_goal: { group: "structural", desc: "A is relevant to achieving B" },
    intensifies_with: { group: "emotional", desc: "A amplifies or worsens B" },
    co_occurs_with: { group: "emotional", desc: "A tends to happen alongside B" },
    triggered_by: { group: "emotional", desc: "A is emotionally triggered by B" },
    resistance_against: { group: "emotional", desc: "A is a defense mechanism against B" },
    relates_to_person: { group: "relational", desc: "A is about or involves person B" },
    intention_outcome: { group: "relational", desc: "A intention led to outcome B" },
    "active-project": { group: "relational", desc: "A is an active project for B" },
    "core-infrastructure": { group: "relational", desc: "A is core infrastructure for B" },
    crushing_on: { group: "relational", desc: "A has a crush on B" },
    smitten: { group: "relational", desc: "A is smitten with B" },
    in_love: { group: "relational", desc: "A is in love with B" },
    loves: { group: "relational", desc: "A loves B" },
    loved: { group: "relational", desc: "A loved B" },
    cherishes: { group: "relational", desc: "A cherishes B" },
    works_with: { group: "relational", desc: "A has professional connection to B" },
    avoids: { group: "relational", desc: "A avoids B" },
    ghosted: { group: "relational", desc: "A ghosted B" },
    friends_with: { group: "relational", desc: "A has friendship with B" },
    family: { group: "relational", desc: "A has family relation to B" },
  };

  const wireState = {
    loaded: false,
    source: null,
    target: null,
    predicate: null,
    predicates: [],
    metadata: null,
  };

  const C = () => window.Cartographer;

  async function render() {
    if (!wireState.loaded) {
      bindEvents();
      await Promise.all([loadPredicates(), loadMetadata()]);
      wireState.loaded = true;
    }
    await loadRecentWires();
  }

  async function loadPredicates() {
    const payload = await C().api("/api/predicates");
    wireState.predicates = payload || [];
    if (!wireState.predicate && wireState.predicates.length) {
      wireState.predicate = wireState.predicates[0].name;
    }
    renderPredicates();
  }

  async function loadMetadata() {
    wireState.metadata = await C().api("/api/metadata");
    populateSelect("wire-valence", wireState.metadata.emotional_valences);
    populateSelect("wire-energy", wireState.metadata.energy_impacts);
    populateSelect("wire-avoidance", wireState.metadata.avoidance_risks);
    populateSelect("wire-state", wireState.metadata.current_states);
  }

  function populateSelect(id, values = []) {
    const select = C().$(`#${id}`);
    if (!select) return;
    select.innerHTML = '<option value="">none</option>' + values.map((value) => (
      `<option value="${C().escapeHtml(value)}">${C().escapeHtml(value)}</option>`
    )).join("");
  }

  function renderPredicates() {
    const output = C().$("#predicate-picker");
    if (!output) return;
    const groups = {};
    for (const predicate of wireState.predicates) {
      const info = PREDICATE_INFO[predicate.name] || { group: "other", desc: "Custom profile predicate" };
      groups[info.group] ||= [];
      groups[info.group].push({ ...predicate, ...info });
    }
    const groupOrder = ["structural", "relational", "emotional", "temporal", "other"];
    output.innerHTML = groupOrder.filter((group) => groups[group]?.length).map((group) => `
      <section class="predicate-group">
        <h4>${C().escapeHtml(group)}</h4>
        ${groups[group].map((predicate) => `
          <button class="predicate-option ${wireState.predicate === predicate.name ? "is-active" : ""}" type="button" data-predicate="${C().escapeHtml(predicate.name)}">
            <span class="predicate-dot" style="background:${C().escapeHtml(predicate.color || "#ffb000")}"></span>
            <span>
              <span class="predicate-name">${C().escapeHtml(predicate.name)}</span>
              <span class="predicate-desc">${C().escapeHtml(predicate.desc)}</span>
            </span>
          </button>
        `).join("")}
      </section>
    `).join("");
    C().$$("[data-predicate]", output).forEach((button) => {
      button.addEventListener("click", () => {
        wireState.predicate = button.dataset.predicate;
        renderPredicates();
      });
    });
  }

  async function searchNotes(which, query) {
    const resultBox = C().$(`#wire-${which}-results`);
    if (!resultBox) return;
    if (!query.trim()) {
      resultBox.innerHTML = "";
      return;
    }
    const payload = await C().api(`/api/notes?q=${encodeURIComponent(query)}&limit=8`);
    const notes = payload.notes || [];
    resultBox.innerHTML = notes.length ? notes.map((note) => `
      <button type="button" data-wire-note="${C().escapeHtml(note.id)}" data-wire-title="${C().escapeHtml(note.title)}" data-wire-which="${which}">
        ${C().escapeHtml(note.title)} <span class="muted">${C().escapeHtml(note.type)}</span>
      </button>
    `).join("") : '<p class="muted">no matches</p>';
    C().$$("[data-wire-note]", resultBox).forEach((button) => {
      button.addEventListener("click", () => selectNote(which, button.dataset.wireNote, button.dataset.wireTitle));
    });
  }

  function selectNote(which, id, title) {
    wireState[which] = { id, title };
    const input = C().$(`#wire-${which}-input`);
    const results = C().$(`#wire-${which}-results`);
    if (input) input.value = title || id;
    if (results) results.innerHTML = "";
  }

  async function createWire() {
    const message = C().$("#wire-message");
    if (!wireState.source || !wireState.target || !wireState.predicate) {
      if (message) message.textContent = "choose source, target, and predicate";
      return;
    }
    const body = {
      source_note: wireState.source.id,
      target_note: wireState.target.id,
      predicate: wireState.predicate,
      bidirectional: C().$("#wire-bidirectional")?.checked || false,
      emotional_valence: C().$("#wire-valence")?.value || null,
      energy_impact: C().$("#wire-energy")?.value || null,
      avoidance_risk: C().$("#wire-avoidance")?.value || null,
      growth_edge: C().$("#wire-growth")?.checked || false,
      current_state: C().$("#wire-state")?.value || null,
      reviewed: true,
      method: "interactive",
      confidence: "high",
    };
    try {
      const payload = await C().api("/api/wire/create", {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (message) {
        message.textContent = payload.created ? "wire created" : "wire updated";
      }
      await loadRecentWires();
    } catch (error) {
      if (message) message.textContent = error.message;
    }
  }

  async function loadRecentWires() {
    const output = C().$("#recent-wires");
    if (!output) return;
    try {
      const payload = await C().api("/api/wires?limit=60");
      const wires = payload.wires || [];
      output.innerHTML = wires.length ? wires.map((wire) => `
        <div class="wire-row">
          <strong>${C().escapeHtml(wire.source_note)} --${C().escapeHtml(wire.predicate)}--> ${C().escapeHtml(wire.target_note)}</strong>
          <div class="muted">${C().escapeHtml(wire.confidence || "unrated")} / ${C().escapeHtml(wire.method || "manual")}</div>
        </div>
      `).join("") : '<p class="muted">no wires yet</p>';
    } catch (error) {
      output.innerHTML = `<p class="error">${C().escapeHtml(error.message)}</p>`;
    }
  }

  async function discoverWire() {
    const output = C().$("#discover-output");
    if (!output) return;
    output.innerHTML = '<p class="muted">looking for a bridge...</p>';
    try {
      const payload = await C().api("/api/discover?threshold=0.1");
      const candidate = (payload.candidates || [])[0];
      if (!candidate) {
        output.innerHTML = '<p class="muted">no bridge candidates right now</p>';
        return;
      }
      const predicate = candidate.predicate || wireState.predicate || "relates_to";
      const reasons = candidateReasonText(candidate);
      output.innerHTML = `
        <div class="candidate-card">
          <strong>${C().escapeHtml(candidate.left_id)} -> ${C().escapeHtml(candidate.right_id)}</strong>
          <div class="muted">score ${C().escapeHtml(candidate.score ?? "")} / ${C().escapeHtml(predicate)}</div>
          <p>${C().escapeHtml(reasons || "similar note profile")}</p>
          <button class="small-button" type="button" id="accept-discovery">accept</button>
          <button class="small-button" type="button" id="customize-discovery">customize</button>
        </div>
      `;
      C().$("#accept-discovery")?.addEventListener("click", () => acceptDiscovery(candidate, predicate));
      C().$("#customize-discovery")?.addEventListener("click", () => {
        selectNote("source", candidate.left_id, candidate.left_title || candidate.left_id);
        selectNote("target", candidate.right_id, candidate.right_title || candidate.right_id);
        wireState.predicate = predicate;
        renderPredicates();
      });
    } catch (error) {
      output.innerHTML = `<p class="error">${C().escapeHtml(error.message)}</p>`;
    }
  }

  function candidateReasonText(candidate) {
    const reasons = candidate.reasons || {};
    const parts = [];
    if (Array.isArray(reasons.tags) && reasons.tags.length) {
      parts.push(`shared tags: ${reasons.tags.join(", ")}`);
    }
    if (Array.isArray(reasons.keywords) && reasons.keywords.length) {
      parts.push(`common terms: ${reasons.keywords.slice(0, 6).join(", ")}`);
    }
    if (reasons.type_match) {
      parts.push(`same type: ${candidate.left_type || "note"}`);
    }
    if (Array.isArray(reasons.links) && reasons.links.length) {
      parts.push(`shared links: ${reasons.links.slice(0, 4).join(", ")}`);
    }
    return parts.join(" / ");
  }

  async function acceptDiscovery(candidate, predicate) {
    const output = C().$("#discover-output");
    try {
      await C().api("/api/discover/accept", {
        method: "POST",
        body: JSON.stringify({
          ...candidate,
          predicate,
          weight: candidate.score || 0.7,
          confidence: "medium",
        }),
      });
      if (output) output.innerHTML = '<p class="muted">discovery accepted</p>';
      await loadRecentWires();
    } catch (error) {
      if (output) output.innerHTML = `<p class="error">${C().escapeHtml(error.message)}</p>`;
    }
  }

  function bindEvents() {
    C().$("#wire-source-input")?.addEventListener("input", C().debounce((event) => {
      wireState.source = null;
      searchNotes("source", event.target.value);
    }, 300));
    C().$("#wire-target-input")?.addEventListener("input", C().debounce((event) => {
      wireState.target = null;
      searchNotes("target", event.target.value);
    }, 300));
    C().$("#create-wire")?.addEventListener("click", createWire);
    C().$("#discover-wire")?.addEventListener("click", discoverWire);
  }

  function setSource(id, title) {
    wireState.source = { id, title };
    const input = C().$("#wire-source-input");
    const results = C().$("#wire-source-results");
    if (input) input.value = title || id;
    if (results) results.innerHTML = "";
  }

  window.CartWiring = {
    render,
    setSource,
  };
})();
