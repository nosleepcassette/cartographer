from __future__ import annotations

import math
import random
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import load_config
from .index import Index
from .notes import Note


STATE_RE = re.compile(r"^- state:\s*(.+)$", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^- \[(?P<done>[ xX])\]", re.MULTILINE)
EMOTIONAL_KEYWORDS = {
    "grief",
    "sad",
    "anxious",
    "hope",
    "joy",
    "panic",
    "lonely",
    "overwhelm",
    "stable",
    "thriving",
    "surviving",
    "depleted",
}

SIGNAL_PAIRS = [
    (
        "state_transition",
        "wire_activity",
        48,
        "Wire activity in the {lead}h before state transitions",
    ),
    (
        "wire_activity",
        "state_transition",
        48,
        "State transitions in the {lead}h after wire activity changes",
    ),
    (
        "high_valence_wire",
        "session_frequency",
        72,
        "Agent session frequency {lead}h after high-valence wire activation",
    ),
    (
        "session_frequency",
        "wire_creation",
        24,
        "Wire creation {lead}h after high agent activity",
    ),
    (
        "intention_misses",
        "state_drop",
        48,
        "State drops {lead}h after intention tracking misses",
    ),
    (
        "daily_word_count",
        "state_stability",
        24,
        "State stability correlation with journaling volume",
    ),
    (
        "access_hot_notes",
        "wire_activity",
        48,
        "Wire activity {lead}h after frequently-accessed notes",
    ),
    (
        "operating_truth_churn",
        "state_transition",
        24,
        "State transitions {lead}h after operating truth changes",
    ),
]


@dataclass(slots=True)
class StateSnapshot:
    timestamp: float
    date: str
    state: str


@dataclass(slots=True)
class StateTransition:
    timestamp: float
    from_state: str
    to_state: str


@dataclass(slots=True)
class WireEvent:
    timestamp: float
    source: str
    target: str
    predicate: str
    event_type: str
    emotional_valence: str | None = None


@dataclass(slots=True)
class SessionCount:
    date: str
    count: int
    agents: list[str]


@dataclass(slots=True)
class DailyData:
    date: str
    word_count: int
    intentions_met: int
    intentions_total: int
    emotional_keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AccessEvent:
    timestamp: float
    note_id: str
    access_count: int
    access_type: str


@dataclass(slots=True)
class CorrelationResult:
    signal_a: str
    signal_b: str
    lead_hours: int
    correlation: float
    n_buckets: int
    p_value: float
    significant: bool
    description: str
    buckets: list[tuple[float, float, float]] = field(default_factory=list)


@dataclass(slots=True)
class PatternReport:
    title: str
    correlations: list[CorrelationResult]
    summary: str
    counter_evidence: list[str]
    recommendation: str


def _config(atlas_root: Path | str) -> dict[str, Any]:
    config = load_config(root=atlas_root)
    raw = config.get("temporal_patterns", {}) if isinstance(config, dict) else {}
    return raw if isinstance(raw, dict) else {}


def _db_path(atlas_root: Path | str) -> Path:
    return Path(atlas_root).expanduser() / ".cartographer" / "index.db"


def _parse_iso_timestamp(value: str | None) -> float | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    for attempt in (candidate, candidate[:10]):
        try:
            parsed = datetime.fromisoformat(attempt)
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed.timestamp()
    return None


def _day_timestamp(day: str) -> float:
    return datetime.fromisoformat(day[:10]).timestamp()


def _bucket_start(timestamp: float, bucket_hours: int) -> float:
    width = float(max(bucket_hours, 1) * 3600)
    return math.floor(timestamp / width) * width


def pearson_correlation(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3 or n != len(ys):
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n
    std_x = (sum((x - mean_x) ** 2 for x in xs) / n) ** 0.5
    std_y = (sum((y - mean_y) ** 2 for y in ys) / n) ** 0.5
    if std_x == 0.0 or std_y == 0.0:
        return 0.0
    return cov / (std_x * std_y)


def _state_key(value: str) -> str:
    candidate = str(value).strip().lower()
    candidate = candidate.split("(", 1)[0].strip()
    candidate = candidate.split("→", 1)[-1].strip() if "→" in candidate else candidate
    return candidate


def _state_capacity(value: str) -> float:
    state = _state_key(value)
    table = {
        "thriving": 5.0,
        "grounded": 4.5,
        "rising": 4.2,
        "stable": 4.0,
        "building": 3.8,
        "recovering": 3.3,
        "surviving": 2.0,
        "depleted": 1.8,
        "grieving": 1.7,
        "shutdown": 1.0,
        "collapsed": 0.7,
        "crisis": 0.3,
    }
    for key, score in table.items():
        if key in state:
            return score
    return 2.5


def _signal_domains() -> dict[str, set[str]]:
    return {
        "state": {"state_transition", "state_drop", "state_stability", "operating_truth_churn"},
        "wires": {"wire_activity", "high_valence_wire", "wire_creation"},
        "sessions": {"session_frequency"},
        "daily": {"intention_misses", "daily_word_count"},
        "access": {"access_hot_notes"},
    }


class TemporalPatternDetector:
    """Detect cross-dimensional temporal correlations across the atlas."""

    def __init__(self, atlas_root: Path | str):
        self.atlas_root = Path(atlas_root).expanduser()
        self.db_path = _db_path(self.atlas_root)
        self.config = _config(self.atlas_root)
        self._rng = random.Random(0)

    def _connect(self) -> sqlite3.Connection:
        Index(self.atlas_root)
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _mapsos_snapshot_paths(self) -> list[Path]:
        directory = self.atlas_root / "agents" / "mapsOS"
        if not directory.exists():
            return []
        return sorted(
            path
            for path in directory.glob("*.md")
            if path.name not in {"state-log.md", "intake-index.md"}
        )

    def _load_state_snapshots(self) -> list[StateSnapshot]:
        snapshots: list[StateSnapshot] = []
        for path in self._mapsos_snapshot_paths():
            try:
                note = Note.from_file(path)
            except Exception:
                continue
            state = str(note.frontmatter.get("state") or "").strip()
            if not state:
                match = STATE_RE.search(note.body)
                if match is not None:
                    state = match.group(1).strip()
            if not state:
                continue
            day = str(
                note.frontmatter.get("date")
                or note.frontmatter.get("created")
                or path.stem[:10]
            ).strip()[:10]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                continue
            snapshots.append(
                StateSnapshot(
                    timestamp=_day_timestamp(day),
                    date=day,
                    state=state,
                )
            )
        snapshots.sort(key=lambda item: item.timestamp)
        return snapshots

    def load_state_transitions(self) -> list[StateTransition]:
        snapshots = self._load_state_snapshots()
        transitions: list[StateTransition] = []
        previous: StateSnapshot | None = None
        for snapshot in snapshots:
            if previous is not None and _state_key(previous.state) != _state_key(snapshot.state):
                transitions.append(
                    StateTransition(
                        timestamp=snapshot.timestamp,
                        from_state=previous.state,
                        to_state=snapshot.state,
                    )
                )
            previous = snapshot
        return transitions

    def load_wire_activity(self) -> list[WireEvent]:
        events: list[WireEvent] = []
        with self._connect() as connection:
            wire_rows = connection.execute(
                """
                SELECT source_note, target_note, predicate, emotional_valence, since
                FROM wires
                """
            ).fetchall()
        for row in wire_rows:
            since = _parse_iso_timestamp(None if row["since"] is None else str(row["since"]))
            if since is None:
                continue
            events.append(
                WireEvent(
                    timestamp=since,
                    source=str(row["source_note"]),
                    target=str(row["target_note"]),
                    predicate=str(row["predicate"]),
                    event_type="created",
                    emotional_valence=None
                    if row["emotional_valence"] is None
                    else str(row["emotional_valence"]),
                )
            )

        for section in ("entities", "projects"):
            directory = self.atlas_root / section
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*.md")):
                if path.name == "index.md":
                    continue
                try:
                    note = Note.from_file(path)
                except Exception:
                    continue
                note_id = str(note.frontmatter.get("id") or path.stem)
                events.append(
                    WireEvent(
                        timestamp=path.stat().st_mtime,
                        source=note_id,
                        target="",
                        predicate="note_modified",
                        event_type="modified",
                    )
                )
        events.sort(key=lambda item: item.timestamp)
        return events

    def load_session_frequency(self) -> list[SessionCount]:
        grouped: dict[str, dict[str, Any]] = {}
        agents_root = self.atlas_root / "agents"
        if not agents_root.exists():
            return []
        for path in agents_root.glob("*/sessions/*.md"):
            match = re.search(r"(\d{4}-\d{2}-\d{2}|\d{8})", path.name)
            if match is None:
                continue
            raw = match.group(1)
            day = (
                raw
                if "-" in raw
                else f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
            )
            agent = path.parents[1].name
            grouped.setdefault(day, {"count": 0, "agents": set()})
            grouped[day]["count"] += 1
            grouped[day]["agents"].add(agent)
        return [
            SessionCount(date=day, count=int(data["count"]), agents=sorted(data["agents"]))
            for day, data in sorted(grouped.items())
        ]

    def load_daily_note_data(self) -> list[DailyData]:
        daily_dir = self.atlas_root / "daily"
        if not daily_dir.exists():
            return []
        payload: list[DailyData] = []
        for path in sorted(daily_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            match = re.search(r"(\d{4}-\d{2}-\d{2})", path.stem)
            day = "" if match is None else match.group(1)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                continue
            try:
                note = Note.from_file(path)
            except Exception:
                continue
            body = note.body
            matches = list(CHECKBOX_RE.finditer(body))
            intentions_total = len(matches)
            intentions_met = sum(1 for match in matches if match.group("done").lower() == "x")
            lowered = body.lower()
            emotional_keywords = sorted(
                keyword for keyword in EMOTIONAL_KEYWORDS if keyword in lowered
            )
            payload.append(
                DailyData(
                    date=day,
                    word_count=len(body.split()),
                    intentions_met=intentions_met,
                    intentions_total=intentions_total,
                    emotional_keywords=emotional_keywords,
                )
            )
        return payload

    def load_access_patterns(self) -> list[AccessEvent]:
        if not self.db_path.exists():
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    note_id,
                    access_type,
                    date(accessed_at, 'unixepoch') AS access_day,
                    COUNT(*) AS access_count
                FROM access_log
                GROUP BY note_id, access_type, access_day
                ORDER BY access_day ASC, note_id ASC
                """
            ).fetchall()
        events: list[AccessEvent] = []
        for row in rows:
            day = row["access_day"]
            if day is None:
                continue
            events.append(
                AccessEvent(
                    timestamp=_day_timestamp(str(day)),
                    note_id=str(row["note_id"]),
                    access_count=int(row["access_count"]),
                    access_type=str(row["access_type"]),
                )
            )
        return events

    def load_operating_truth_activity(self) -> list[tuple[float, str]]:
        if not self.db_path.exists():
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at, updated_at
                FROM operating_truth
                """
            ).fetchall()
        events: list[tuple[float, str]] = []
        for row in rows:
            created_at = row["created_at"]
            updated_at = row["updated_at"]
            if created_at is not None:
                events.append((float(created_at), "created"))
            if updated_at is not None and (
                created_at is None or float(updated_at) != float(created_at)
            ):
                events.append((float(updated_at), "updated"))
        events.sort(key=lambda item: item[0])
        return events

    def _bucket_events(
        self,
        events: list[tuple[float, float]],
        *,
        bucket_hours: int,
    ) -> list[tuple[float, float]]:
        buckets: dict[float, float] = defaultdict(float)
        for timestamp, value in events:
            buckets[_bucket_start(timestamp, bucket_hours)] += float(value)
        return sorted(buckets.items())

    def derive_signal(
        self,
        name: str,
        *,
        bucket_hours: int = 24,
    ) -> list[tuple[float, float]]:
        snapshots = self._load_state_snapshots()
        transitions = self.load_state_transitions()
        wire_events = self.load_wire_activity()
        sessions = self.load_session_frequency()
        daily = self.load_daily_note_data()
        accesses = self.load_access_patterns()
        operating_truth_events = self.load_operating_truth_activity()

        if name == "state_transition":
            return self._bucket_events(
                [(item.timestamp, 1.0) for item in transitions],
                bucket_hours=bucket_hours,
            )
        if name == "wire_activity":
            return self._bucket_events(
                [(item.timestamp, 1.0) for item in wire_events],
                bucket_hours=bucket_hours,
            )
        if name == "high_valence_wire":
            return self._bucket_events(
                [
                    (item.timestamp, 1.0)
                    for item in wire_events
                    if str(item.emotional_valence or "").lower() in {"positive", "mixed", "energizing"}
                ],
                bucket_hours=bucket_hours,
            )
        if name == "session_frequency":
            return self._bucket_events(
                [(_day_timestamp(item.date), float(item.count)) for item in sessions],
                bucket_hours=bucket_hours,
            )
        if name == "wire_creation":
            return self._bucket_events(
                [(item.timestamp, 1.0) for item in wire_events if item.event_type == "created"],
                bucket_hours=bucket_hours,
            )
        if name == "intention_misses":
            return self._bucket_events(
                [
                    (_day_timestamp(item.date), float(max(item.intentions_total - item.intentions_met, 0)))
                    for item in daily
                ],
                bucket_hours=bucket_hours,
            )
        if name == "state_drop":
            values = []
            for item in transitions:
                dropped = 1.0 if _state_capacity(item.to_state) < _state_capacity(item.from_state) else 0.0
                values.append((item.timestamp, dropped))
            return self._bucket_events(values, bucket_hours=bucket_hours)
        if name == "state_stability":
            values: list[tuple[float, float]] = []
            previous: StateSnapshot | None = None
            for snapshot in snapshots:
                if previous is not None:
                    stable = 1.0 if _state_key(snapshot.state) == _state_key(previous.state) else 0.0
                    values.append((snapshot.timestamp, stable))
                previous = snapshot
            return self._bucket_events(values, bucket_hours=bucket_hours)
        if name == "daily_word_count":
            return self._bucket_events(
                [(_day_timestamp(item.date), float(item.word_count)) for item in daily],
                bucket_hours=bucket_hours,
            )
        if name == "access_hot_notes":
            by_day: dict[float, list[AccessEvent]] = defaultdict(list)
            for item in accesses:
                by_day[_bucket_start(item.timestamp, bucket_hours)].append(item)
            values: list[tuple[float, float]] = []
            ordered_days = sorted(by_day.keys())
            for index, day in enumerate(ordered_days):
                prior_days = ordered_days[max(0, index - 7) : index]
                prior_totals: dict[str, int] = defaultdict(int)
                for prior in prior_days:
                    for event in by_day[prior]:
                        prior_totals[event.note_id] += event.access_count
                hot_notes = {note_id for note_id, count in prior_totals.items() if count > 5}
                values.append(
                    (
                        day,
                        float(
                            sum(
                                event.access_count
                                for event in by_day[day]
                                if not hot_notes or event.note_id in hot_notes
                            )
                        ),
                    )
                )
            return values
        if name == "operating_truth_churn":
            return self._bucket_events(
                [(timestamp, 1.0) for timestamp, _event_type in operating_truth_events],
                bucket_hours=bucket_hours,
            )
        raise ValueError(f"unsupported temporal signal: {name}")

    def _align_signals(
        self,
        signal_a: list[tuple[float, float]],
        signal_b: list[tuple[float, float]],
        *,
        lead_hours: int,
        bucket_hours: int,
    ) -> list[tuple[float, float, float]]:
        shift = float(lead_hours) * 3600.0
        bucketed_a = {_bucket_start(ts, bucket_hours): value for ts, value in signal_a}
        bucketed_b = {
            _bucket_start(ts - shift, bucket_hours): value
            for ts, value in signal_b
        }
        buckets = sorted(set(bucketed_a) | set(bucketed_b))
        return [
            (bucket, float(bucketed_a.get(bucket, 0.0)), float(bucketed_b.get(bucket, 0.0)))
            for bucket in buckets
        ]

    def _permutation_p_value(
        self,
        xs: list[float],
        ys: list[float],
        actual_r: float,
        *,
        permutation_count: int,
    ) -> float:
        if len(xs) < 3 or len(ys) < 3:
            return 1.0
        exceed = 0
        shuffled = list(ys)
        for _ in range(max(1, permutation_count)):
            self._rng.shuffle(shuffled)
            permuted_r = pearson_correlation(xs, shuffled)
            if abs(permuted_r) >= abs(actual_r):
                exceed += 1
        return (exceed + 1) / (max(1, permutation_count) + 1)

    def correlate(
        self,
        signal_a_name: str,
        signal_b_name: str,
        *,
        lead_hours: int = 48,
        bucket_hours: int = 24,
        min_n: int = 3,
        permutation_count: int | None = None,
    ) -> CorrelationResult:
        signal_a = self.derive_signal(signal_a_name, bucket_hours=bucket_hours)
        signal_b = self.derive_signal(signal_b_name, bucket_hours=bucket_hours)
        aligned = self._align_signals(
            signal_a,
            signal_b,
            lead_hours=lead_hours,
            bucket_hours=bucket_hours,
        )
        xs = [item[1] for item in aligned]
        ys = [item[2] for item in aligned]
        n_buckets = len(aligned)
        if n_buckets < min_n:
            return CorrelationResult(
                signal_a=signal_a_name,
                signal_b=signal_b_name,
                lead_hours=lead_hours,
                correlation=0.0,
                n_buckets=n_buckets,
                p_value=1.0,
                significant=False,
                description=f"insufficient data for {signal_a_name} vs {signal_b_name}",
                buckets=aligned,
            )
        actual_r = pearson_correlation(xs, ys)
        permutation_total = (
            int(self.config.get("permutation_count", 1000))
            if permutation_count is None
            else int(permutation_count)
        )
        p_value = self._permutation_p_value(
            xs,
            ys,
            actual_r,
            permutation_count=permutation_total,
        )
        threshold = float(self.config.get("significance_threshold", 0.05) or 0.05)
        return CorrelationResult(
            signal_a=signal_a_name,
            signal_b=signal_b_name,
            lead_hours=lead_hours,
            correlation=actual_r,
            n_buckets=n_buckets,
            p_value=p_value,
            significant=p_value < threshold,
            description=f"{signal_a_name} vs {signal_b_name}",
            buckets=aligned,
        )

    def _counter_evidence(self, result: CorrelationResult) -> list[str]:
        if not result.buckets:
            return []
        xs = [item[1] for item in result.buckets]
        ys = [item[2] for item in result.buckets]
        if not xs or not ys:
            return []
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        counter: list[str] = []
        for bucket, x_value, y_value in result.buckets:
            day = datetime.fromtimestamp(bucket).date().isoformat()
            if x_value > mean_x and y_value <= mean_y:
                counter.append(
                    f"{day}: {result.signal_a} was elevated without matching {result.signal_b}"
                )
            elif y_value > mean_y and x_value <= mean_x:
                counter.append(
                    f"{day}: {result.signal_b} spiked without recent {result.signal_a}"
                )
            if len(counter) >= 3:
                break
        return counter

    def _pair_allowed(self, signal_domain: str, signal_a: str, signal_b: str) -> bool:
        if signal_domain == "all":
            return True
        mapping = _signal_domains()
        allowed = mapping.get(signal_domain, set())
        return signal_a in allowed or signal_b in allowed

    def _cache_patterns(self, results: list[CorrelationResult]) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM pattern_cache")
            connection.executemany(
                """
                INSERT INTO pattern_cache
                (id, signal_a, signal_b, lead_hours, correlation, p_value, significant, n_buckets, computed_at, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"{item.signal_a}:{item.signal_b}:{item.lead_hours}",
                        item.signal_a,
                        item.signal_b,
                        item.lead_hours,
                        item.correlation,
                        item.p_value,
                        1 if item.significant else 0,
                        item.n_buckets,
                        time.time(),
                        item.description,
                    )
                    for item in results
                ],
            )
            connection.commit()

    def detect_all_patterns(
        self,
        *,
        lead_hours: int | None = None,
        min_n: int | None = None,
        signal_domain: str = "all",
        permutation_count: int | None = None,
    ) -> list[PatternReport]:
        if not bool(self.config.get("enabled", True)):
            self._cache_patterns([])
            return []
        resolved_lead = (
            int(self.config.get("default_lead_hours", 48))
            if lead_hours is None
            else int(lead_hours)
        )
        resolved_min_n = (
            int(self.config.get("min_data_points", 3))
            if min_n is None
            else int(min_n)
        )
        bucket_hours = int(self.config.get("bucket_hours", 24) or 24)
        significant_results: list[tuple[CorrelationResult, str]] = []
        cached_results: list[CorrelationResult] = []
        for signal_a, signal_b, pair_lead, description_template in SIGNAL_PAIRS:
            if not self._pair_allowed(signal_domain, signal_a, signal_b):
                continue
            effective_lead = resolved_lead if lead_hours is not None else pair_lead
            result = self.correlate(
                signal_a,
                signal_b,
                lead_hours=effective_lead,
                bucket_hours=bucket_hours,
                min_n=resolved_min_n,
                permutation_count=permutation_count,
            )
            result.description = description_template.format(lead=effective_lead)
            cached_results.append(result)
            if result.significant:
                significant_results.append((result, description_template))
        self._cache_patterns(cached_results)
        significant_results.sort(
            key=lambda item: abs(item[0].correlation),
            reverse=True,
        )
        reports: list[PatternReport] = []
        for result, description_template in significant_results:
            summary = (
                f"{description_template.format(lead=result.lead_hours)} "
                f"(r={result.correlation:.2f}, p={result.p_value:.3f}, N={result.n_buckets})"
            )
            reports.append(
                PatternReport(
                    title=result.description,
                    correlations=[result],
                    summary=summary,
                    counter_evidence=self._counter_evidence(result),
                    recommendation="This is a pattern report, not an intervention.",
                )
            )
        return reports

    def format_report(self, patterns: list[PatternReport]) -> str:
        if not patterns:
            return "temporal patterns\n  no significant correlations detected\n"
        lines = ["temporal patterns", ""]
        for pattern in patterns:
            lines.append(f"pattern report: {pattern.title.lower()}")
            lines.append("")
            lines.append(f"  {pattern.summary}")
            for correlation in pattern.correlations:
                lines.append(
                    f"  correlation: {correlation.correlation:.2f}  |  p={correlation.p_value:.3f}  |  buckets={correlation.n_buckets}"
                )
            if pattern.counter_evidence:
                lines.append("  counter-evidence:")
                for item in pattern.counter_evidence[:3]:
                    lines.append(f"    - {item}")
            lines.append(f"  recommendation: {pattern.recommendation}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def write_report(self, patterns: list[PatternReport], output_dir: Path | str) -> Path:
        output_dir = Path(output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        day = datetime.now().date().isoformat()
        path = output_dir / f"{day}.md"
        body = self.format_report(patterns)
        note = Note(
            path=path,
            frontmatter={
                "id": f"temporal-patterns-{day}",
                "title": f"Temporal Pattern Report {day}",
                "type": "temporal-pattern-report",
                "created": day,
                "modified": day,
                "tags": ["temporal-patterns", "report"],
            },
            body=f"# Temporal Pattern Report\n\n{body}",
        )
        note.write(ensure_blocks=True)
        return path

    def quick_summary(self) -> dict[str, Any]:
        if not bool(self.config.get("enabled", True)):
            return {"enabled": False}
        state_transitions = self.load_state_transitions()
        wire_events = self.load_wire_activity()
        with self._connect() as connection:
            cached = connection.execute(
                """
                SELECT signal_a, signal_b, correlation, p_value, description
                FROM pattern_cache
                WHERE significant = 1
                ORDER BY ABS(correlation) DESC
                LIMIT 1
                """
            ).fetchone()
        state_days = {
            datetime.fromtimestamp(item.timestamp).date().isoformat()
            for item in state_transitions
        }
        wire_days = {
            datetime.fromtimestamp(item.timestamp).date().isoformat()
            for item in wire_events
        }
        return {
            "enabled": True,
            "state_transitions": len(state_transitions),
            "wire_events": len(wire_events),
            "data_days": max(1, len(state_days | wire_days)),
            "significant_correlations": 0 if cached is None else 1,
            "strongest": None
            if cached is None
            else {
                "signal_a": str(cached["signal_a"]),
                "signal_b": str(cached["signal_b"]),
                "correlation": float(cached["correlation"]),
                "p_value": float(cached["p_value"]),
                "description": str(cached["description"]),
            },
            "note": "run cart temporal-patterns for full correlation report",
        }
