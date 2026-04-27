"""ui_extensions.py — Client-side UI extensions for the emotional-topology plugin.

This module generates the JavaScript and CSS that the graph renderer injects
into the HTML template. It provides:

1. Hover-to-expand — CSS/JS for expanding a compact wire label into
   full provenance detail on hover/click
2. E key toggle — per-session emotional styling toggle (default OFF)
3. Edge grouping — collapsible wire bundles by predicate category
4. Privacy dropdown — per-wire privacy tier selector in expanded view

The graph renderer calls inject_ui_extensions() to get the combined
CSS + JS as strings that get inserted at the toolbar and edge_rendering
template hooks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _read_template(name: str) -> str:
    """Read a template partial from the templates/ directory."""
    path = Path(__file__).resolve().parent / "templates" / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


# ── CSS for hover-to-expand ───────────────────────────────

HOVER_EXPAND_CSS = """\
/* ── Emotional Topology: hover-to-expand ── */
.et-wire-label {
  cursor: pointer;
  transition: background 0.15s ease;
  padding: 2px 6px;
  border-radius: 3px;
}
.et-wire-label:hover {
  background: rgba(255, 255, 255, 0.08);
}

.et-wire-expand {
  display: none;
  position: absolute;
  z-index: 100;
  background: #1a1a2e;
  border: 1px solid #334155;
  border-radius: 6px;
  padding: 12px 16px;
  min-width: 280px;
  max-width: 420px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  font-size: 13px;
  line-height: 1.6;
  color: #e2e8f0;
}
.et-wire-expand.et-visible {
  display: block;
}
.et-wire-expand .et-field {
  display: flex;
  justify-content: space-between;
  padding: 2px 0;
  border-bottom: 1px solid #1e293b;
}
.et-wire-expand .et-field:last-child {
  border-bottom: none;
}
.et-wire-expand .et-field-key {
  color: #94a3b8;
  min-width: 100px;
}
.et-wire-expand .et-field-val {
  text-align: right;
  color: #f1f5f9;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.et-wire-expand .et-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}
.et-wire-expand .et-actions button {
  background: #334155;
  border: 1px solid #475569;
  color: #e2e8f0;
  padding: 4px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}
.et-wire-expand .et-actions button:hover {
  background: #475569;
}
"""


# ── CSS for emotional toggle ──────────────────────────────

EMOTIONAL_TOGGLE_CSS = """\
/* ── Emotional Topology: toggle indicator ── */
.et-toggle-badge {
  position: fixed;
  bottom: 16px;
  right: 16px;
  z-index: 200;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: 0.02em;
  pointer-events: none;
  user-select: none;
  transition: all 0.2s ease;
}
.et-toggle-badge.et-off {
  background: rgba(30, 41, 59, 0.85);
  color: #94a3b8;
  border: 1px solid #334155;
}
.et-toggle-badge.et-on {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
  border: 1px solid rgba(245, 158, 11, 0.4);
}
"""


# ── CSS for edge grouping ────────────────────────────────

EDGE_GROUPING_CSS = """\
/* ── Emotional Topology: edge grouping ── */
.et-edge-group {
  cursor: pointer;
  transition: opacity 0.15s ease;
}
.et-edge-group:hover {
  opacity: 0.85;
}
.et-edge-group-label {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 4px;
  background: rgba(30, 41, 59, 0.7);
  color: #cbd5e1;
  border: 1px solid #334155;
  display: inline-block;
  margin: 2px 0;
}
.et-edge-group-label .et-count {
  color: #94a3b8;
  margin-right: 4px;
}
"""


# ── CSS for privacy dropdown ──────────────────────────────

PRIVACY_DROPDOWN_CSS = """\
/* ── Emotional Topology: privacy dropdown ── */
.et-privacy-select {
  background: #1e293b;
  border: 1px solid #475569;
  color: #e2e8f0;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}
.et-privacy-select:focus {
  outline: 1px solid #f59e0b;
  border-color: #f59e0b;
}
"""


# ── JavaScript: emotional toggle ──────────────────────────

EMOTIONAL_TOGGLE_JS = """\
// ── Emotional Topology: E key toggle ──
(function() {
  let emotionalStylingOn = false;

  function updateToggleBadge() {
    const badge = document.getElementById('et-toggle-badge');
    if (!badge) return;
    badge.className = 'et-toggle-badge ' + (emotionalStylingOn ? 'et-on' : 'et-off');
    badge.textContent = emotionalStylingOn ? '🔓 emotional: on [L]' : '🔒 emotional: off [L]';
  }

  function applyEmotionalStyling() {
    // Dispatch custom event for the graph renderer to pick up
    const event = new CustomEvent('et:styling-toggle', {
      detail: { emotionalStylingOn: emotionalStylingOn },
      bubbles: true,
    });
    document.dispatchEvent(event);

    // Also update edge visuals directly if the renderer exposes them
    if (typeof window._cartographerApplyEmotionalStyling === 'function') {
      window._cartographerApplyEmotionalStyling(emotionalStylingOn);
    }
  }

 document.addEventListener('keydown', function(e) {
 if (e.key === 'l' || e.key === 'L') {
 // Don't toggle if user is typing in an input
 if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
 return;
 }
 emotionalStylingOn = !emotionalStylingOn;
 updateToggleBadge();
 applyEmotionalStyling();
 // Sync the sidebar checkbox
 const cb = document.getElementById('emotional-styling');
 if (cb) { cb.checked = emotionalStylingOn; cb.closest('.toggle')?.classList.toggle('active', emotionalStylingOn); }
 e.preventDefault();
 }
 });

  // Initialize badge on DOM ready
  function initBadge() {
    if (document.getElementById('et-toggle-badge')) return;
    const badge = document.createElement('div');
    badge.id = 'et-toggle-badge';
    badge.className = 'et-toggle-badge et-off';
    badge.textContent = '🔒 emotional: off';
    document.body.appendChild(badge);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBadge);
  } else {
    initBadge();
  }

 // Expose state for other modules
 window._etEmotionalStylingOn = function() { return emotionalStylingOn; };

 // Wire the sidebar checkbox to the same toggle
 function wireCheckbox() {
 const cb = document.getElementById('emotional-styling');
 if (!cb) return;
 cb.checked = emotionalStylingOn;
 cb.closest('.toggle')?.classList.toggle('active', emotionalStylingOn);
 cb.addEventListener('change', function() {
 emotionalStylingOn = cb.checked;
 updateToggleBadge();
 applyEmotionalStyling();
 });
 }

 if (document.readyState === 'loading') {
 document.addEventListener('DOMContentLoaded', wireCheckbox);
 } else {
 wireCheckbox();
 }

 // Initialize emotional styling to OFF on page load.
 // This ensures love-spectrum edges render neutral until toggled.
 function initEmotionalStyling() {
 if (typeof window._cartographerApplyEmotionalStyling === 'function') {
 window._cartographerApplyEmotionalStyling(false);
 }
 }
 // Wait for the 3D graph to finish building edges
 if (document.readyState === 'loading') {
 document.addEventListener('DOMContentLoaded', function() {
 setTimeout(initEmotionalStyling, 500);
 });
 } else {
 setTimeout(initEmotionalStyling, 500);
 }
})();
"""


# ── JavaScript: hover-to-expand ───────────────────────────

HOVER_EXPAND_JS = """\
// ── Emotional Topology: hover-to-expand ──
(function() {
  let activeExpand = null;

  function hideExpand() {
    if (activeExpand) {
      activeExpand.classList.remove('et-visible');
      activeExpand = null;
    }
  }

  function showExpand(labelEl, edgeData) {
    hideExpand();

    // Build expand panel
    const panel = document.createElement('div');
    panel.className = 'et-wire-expand';

    const fields = [
      ['Source → Target', (edgeData.source || '?') + ' → ' + (edgeData.target || '?')],
      ['Predicate', edgeData.predicate || '—'],
    ];

    // State modifiers
    if (edgeData.state_modifiers && edgeData.state_modifiers.length) {
      fields.push(['State', edgeData.state_modifiers.join(' · ')]);
    }
    if (edgeData.note) fields.push(['Note', edgeData.note]);
    if (edgeData.author) fields.push(['Author', edgeData.author]);
    if (edgeData.method) fields.push(['Method', edgeData.method]);
    if (edgeData.confidence) fields.push(['Confidence', edgeData.confidence]);
    if (edgeData.reviewed !== undefined) {
      const reviewedLabel = edgeData.reviewed ? 'yes' + (edgeData.reviewed_at ? ' (' + edgeData.reviewed_at + ')' : '') : 'no';
      fields.push(['Reviewed', reviewedLabel]);
    }
    if (edgeData.review_duration_s) {
      const mins = Math.round(edgeData.review_duration_s / 60);
      fields.push(['Review duration', mins + 'm']);
    }
    if (edgeData.privacy) fields.push(['Privacy', edgeData.privacy]);

    for (const [key, val] of fields) {
      const row = document.createElement('div');
      row.className = 'et-field';
      row.innerHTML = '<span class="et-field-key">' + key + '</span><span class="et-field-val">' + escHtml(String(val)) + '</span>';
      panel.appendChild(row);
    }

    // Action buttons
    const actions = document.createElement('div');
    actions.className = 'et-actions';
    for (const [label, action] of [['Edit', 'edit'], ['Review', 'review'], ['Delete', 'delete']]) {
      const btn = document.createElement('button');
      btn.textContent = label;
      btn.setAttribute('data-action', action);
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        const evt = new CustomEvent('et:wire-action', {
          detail: { action: action, edge: edgeData },
          bubbles: true,
        });
        document.dispatchEvent(evt);
        hideExpand();
      });
      actions.appendChild(btn);
    }
    panel.appendChild(actions);

    // Privacy dropdown (if inner-circle or admin)
    if (edgeData.hover_detail === 'full_provenance') {
      const privacyRow = document.createElement('div');
      privacyRow.className = 'et-field';
      privacyRow.style.marginTop = '8px';
      privacyRow.style.borderTop = '1px solid #334155';
      privacyRow.style.paddingTop = '8px';
      privacyRow.innerHTML = '<span class="et-field-key">Set privacy</span>';
      const select = document.createElement('select');
      select.className = 'et-privacy-select';
      for (const [val, label] of [['public', 'Public'], ['inner-circle', 'Inner Circle'], ['private', 'Private']]) {
        const opt = document.createElement('option');
        opt.value = val;
        opt.textContent = label;
        if (edgeData.privacy === val) opt.selected = true;
        select.appendChild(opt);
      }
      select.addEventListener('change', function() {
        const evt = new CustomEvent('et:privacy-change', {
          detail: { edge: edgeData, newTier: select.value },
          bubbles: true,
        });
        document.dispatchEvent(evt);
      });
      privacyRow.appendChild(select);
      panel.appendChild(privacyRow);
    }

    // Position near the label
    const rect = labelEl.getBoundingClientRect();
    panel.style.left = Math.min(rect.left, window.innerWidth - 440) + 'px';
    panel.style.top = (rect.bottom + 8) + 'px';
    document.body.appendChild(panel);
    activeExpand = panel;

    // Show on next frame (allows positioning)
    requestAnimationFrame(function() {
      panel.classList.add('et-visible');
    });
  }

  function escHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // Close on click outside
  document.addEventListener('click', function(e) {
    if (activeExpand && !activeExpand.contains(e.target)) {
      hideExpand();
    }
  });

  // Close on Escape
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') hideExpand();
  });

  // Expose for graph renderer to call when wiring up edge labels
  window._etShowExpand = showExpand;
  window._etHideExpand = hideExpand;
})();
"""


# ── JavaScript: edge grouping ─────────────────────────────

EDGE_GROUPING_JS = """\
// ── Emotional Topology: edge grouping ──
(function() {
  // When a group label is clicked, expand to show individual wires
  document.addEventListener('click', function(e) {
    const groupEl = e.target.closest('.et-edge-group-label');
    if (!groupEl) return;

    const groupId = groupEl.getAttribute('data-group-id');
    if (!groupId) return;

    const container = groupEl.closest('.et-group-container');
    if (!container) return;

    const detail = container.querySelector('.et-group-detail');
    if (!detail) return;

    const isExpanded = detail.style.display !== 'none';
    detail.style.display = isExpanded ? 'none' : 'block';
    groupEl.setAttribute('data-expanded', String(!isExpanded));
  });

  // Expose for renderer
  window._etToggleGroup = function(groupId) {
    const label = document.querySelector('[data-group-id="' + groupId + '"]');
    if (label) label.click();
  };
})();
"""


# ── Combined injection ────────────────────────────────────

def inject_ui_extensions() -> dict[str, str]:
    """Return combined CSS and JS for all UI extensions.

    Returns dict with keys:
      css: all combined CSS
      js: all combined JS
      toggle_html: the badge HTML (for toolbar hook)
    """
    css = "\n".join([
        "/* ═══ Emotional Topology Plugin — UI Extensions ═══ */",
        HOVER_EXPAND_CSS,
        EMOTIONAL_TOGGLE_CSS,
        EDGE_GROUPING_CSS,
        PRIVACY_DROPDOWN_CSS,
    ])

    js = "\n".join([
        "// ═══ Emotional Topology Plugin — UI Extensions ═══",
        EMOTIONAL_TOGGLE_JS,
        HOVER_EXPAND_JS,
        EDGE_GROUPING_JS,
    ])

    # The badge is created by JS, but we provide a placeholder
    # for the toolbar hook in case the template wants static HTML
    toggle_html = (
        '<div id="et-toggle-badge" class="et-toggle-badge et-off">'
        '🔒 emotional: off'
        '</div>'
    )

    return {
        "css": css,
        "js": js,
        "toggle_html": toggle_html,
    }
