from __future__ import annotations

from pathlib import Path
from typing import Any

import tomllib

from .config import atlas_config_path


DEFAULT_PREDICATE_PALETTE = (
    "#7bb3ff",
    "#f0b35f",
    "#8fd3a4",
    "#ff8d8d",
    "#d4a7ff",
    "#7fe3de",
    "#f4df7a",
    "#b6c2cf",
)


def profiles_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "profiles"


def builtin_profile_names() -> list[str]:
    directory = profiles_dir()
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.toml") if path.is_file())


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    return payload if isinstance(payload, dict) else {}


def resolve_profile_path(profile_ref: str | Path | None) -> Path:
    if profile_ref is None:
        return profiles_dir() / "default.toml"
    candidate = str(profile_ref).strip()
    if not candidate:
        return profiles_dir() / "default.toml"
    if candidate.endswith(".toml") and ("/" in candidate or candidate.startswith(".")):
        return Path(candidate).expanduser()
    direct = Path(candidate).expanduser()
    if direct.exists():
        return direct
    builtin = profiles_dir() / f"{candidate.removesuffix('.toml')}.toml"
    if builtin.exists():
        return builtin
    raise FileNotFoundError(f"profile not found: {profile_ref}")


def load_profile(profile_ref: str | Path | None) -> dict[str, Any]:
    path = resolve_profile_path(profile_ref)
    payload = _load_toml(path)
    payload["_path"] = str(path)
    payload["_name"] = str(payload.get("name") or path.stem)
    return payload


def _config_wires(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    raw = config.get("wires", {})
    return raw if isinstance(raw, dict) else {}


def has_explicit_profile_config(config: dict[str, Any] | None) -> bool:
    wires = _config_wires(config)
    return any(
        key in wires
        for key in ("profile", "default_predicates", "metadata_fields", "predicate_colors")
    )


def active_profile_ref(
    atlas_root: Path | str,
    *,
    config: dict[str, Any] | None = None,
) -> str:
    wires = _config_wires(config)
    if isinstance(wires.get("profile"), str) and str(wires["profile"]).strip():
        return str(wires["profile"]).strip()
    if atlas_config_path(atlas_root).exists() and not has_explicit_profile_config(config):
        return "emotional-topology"
    return "default"


def active_profile(
    atlas_root: Path | str,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return load_profile(active_profile_ref(atlas_root, config=config))


def _wires_section(profile: dict[str, Any]) -> dict[str, Any]:
    raw = profile.get("wires", {})
    return raw if isinstance(raw, dict) else {}


def profile_predicates(profile: dict[str, Any]) -> list[str]:
    wires = _wires_section(profile)
    values = wires.get("default_predicates", [])
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def profile_metadata_fields(profile: dict[str, Any]) -> list[str]:
    wires = _wires_section(profile)
    values = wires.get("metadata_fields", [])
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def profile_predicate_colors(profile: dict[str, Any]) -> dict[str, str]:
    wires = _wires_section(profile)
    raw = wires.get("predicate_colors", {})
    mapping = raw if isinstance(raw, dict) else {}
    output: dict[str, str] = {}
    for index, predicate in enumerate(profile_predicates(profile)):
        color = mapping.get(predicate)
        if color is None or not str(color).strip():
            color = DEFAULT_PREDICATE_PALETTE[index % len(DEFAULT_PREDICATE_PALETTE)]
        output[predicate] = str(color).strip()
    return output


def profile_payload(
    atlas_root: Path | str,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = active_profile(atlas_root, config=config)
    return {
        "name": str(profile.get("_name") or "default"),
        "path": str(profile.get("_path") or ""),
        "description": str(profile.get("description") or ""),
        "default_predicates": profile_predicates(profile),
        "metadata_fields": profile_metadata_fields(profile),
        "predicate_colors": profile_predicate_colors(profile),
        "metadata_schema": profile.get("metadata", {}),
    }


def apply_profile_to_config(
    config: dict[str, Any],
    profile_ref: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = load_profile(profile_ref)
    profile_name = str(profile.get("_name") or "default")
    wires = config.setdefault("wires", {})
    wires["profile"] = profile_name if resolve_profile_path(profile_ref).parent == profiles_dir() else str(Path(profile_ref).expanduser())
    wires["default_predicates"] = profile_predicates(profile)
    wires["metadata_fields"] = profile_metadata_fields(profile)
    wires["predicate_colors"] = profile_predicate_colors(profile)
    return config, profile


def predicate_palette_payload(
    atlas_root: Path | str,
    *,
    config: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    payload = profile_payload(atlas_root, config=config)
    return [
        {"name": predicate, "color": payload["predicate_colors"].get(predicate, DEFAULT_PREDICATE_PALETTE[index % len(DEFAULT_PREDICATE_PALETTE)])}
        for index, predicate in enumerate(payload["default_predicates"])
    ]


def metadata_schema_payload(
    atlas_root: Path | str,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = profile_payload(atlas_root, config=config)
    raw = payload.get("metadata_schema", {})
    return raw if isinstance(raw, dict) else {}
