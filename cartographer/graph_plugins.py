"""graph_plugins.py — Graph-rendering plugin loader for cartographer.

Extends the base plugin system to support plugins that modify the graph
HTML renderer with:
  - Template partials injected at named hook points
  - Predicate definitions (TOML) that extend edge styling
  - Privacy tier definitions
  - UI extensions (CSS + JS) for client-side interactivity

Graph-rendering plugins differ from CLI plugins:
  - CLI plugins are subprocess-based (JSON in, JSON out)
  - Graph plugins modify the HTML template before it's served
  - They run at template-render time, not as separate processes

A graph-rendering plugin directory must contain a plugin.toml with:
  [plugin]
  type = "graph-rendering"

And optionally:
  [plugin.hooks]       — maps hook names to template partial files
  [plugin.provides]    — declares predicates, privacy tiers, etc.
  [plugin.config]      — configurable defaults
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
BUILTIN_GRAPH_PLUGIN_DIR = PACKAGE_ROOT / "cartographer" / "plugins"

# Known hook names in the graph HTML template
KNOWN_HOOKS = {
    "wire_label",
    "wire_styling",
    "edge_rendering",
    "privacy_controls",
    "toolbar",
}


@dataclass
class GraphPlugin:
    """A loaded graph-rendering plugin with all its data resolved."""

    name: str
    version: str
    description: str
    extends: str
    author: str
    plugin_dir: Path
    hooks: dict[str, str] = field(default_factory=dict)
    provides: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    predicates: dict[str, Any] = field(default_factory=dict)
    ui_extensions: dict[str, str] = field(default_factory=dict)


def discover_graph_plugins() -> list[GraphPlugin]:
    """Scan the builtin plugin directory for graph-rendering plugins."""
    plugins: list[GraphPlugin] = []
    if not BUILTIN_GRAPH_PLUGIN_DIR.exists():
        return plugins
    for entry in sorted(BUILTIN_GRAPH_PLUGIN_DIR.iterdir()):
        if not entry.is_dir():
            continue
        toml_path = entry / "plugin.toml"
        if not toml_path.exists():
            continue
        plugin = load_graph_plugin(toml_path)
        if plugin is not None:
            plugins.append(plugin)
    return plugins


def load_graph_plugin(toml_path: Path) -> GraphPlugin | None:
    """Load a single graph-rendering plugin from its plugin.toml."""
    if tomllib is None:
        return None
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return None

    plugin_data = data.get("plugin", {})
    if not isinstance(plugin_data, dict):
        return None

    # Only load graph-rendering plugins
    plugin_type = str(plugin_data.get("type", "")).strip().lower()
    if plugin_type != "graph-rendering":
        return None

    plugin_dir = toml_path.resolve().parent

    # Load predicate definitions if declared
    predicates: dict[str, Any] = {}
    provides = data.get("plugin", {}).get("provides", {})
    if not isinstance(provides, dict):
        provides = {}
    predicates_ref = provides.get("predicates")
    if isinstance(predicates_ref, str) and predicates_ref.strip():
        pred_path = plugin_dir / predicates_ref.strip()
        if pred_path.exists():
            try:
                with open(pred_path, "rb") as f:
                    predicates = tomllib.load(f)
            except Exception:
                predicates = {}

    # Load hooks mapping
    hooks_data = plugin_data.get("hooks", {})
    if not isinstance(hooks_data, dict):
        hooks_data = {}

    # Load config
    config_data = plugin_data.get("config", {})
    if not isinstance(config_data, dict):
        config_data = {}

    return GraphPlugin(
        name=str(plugin_data.get("name", toml_path.parent.stem)).strip(),
        version=str(plugin_data.get("version", "0.0.0")).strip(),
        description=str(plugin_data.get("description", "")).strip(),
        extends=str(plugin_data.get("extends", "")).strip(),
        author=str(plugin_data.get("author", "")).strip(),
        plugin_dir=plugin_dir,
        hooks=hooks_data,
        provides=provides,
        config=config_data,
        predicates=predicates,
    )


def load_plugin_template(plugin: GraphPlugin, hook_name: str) -> str:
    """Load a template partial for a given hook from the plugin.

    Returns empty string if the hook isn't registered or the file doesn't exist.
    """
    template_file = plugin.hooks.get(hook_name, "")
    if not template_file:
        return ""
    path = plugin.plugin_dir / template_file
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def load_plugin_ui_extensions(plugin: GraphPlugin) -> dict[str, str]:
    """Load CSS + JS from a plugin's ui_extensions module.

    Tries to import and call inject_ui_extensions() from the plugin's
    ui_extensions.py. Falls back to empty dict if the module can't be loaded.
    """
    ui_path = plugin.plugin_dir / "ui_extensions.py"
    if not ui_path.exists():
        return {"css": "", "js": "", "toggle_html": ""}

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            f"cartographer.graph_plugins.{plugin.name}.ui_extensions",
            str(ui_path),
        )
        if spec is None or spec.loader is None:
            return {"css": "", "js": "", "toggle_html": ""}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "inject_ui_extensions"):
            result = module.inject_ui_extensions()
            if isinstance(result, dict):
                return result
    except Exception:
        pass

    return {"css": "", "js": "", "toggle_html": ""}


def inject_plugin_hooks(
    html: str,
    plugins: list[GraphPlugin],
) -> str:
    """Inject plugin template partials and UI extensions into the graph HTML.

    For each plugin:
      1. Replace <!-- PLUGIN_HOOK:name --> comments with template partials
      2. Inject plugin CSS before </style>
      3. Inject plugin JS before </script> (the last main script block)
      4. Add data-plugin-hook attributes for JS interactivity

    Falls back gracefully — missing hooks or templates don't break rendering.
    """
    if not plugins:
        return html

    # Collect all CSS and JS from plugins
    all_css: list[str] = []
    all_js: list[str] = []
    toggle_html_parts: list[str] = []

    for plugin in plugins:
        ui = load_plugin_ui_extensions(plugin)
        if ui.get("css"):
            all_css.append(f"/* ── Plugin: {plugin.name} ── */\n{ui['css']}")
        if ui.get("js"):
            all_js.append(f"// ── Plugin: {plugin.name} ──\n{ui['js']}")
        if ui.get("toggle_html"):
            toggle_html_parts.append(ui["toggle_html"])


    # Inject template partials at hook points
    # Support three hook formats:
    #   1. HTML comment: <!-- PLUGIN_HOOK:name -->
    #   2. CSS comment: /* PLUGIN_HOOK:name */
    #   3. JS comment: // PLUGIN_HOOK:name
    for plugin in plugins:
        for hook_name in KNOWN_HOOKS:
            partial = load_plugin_template(plugin, hook_name)
            if not partial:
                continue
            for hook_format in [
                f"<!-- PLUGIN_HOOK:{hook_name} -->",
                f"/* PLUGIN_HOOK:{hook_name} */",
                f"// PLUGIN_HOOK:{hook_name}",
            ]:
                if hook_format in html:
                    html = html.replace(hook_format, partial)

    # Inject CSS before the last </style>
    if all_css:
        combined_css = "\n".join(all_css)
        # Find the last </style> tag
        last_style_pos = html.rfind("</style>")
        if last_style_pos >= 0:
            html = html[:last_style_pos] + combined_css + "\n" + html[last_style_pos:]

    # Inject JS after the last </script> in the main body
    if all_js:
        combined_js = "\n".join(all_js)
        # Find the last </script> and insert AFTER it (not before)
        last_script_pos = html.rfind("</script>")
        if last_script_pos >= 0:
            insert_pos = last_script_pos + len("</script>")
            html = (
                html[:insert_pos]
                + f"\n<script>\n{combined_js}\n</script>\n"
                + html[insert_pos:]
            )

    # Inject toggle HTML into toolbar area
    if toggle_html_parts:
        toolbar_hook = '<!-- PLUGIN_HOOK:toolbar -->'
        # If the toolbar hook wasn't already replaced, try adding near
        # existing toolbar controls
        if toolbar_hook not in html:
            # Fallback: inject before the sidebar stats section
            stats_marker = '<div class="stat"><strong id="node-count">'
            combined_toggle = "\n".join(toggle_html_parts)
            if stats_marker in html:
                html = html.replace(
                    stats_marker,
                    combined_toggle + "\n" + stats_marker,
                    1,
                )

    return html


def plugin_predicate_lookup(
    plugins: list[GraphPlugin],
) -> dict[str, dict[str, Any]]:
    """Build a combined predicate lookup from all loaded plugins.

    Returns dict mapping predicate_key → {label, thickness, color, hex, ...}
    Merges love_spectrum and person_predicates from all plugins.
    Later plugins override earlier ones on conflict.
    """
    combined: dict[str, dict[str, Any]] = {}

    for plugin in plugins:
        love_spectrum = plugin.predicates.get("love_spectrum", {})
        love_order = love_spectrum.get("order", [])
        for key in love_order:
            pred_def = love_spectrum.get(key, {})
            if isinstance(pred_def, dict):
                combined[key] = {
                    "label": pred_def.get("label", key.replace("_", " ")),
                    "thickness": pred_def.get("thickness", 1),
                    "color": pred_def.get("hex", "#71717a"),
                    "category": "love_spectrum",
                    "position": love_order.index(key) + 1,
                }

        person_preds = plugin.predicates.get("person_predicates", {})
        for key, pred_def in person_preds.items():
            if isinstance(pred_def, dict):
                combined[key] = {
                    "label": pred_def.get("label", key.replace("_", " ")),
                    "thickness": pred_def.get("thickness", 1),
                    "color": pred_def.get("hex", "#71717a"),
                    "category": "person_predicates",
                }

    return combined


def plugin_privacy_tiers(plugins: list[GraphPlugin]) -> list[str]:
    """Collect all declared privacy tiers from plugins."""
    tiers: list[str] = ["public"]  # always available
    for plugin in plugins:
        declared = plugin.provides.get("privacy_tiers", [])
        if isinstance(declared, list):
            for tier in declared:
                tier_str = str(tier).strip()
                if tier_str and tier_str not in tiers:
                    tiers.append(tier_str)
    return tiers
