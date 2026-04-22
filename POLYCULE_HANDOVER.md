# Polycule Handover

Date: 2026-04-22
Repo: `cartographer`
Current pushed commit: `2ebf08b` (`feat(v0.5): graph workspace — profiles, provenance, and live editing`)

## What Shipped This Session

- v0.5 is now effectively live in cartographer.
- Profiles are in: neutral `default` plus full `emotional-topology`.
- `cart discover` is now a first-class entry point, including `--interactive`, `--export`, and auto-discovery on profile apply.
- `cart think` was renamed to `cart trace` at the UI/CLI level. Hidden alias remains for compatibility.
- Wire provenance is now part of the real substrate, not just docs:
  - `author`
  - `method`
  - `reviewed`
  - `reviewed_by`
  - `reviewed_at`
  - `review_duration_s`
  - `confidence`
  - `note`
- The live graph is now a workspace, not just an export:
  - trace mode
  - discover overlay
  - unreviewed filter
  - profile-driven predicate palette
  - inline wire create/edit/review/delete via local HTTP APIs
  - discover accept back into Markdown from the graph UI

## Files To Read First

- [README.md](/Users/maps/dev/cartographer/README.md)
- [cartographer/profiles.py](/Users/maps/dev/cartographer/cartographer/profiles.py)
- [profiles/default.toml](/Users/maps/dev/cartographer/profiles/default.toml)
- [profiles/emotional-topology.toml](/Users/maps/dev/cartographer/profiles/emotional-topology.toml)
- [cartographer/graph_serve.py](/Users/maps/dev/cartographer/cartographer/graph_serve.py)
- [cartographer/graph_export.py](/Users/maps/dev/cartographer/cartographer/graph_export.py)
- [cartographer/wires.py](/Users/maps/dev/cartographer/cartographer/wires.py)
- [tests/test_profiles_and_trace.py](/Users/maps/dev/cartographer/tests/test_profiles_and_trace.py)
- [tests/test_graph_serve.py](/Users/maps/dev/cartographer/tests/test_graph_serve.py)

## CLI Surface You Should Assume

- `cart profile list`
- `cart profile apply <name>`
- `cart discover`
- `cart discover --interactive`
- `cart discover --export`
- `cart discover --accept`
- `cart trace <note>`
- `cart wire review`
- `cart graph --serve`

Important:
- `cart think` is now a hidden compatibility alias, not the primary name.
- `cart profile apply <name>` must auto-run discover and tell the user how many new candidates were found.
- Existing atlases must not be silently forced onto the neutral profile.

## Profiles + Config Rules

The config layer changed.

New/default profile behavior:
- New neutral predicate defaults live under `[wires]`.
- Built-in profiles are shipped from repo `profiles/`.
- Existing atlases without explicit profile wiring config are treated as `emotional-topology` for compatibility.
- Programmatic `Atlas.init()` defaults to `emotional-topology` for compatibility.
- CLI `cart init` explicitly chooses `default` unless the user selects otherwise.

What agents should assume when touching config:
- `config.toml` may now have:
  - `wires.profile`
  - `wires.default_predicates`
  - `wires.metadata_fields`
  - `wires.predicate_colors`
- Predicate color comes from the active profile, not hardcoded graph logic.
- The neutral/default graph profile is general-purpose.
- The emotional-topology profile is intentionally specific and should not be normalized away.

## Wiring Rules

Wires are still file-native HTML comments. SQLite remains a cache only.

If you are writing or mutating wires programmatically:
- prefer using the real wire helpers in [wires.py](/Users/maps/dev/cartographer/cartographer/wires.py)
- preserve file-backed truth
- refresh the index after writes

Provenance expectations:
- agent-created discover/batch wires should carry provenance
- reviewed interactive paths should carry review timing and confidence when available
- manual compatibility still matters

Important compatibility nuance:
- plain `cart wire add` was left minimally formatted for older expectations/tests
- do not assume every manual wire comment includes the full provenance payload
- do assume discover/review/graph workspace paths can include provenance-rich metadata

## Graph Workspace APIs

Live graph server now exposes:

GET:
- `/`
- `/status`
- `/reload`
- `/api/predicates`
- `/api/trace?note=<id>&depth=<n>`
- `/api/discover?format=json`
- `/api/discover?format=json&note=<id>`
- `/themes/*.js`

POST:
- `/api/wire/create`
- `/api/wire/update`
- `/api/wire/review`
- `/api/wire/delete`
- `/api/discover/accept`

Interpretation:
- these APIs are localhost graph-workspace endpoints
- they are designed so a future daemon can absorb them cleanly
- do not rebuild a separate graph mutation system unless there is a very strong reason

## Theme / Atlas Side Notes

Atlas-local theme files were updated locally in the separate atlas repo:
- `/Users/maps/atlas/themes/template.js`
- `/Users/maps/atlas/themes/synaptic-vesper.js`
- `/Users/maps/atlas/themes/README.md`

They now mark explicit v0.5 compliance and expose a runtime edge-style hook.

If you work on theme-side graph behavior:
- treat `template.js` as the canonical compatibility marker file
- preserve `synaptic-vesper.js` structure; add to it, do not flatten it into generic theme code
- predicate colors must come from `/api/predicates`
- reviewed/manual edges should read solid
- unreviewed agent/interactive edges should read dashed and dimmer

## Non-Negotiable User Constraints

This matters. Do not regress it.

- `maps` must remain visible and non-redacted in actual config/code behavior.
- The earlier `grungler` / `chungus` substitution is for `README.md` examples only.
- Do not replace real config/code semantics with placeholder names.
- If you need functional placeholder people in README examples, use `grungler` or `chungus`.
- Do not put actual personal graph names into the README.

Concretely:
- actual graph config defaults in code keep `maps` visible/non-redacted
- README examples may use placeholders, but should not imply hiding/redacting `maps`

## Current Reality For Future Agents

What is already true:
- full suite is green
- v0.5 graph workspace behavior exists
- graph serve daemon support exists from earlier work
- v0.5 did not add new daemon architecture beyond the existing serve flow

What not to accidentally undo:
- profile compatibility behavior for existing atlases
- `maps` visibility / non-redaction in code
- provenance fields in wire parsing/indexing/querying/stats
- graph mutation endpoints
- trace rename

## Verification

Latest clean verification on this branch:

```bash
uv run --with pytest pytest -q
```

Result:
- `97 passed in 51.55s`

## If You’re A Fresh Codex

Before touching anything in this area:
1. Read [POLYCULE_HANDOVER.md](/Users/maps/dev/cartographer/POLYCULE_HANDOVER.md).
2. Read [README.md](/Users/maps/dev/cartographer/README.md).
3. Read [profiles/emotional-topology.toml](/Users/maps/dev/cartographer/profiles/emotional-topology.toml).
4. Read [graph_serve.py](/Users/maps/dev/cartographer/cartographer/graph_serve.py) and [graph_export.py](/Users/maps/dev/cartographer/cartographer/graph_export.py).
5. Respect the README-only placeholder-name rule.
6. Do not break existing-atlas compatibility.
