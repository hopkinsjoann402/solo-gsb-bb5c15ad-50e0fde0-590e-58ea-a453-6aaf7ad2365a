"""Tests for the pure grid core and SQLite persistence (stdlib only).

Run with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from fractions import Fraction

from app import db
from app.grid import build_measure, parse_fraction


def voice(name, *pairs):
    return {
        "name": name,
        "events": [
            {"kind": kind, "duration": duration} for kind, duration in pairs
        ],
    }


class ParseFractionTests(unittest.TestCase):
    def test_valid_forms(self):
        self.assertEqual(parse_fraction("1"), Fraction(1))
        self.assertEqual(parse_fraction("3/8"), Fraction(3, 8))
        self.assertEqual(parse_fraction(" 2/4 "), Fraction(1, 2))
        self.assertEqual(parse_fraction("17/6"), Fraction(17, 6))

    def test_rejects_bad_strings(self):
        for bad in ["", "abc", "1.5", "-1/4", "1/0", "0", "0/3", "1 /4", "1//4"]:
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    parse_fraction(bad)


class GridTests(unittest.TestCase):
    """Two voices over one whole-note target with different subdivisions."""

    def setUp(self):
        # Voice A: half-note note, half-note rest.
        # Voice B: four quarter notes.
        self.voices = [
            voice("A", ("note", "1/2"), ("rest", "1/2")),
            voice(
                "B",
                ("note", "1/4"),
                ("note", "1/4"),
                ("note", "1/4"),
                ("note", "1/4"),
            ),
        ]
        self.result = build_measure("1", self.voices)

    def test_measure_is_accepted(self):
        self.assertEqual(self.result["mismatches"], [])
        self.assertIsNotNone(self.result["measure"])

    def test_union_boundaries_split_segments(self):
        segments = self.result["measure"]["segments"]
        starts = [seg["start"] for seg in segments]
        self.assertEqual(starts, ["0", "1/4", "1/2", "3/4"])
        self.assertEqual(segments[-1]["end"], "1")

    def test_rest_is_null_and_notes_keep_event_ids(self):
        segments = self.result["measure"]["segments"]
        expected = [
            ("A#1", "B#1"),  # 0   - 1/4: A sounding, B event 1
            ("A#1", "B#2"),  # 1/4 - 1/2: A still sounding (boundary safe)
            (None, "B#3"),   # 1/2 - 3/4: A resting -> null
            (None, "B#4"),   # 3/4 - 1
        ]
        actual = [
            (seg["voices"]["A"], seg["voices"]["B"]) for seg in segments
        ]
        self.assertEqual(actual, expected)

    def test_segments_tile_without_gaps_or_overlaps(self):
        segments = self.result["measure"]["segments"]
        # Adjacent segments share exactly one boundary point.
        for left, right in zip(segments, segments[1:]):
            self.assertEqual(Fraction(left["end"]), Fraction(right["start"]))
        total = sum(
            (Fraction(s["end"]) - Fraction(s["start"]) for s in segments),
            Fraction(0),
        )
        self.assertEqual(total, Fraction(1))

    def test_each_note_event_appears_for_exactly_its_duration(self):
        measure = self.result["measure"]
        coverage: dict[str, Fraction] = {}
        for segment in measure["segments"]:
            length = Fraction(segment["end"]) - Fraction(segment["start"])
            for event_id in segment["voices"].values():
                if event_id is not None:
                    coverage[event_id] = coverage.get(event_id, Fraction(0)) + length
        self.assertEqual(
            coverage,
            {
                "A#1": Fraction(1, 2),
                "B#1": Fraction(1, 4),
                "B#2": Fraction(1, 4),
                "B#3": Fraction(1, 4),
                "B#4": Fraction(1, 4),
            },
        )

    def test_simultaneous_attack_at_boundary_is_not_dropped_or_duplicated(self):
        # Both voices switch events at exactly 1/2: one ends, one starts.
        voices = [
            voice("X", ("note", "1/2"), ("note", "1/2")),
            voice("Y", ("rest", "1/2"), ("note", "1/2")),
        ]
        result = build_measure("1", voices)["measure"]
        middle = next(s for s in result["segments"] if s["start"] == "1/2")
        # The new events own the boundary point [1/2, ...): X#2 and Y#2.
        self.assertEqual(middle["voices"], {"X": "X#2", "Y": "Y#2"})
        before = next(s for s in result["segments"] if s["end"] == "1/2")
        self.assertEqual(before["voices"], {"X": "X#1", "Y": None})


class MismatchTests(unittest.TestCase):
    def test_short_and_long_voices_are_reported_and_exact(self):
        voices = [
            voice("short", ("note", "3/8"), ("rest", "1/8")),  # 1/2
            voice("long", ("note", "1"), ("note", "1/3")),     # 4/3
        ]
        result = build_measure("1", voices)
        self.assertIsNone(result["measure"])
        by_voice = {m["voice"]: m for m in result["mismatches"]}
        self.assertEqual(by_voice["short"]["total"], "1/2")
        self.assertEqual(by_voice["short"]["difference"], "-1/2")
        self.assertEqual(by_voice["long"]["total"], "4/3")
        self.assertEqual(by_voice["long"]["difference"], "1/3")
        self.assertEqual(by_voice["long"]["target"], "1")

    def test_float_near_miss_is_a_real_mismatch(self):
        # 1/3 + 1/3 + 1/3 is exactly 1 with Fractions; tweak one to 0.34-style
        # rational to confirm no float tolerance hides the difference.
        voices = [
            voice("V1", ("note", "1/3"), ("note", "1/3"), ("note", "1/3")),
            voice("V2", ("note", "17/50"), ("note", "33/100")),  # 0.67
        ]
        result = build_measure("1", voices)
        names = {m["voice"] for m in result["mismatches"]}
        self.assertEqual(names, {"V2"})
        self.assertEqual(
            next(iter(result["mismatches"]))["difference"], "-33/100"
        )

    def test_malformed_duration_raises(self):
        with self.assertRaises(ValueError):
            build_measure("1", [voice("A", ("note", "1/2"), ("rest", "x"))]
                          + [voice("B", ("note", "1"))])


class DbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.original_path = db.DB_PATH
        db.DB_PATH = self.tmp.name
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original_path
        os.unlink(self.tmp.name)

    def test_insert_and_roundtrip(self):
        measure = build_measure(
            "1", [voice("A", ("note", "1")), voice("B", ("rest", "1/2"),
                                                  ("note", "1/2"))]
        )["measure"]
        measure_id = db.insert_measure(measure)
        fetched = db.get_measure(measure_id)
        self.assertEqual(fetched["target_duration"], "1")
        self.assertEqual(fetched["voices"], measure["voices"])
        self.assertEqual(fetched["segments"], measure["segments"])
        self.assertIsNone(db.get_measure(measure_id + 999))

    def test_init_is_idempotent(self):
        db.init_db()
        db.init_db()


if __name__ == "__main__":
    unittest.main()
