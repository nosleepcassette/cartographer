"""privacy.py — Three-tier privacy layer for person-to-person wires.

Privacy tiers:
  public        — wire visible, styling visible (if toggle on), label = predicate only
  inner-circle  — wire visible, styling visible, label = predicate + note, hover = full provenance
  private       — wire hidden, no styling, no label, nothing rendered

Privacy is SEPARATE from the emotional styling toggle:
  - Toggle controls whether colors/thickness reflect emotion (OFF = gray)
  - Privacy controls WHO can see the wire at all and how much detail
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class PrivacyTier(str, Enum):
    PUBLIC = "public"
    INNER_CIRCLE = "inner-circle"
    PRIVATE = "private"


# What each tier reveals in the graph view
TIER_VISIBILITY = {
    PrivacyTier.PUBLIC: {
        "wire_visible": True,
        "styling_visible": True,     # respects emotional toggle independently
        "label_content": "predicate_only",
        "hover_detail": "none",
    },
    PrivacyTier.INNER_CIRCLE: {
        "wire_visible": True,
        "styling_visible": True,
        "label_content": "predicate_and_note",
        "hover_detail": "full_provenance",
    },
    PrivacyTier.PRIVATE: {
        "wire_visible": False,
        "styling_visible": False,
        "label_content": None,
        "hover_detail": None,
    },
}


def resolve_privacy_tier(wire: dict[str, Any]) -> PrivacyTier:
    """Determine the privacy tier for a wire.

    Checks wire.get("privacy") and falls back to "public".
    Raises ValueError for unknown tier strings.
    """
    raw = str(wire.get("privacy", "public")).strip().lower()
    # Normalize common variations
    normalized = raw.replace(" ", "-").replace("_", "-")
    if normalized == "inner-circle" or normalized == "innercircle":
        return PrivacyTier.INNER_CIRCLE
    if normalized == "public":
        return PrivacyTier.PUBLIC
    if normalized == "private":
        return PrivacyTier.PRIVATE
    # Unknown tier — default to public with a warning
    return PrivacyTier.PUBLIC


def apply_privacy_filter(
    edges: list[dict[str, Any]],
    *,
    viewer_tier: PrivacyTier = PrivacyTier.PUBLIC,
) -> list[dict[str, Any]]:
    """Filter and redact edges based on the viewer's access tier.

    - private wires are removed entirely (not even a gray line)
    - public-tier viewers see predicate-only labels
    - inner-circle viewers see full labels and provenance

    Args:
        edges: list of edge payloads (from graph_extensions.build_edge_payloads)
        viewer_tier: the highest tier the current viewer can see

    Returns:
        filtered list with redacted labels where appropriate
    """
    filtered: list[dict[str, Any]] = []

    for edge in edges:
        wire_tier = resolve_privacy_tier(edge)

        # Private wires: completely invisible
        if wire_tier == PrivacyTier.PRIVATE:
            continue

        # If viewer can only see public, redact inner-circle details
        if viewer_tier == PrivacyTier.PUBLIC and wire_tier == PrivacyTier.INNER_CIRCLE:
            redacted = dict(edge)
            # Strip note/provenance from label — keep predicate only
            label_parts = redacted.get("label", "").split(" · ")
            if label_parts:
                redacted["label"] = label_parts[0]
            redacted.pop("note", None)
            redacted.pop("author", None)
            redacted.pop("method", None)
            redacted.pop("confidence", None)
            redacted.pop("reviewed_by", None)
            redacted.pop("reviewed_at", None)
            redacted.pop("review_duration_s", None)
            redacted["hover_detail"] = "none"
            filtered.append(redacted)
            continue

        # Full access — wire passes through as-is
        edge_copy = dict(edge)
        tier_config = TIER_VISIBILITY.get(wire_tier, TIER_VISIBILITY[PrivacyTier.PUBLIC])
        edge_copy["hover_detail"] = tier_config.get("hover_detail", "none")
        filtered.append(edge_copy)

    return filtered


def set_wire_privacy(
    wire: dict[str, Any],
    tier: PrivacyTier | str,
) -> dict[str, Any]:
    """Set the privacy tier on a wire dict.

    Returns a new dict with the privacy field updated.
    Does NOT mutate the original.
    """
    if isinstance(tier, str):
        tier = PrivacyTier(tier.replace(" ", "-").replace("_", "-").lower())
    updated = dict(wire)
    updated["privacy"] = tier.value
    return updated


def bulk_set_privacy(
    wires: list[dict[str, Any]],
    wire_ids: list[str],
    tier: PrivacyTier | str,
) -> list[dict[str, Any]]:
    """Set privacy tier on multiple wires by their IDs.

    wire IDs are matched against wire.get("id") or wire.get("wire_id").
    Returns new list — does not mutate originals.
    """
    id_set = set(wire_ids)
    result: list[dict[str, Any]] = []
    for wire in wires:
        wire_id = wire.get("id") or wire.get("wire_id")
        if wire_id in id_set:
            result.append(set_wire_privacy(wire, tier))
        else:
            result.append(dict(wire))
    return result


def privacy_summary(wires: list[dict[str, Any]]) -> dict[str, int]:
    """Count wires by privacy tier. Useful for status display."""
    counts: dict[str, int] = {"public": 0, "inner-circle": 0, "private": 0}
    for wire in wires:
        tier = resolve_privacy_tier(wire)
        counts[tier.value] += 1
    return counts
