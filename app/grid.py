"""Pure (stdlib-only) ensemble beat grid logic.

Durations are positive rational strings such as ``"1"``, ``"1/4"`` or
``"3/8"``.  All accumulation happens with :class:`fractions.Fraction`, so
there is no floating-point error and equality against the target duration is
exact.

Segment semantics: event intervals and grid segments are both half-open
``[start, end)``.  Grid segments are built from the sorted union of every
event boundary, therefore an event ending exactly when another starts is
neither dropped nor double-counted on the shared boundary.
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any

# Accepts "n" or "n/d" with non-negative decimal numerator/denominator.
# Positivity and non-zero denominator are checked afterwards.
_RATIONAL_RE = re.compile(r"^\d+(?:/\d+)?$")


def parse_fraction(value: str) -> Fraction:
    """Parse a positive rational string into an exact :class:`Fraction`.

    Raises ``ValueError`` for anything that is not a strictly positive
    rational written as ``"n"`` or ``"n/d"``.
    """
    if not isinstance(value, str):
        raise ValueError(f"duration must be a rational string, got {type(value).__name__}")
    text = value.strip()
    if not _RATIONAL_RE.match(text):
        raise ValueError(
            f"invalid rational duration {value!r}: expected a positive string "
            "such as '1' or '1/4'"
        )
    numerator, _, denominator = text.partition("/")
    if denominator and int(denominator) == 0:
        raise ValueError(f"invalid rational duration {value!r}: denominator is zero")
    result = Fraction(int(numerator), int(denominator) if denominator else 1)
    if result <= 0:
        raise ValueError(f"invalid rational duration {value!r}: duration must be positive")
    return result


def _event_id(voice_name: str, index: int) -> str:
    """Stable, voice-qualified event id, e.g. ``soprano#3``."""
    return f"{voice_name}#{index}"


def build_measure(
    target_duration: str, voices: list[dict[str, Any]]
) -> dict[str, Any]:
    """Validate durations and build the beat grid for one measure.

    ``voices`` is a list of ``{"name": str, "events": [{"kind": "note"|"rest",
    "duration": "p/q"}, ...]}`` dicts (already shape-validated by the API
    layer).

    Returns::

        {"mismatches": [], "measure": {...}}      # when every voice matches
        {"mismatches": [...], "measure": None}    # otherwise

    ``difference`` is ``voice_total - target`` and is therefore negative when
    the voice is short.  Mismatching measures are returned to the caller and
    must not be persisted.
    """
    target = parse_fraction(target_duration)

    # Parse every duration up front so a bad string fails the whole request
    # before any totals/grid are computed.
    parsed_voices: list[tuple[str, list[tuple[str, Fraction]]]] = []
    for voice in voices:
        events = [
            (event["kind"], parse_fraction(event["duration"]))
            for event in voice["events"]
        ]
        parsed_voices.append((voice["name"], events))

    # Exact fraction accumulation per voice.
    mismatches: list[dict[str, str]] = []
    for name, events in parsed_voices:
        total = sum((duration for _, duration in events), Fraction(0))
        if total != target:
            mismatches.append(
                {
                    "voice": name,
                    "target": str(target),
                    "total": str(total),
                    "difference": str(total - target),
                }
            )

    if mismatches:
        return {"mismatches": mismatches, "measure": None}

    # Build per-voice timelines with absolute half-open [start, end) spans.
    boundaries: set[Fraction] = {Fraction(0), target}
    timelines: list[tuple[str, list[dict[str, Any]]]] = []
    enriched_voices: list[dict[str, Any]] = []

    for name, events in parsed_voices:
        cursor = Fraction(0)
        timeline: list[dict[str, Any]] = []
        enriched_events: list[dict[str, Any]] = []
        for index, (kind, duration) in enumerate(events, start=1):
            start, end = cursor, cursor + duration
            event_id = _event_id(name, index)
            timeline.append(
                {"id": event_id, "kind": kind, "start": start, "end": end}
            )
            enriched_events.append(
                {
                    "id": event_id,
                    "kind": kind,
                    "duration": str(duration),
                    "start": str(start),
                    "end": str(end),
                }
            )
            boundaries.add(start)
            boundaries.add(end)
            cursor = end
        timelines.append((name, timeline))
        enriched_voices.append({"name": name, "events": enriched_events})

    # Union of all start/end points -> adjacent half-open segments.
    points = sorted(boundaries)
    segments: list[dict[str, Any]] = []
    for start, end in zip(points, points[1:]):
        sounding: dict[str, str | None] = {}
        for name, timeline in timelines:
            event_id: str | None = None
            for event in timeline:
                if event["start"] <= start < event["end"]:
                    # Rests occupy the segment but are reported as null.
                    event_id = event["id"] if event["kind"] == "note" else None
                    break
            sounding[name] = event_id
        segments.append(
            {"start": str(start), "end": str(end), "voices": sounding}
        )

    measure = {
        "target_duration": str(target),
        "voices": enriched_voices,
        "segments": segments,
    }
    return {"mismatches": [], "measure": measure}
