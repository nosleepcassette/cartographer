# QMD Optional Integration — Parallel Track

# maps · cassette.help · MIT
# Status: BUILT — plain-text `cart query` + `cart qmd bootstrap`
# Date: 2026-04-17
# Audience: codex (build); maps (design lead review)

---

## Principle

QMD is an **enhancement**, not a dependency. Cart ships and develops its extant workflow unchanged. Users with qmd installed get better search; users without it lose nothing.

No feature ever *requires* qmd. No code path is made less capable by the check. The integration is one `shutil.which("qmd")` away from being entirely transparent.

---

## Integration Surface

| Cart command | Default behavior | With qmd |
|---|---|---|
| `cart query <plain text>` | Built-in SQLite/FTS atlas query | qmd hybrid query, still atlas-scoped |
| `cart query <structured tokens>` | Built-in structured query | unchanged |
| `cart qmd bootstrap` | no-op / unavailable | create atlas collection, write config, run `qmd embed` |
| Session save hook | existing index refresh | trigger `qmd embed --incremental` if qmd present |

Everything else in cart (ingest, session mgmt, graph, planner, tasks, TUI filter) stays exactly as-is.

---

## Detection

Single module: `cartographer/integrations/qmd.py`

```python
# cartographer/integrations/qmd.py
"""Optional qmd integration. Never raises when qmd is absent."""
from __future__ import annotations
import json, shutil, subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

QMD_BIN = "qmd"

def is_available() -> bool:
    return shutil.which(QMD_BIN) is not None

@dataclass
class QmdHit:
    path: str
    docid: str
    score: float
    snippet: str
    collection: str | None

def query(q: str, *, collection: str | None = None, n: int = 10,
          min_score: float = 0.3, mode: str = "query") -> list[QmdHit]:
    """mode ∈ {'search','vsearch','query'}. Returns [] if qmd missing or errors."""
    if not is_available():
        return []
    cmd = [QMD_BIN, mode, q, "--json", "-n", str(n), "--min-score", str(min_score)]
    if collection:
        cmd += ["-c", collection]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if out.returncode != 0:
            return []
        data = json.loads(out.stdout or "[]")
        return [QmdHit(**_normalize(h)) for h in data]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return []

def embed_incremental() -> None:
    """Best-effort re-index. Silent if qmd missing."""
    if not is_available():
        return
    subprocess.Popen(
        [QMD_BIN, "embed", "--incremental"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

def _normalize(hit: dict) -> dict:
    return {
        "path": hit.get("path") or hit.get("file") or "",
        "docid": hit.get("docid") or hit.get("id") or "",
        "score": float(hit.get("score", 0.0)),
        "snippet": hit.get("snippet") or hit.get("content", "")[:400],
        "collection": hit.get("collection"),
    }
```

**Contract:** this module **never raises** to callers. Missing qmd returns empty list / no-op. Call sites check `if hits:` and fall through to the existing implementation when empty.

---

## Call Site Pattern

```python
# cartographer/cli.py (or wherever cart recall lives)
from cartographer.integrations import qmd

def cmd_recall(args):
    # Try qmd first
    hits = qmd.query(args.query, n=args.limit)
    if hits:
        return _render_qmd_hits(hits, args)
    # Fall through to existing implementation
    return _legacy_recall(args)
```

Never invert: never prefer legacy when qmd is present. Never gate a new feature on qmd.

---

## Setup UX

`cart qmd bootstrap` — implemented subcommand, runs only if qmd is on PATH:

```
cart qmd bootstrap
  → detects qmd
  → creates or reuses a collection pointing at the current atlas root
  → writes `qmd.default_collection` into atlas config
  → adds a context string if the collection was newly created
  → runs `qmd embed`
  → prints next-step hint
```

If qmd is missing: print one line — "qmd not installed; cart will use built-in search. See https://github.com/tobilu/qmd to enable enhanced recall." — and exit 0. Never error.

---

## Config

Add optional section to cart's config file (do **not** add required keys):

```toml
[qmd]
enabled = "auto"          # auto | off | on (on = error if missing)
default_collection = "atlas"   # written by `cart qmd bootstrap`; blank = auto-detect atlas collection
min_score = 0.35
incremental_on_save = true
```

Default when omitted: `enabled = "auto"`. Everything works without this section.

---

## Testing

- `tests/test_qmd_integration.py` — mock `shutil.which` returning None, assert all qmd calls return empty / no-op
- Same file — mock `subprocess.run` returning fake JSON, assert parsing is correct
- **No test may fail on a machine without qmd installed.** CI must pass with qmd absent.

---

## Non-Goals

- No re-implementation of qmd functionality in Python fallback
- No attempt to write embeddings ourselves
- No requiring a specific qmd version (parse its JSON defensively)
- No coupling cart's data model to qmd's

---

## Shipped

1. qmd integration module + tests
2. atlas-scoped plain-text `cart query`
3. `cart qmd bootstrap`
4. README docs under optional enhanced search

TUI `/` remains the existing title/id filter for now.

---

## Open Questions (for design-lead review)

1. Does cart already have a unified search renderer, or are `recall` / `search` / TUI palette each rendering differently? (Dictates how much we dedupe in `_render_qmd_hits`.)
2. Should `qmd embed --incremental` fire on every session save, or debounced (e.g. every 5 min)? Debounce is safer on big vaults.
3. Does cart want its own collection prefix (`cart://sessions`) or share the user's global qmd collections? Separate prefix = cleaner teardown, shared = one index to rule them all.
