"""Behavior, input bounds and integration checks for the public library."""

import importlib.util
import math
import pickle
import random
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from dataclasses import FrozenInstanceError, asdict
from datetime import UTC, datetime, timedelta, timezone
from itertools import repeat
from pathlib import Path
from zoneinfo import ZoneInfo

from msg_algorithm import ALGORITHM_VERSION, Candidate, Recommendation, rank
from msg_algorithm.ranker import (
    MAX_CANDIDATES,
    MAX_EXCLUDED_IDS,
    MAX_FOLLOWING,
    MAX_INTERESTS,
    MAX_TAGS,
    MAX_TEXT_LENGTH,
)

NOW = datetime(2026, 10, 1, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def signature(items):
    return [(item.candidate.id, item.score, item.reasons) for item in items]


class InputTests(unittest.TestCase):
    def test_candidate_generator_stops_at_limit_plus_one(self):
        consumed = []

        def candidates():
            for i in range(MAX_CANDIDATES + 2):
                consumed.append(i)
                yield Candidate(str(i), "author", NOW)

        with self.assertRaises(ValueError):
            rank(candidates(), now=NOW)
        self.assertEqual(len(consumed), MAX_CANDIDATES + 1)

    def test_infinite_profile_iterators_are_bounded(self):
        for argument, maximum in (
            ("following", MAX_FOLLOWING),
            ("interests", MAX_INTERESTS),
            ("exclude_ids", MAX_EXCLUDED_IDS),
        ):
            with self.subTest(argument=argument):
                consumed = 0

                def values():
                    nonlocal consumed
                    for value in repeat("value"):
                        consumed += 1
                        yield value

                with self.assertRaises(ValueError):
                    rank([], now=NOW, **{argument: values()})
                self.assertEqual(consumed, maximum + 1)

    def test_tag_iterator_is_bounded_and_input_is_frozen(self):
        with self.assertRaises(ValueError):
            Candidate("id", "author", NOW, repeat("python"))
        tags = ["Python"]
        candidate = Candidate("id", "author", NOW, tags)
        tags.append("rust")
        self.assertEqual(candidate.tags, ("Python",))
        with self.assertRaises(FrozenInstanceError):
            candidate.id = "changed"

    def test_maximum_sizes_are_accepted(self):
        tags = ("python",) * MAX_TAGS
        pool = [Candidate(str(i), "author", NOW, tags) for i in range(MAX_CANDIDATES)]
        result = rank(
            pool, now=NOW, following=repeat("author", MAX_FOLLOWING),
            interests=repeat("python", MAX_INTERESTS),
            exclude_ids=repeat("missing", MAX_EXCLUDED_IDS), limit=100,
        )
        self.assertEqual(len(result), 100)
        self.assertTrue(all(item.score == 6 for item in result))

    def test_strings_are_not_treated_as_profiles_or_candidate_lists(self):
        for argument in ("following", "interests", "exclude_ids"):
            with self.subTest(argument=argument), self.assertRaises(ValueError):
                rank([], now=NOW, **{argument: "python"})
        for value in ("id", b"id", None, [object()]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                rank(value, now=NOW)

    def test_bad_text_cannot_create_phantom_matches(self):
        for value in ("", "  ", "\u3000", None, 1, "x" * (MAX_TEXT_LENGTH + 1)):
            with self.subTest(value=value):
                for field in ("id", "author", "tags"):
                    kwargs = {"id": "id", "author": "author", "created_at": NOW}
                    kwargs[field] = (value,) if field == "tags" else value
                    with self.assertRaises(ValueError):
                        Candidate(**kwargs)
                for argument in ("following", "interests", "exclude_ids"):
                    with self.assertRaises(ValueError):
                        rank([], now=NOW, **{argument: [value]})
        with self.assertRaises(ValueError):
            Candidate("id", "author", NOW, "python")

    def test_invalid_numbers_fail_before_consuming_candidates(self):
        def unread():
            raise AssertionError("invalid options consumed candidates")
            yield

        for name, values in (
            ("limit", [0, 101, True, 1.5, "20"]),
            ("max_per_author", [0, 101, True, 1.5, "2"]),
            ("max_age_hours", [-1, True, "24", math.nan, math.inf, 10**1000]),
        ):
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    rank(unread(), now=NOW, **{name: value})

    def test_duplicate_ids_are_invalid_even_when_excluded(self):
        item = Candidate("id", "author", NOW)
        with self.assertRaises(ValueError):
            rank([item, item], now=NOW, exclude_ids=["id"])

    def test_naive_and_invalid_times_are_rejected(self):
        for value in (NOW.replace(tzinfo=None), None, "2026-10-01"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    rank([], now=value)
                with self.assertRaises(ValueError):
                    Candidate("id", "author", value)
        with self.assertRaises(ValueError):
            rank([], now=datetime.min.replace(tzinfo=timezone(timedelta(hours=1))))


class BehaviorTests(unittest.TestCase):
    def test_dst_uses_elapsed_time_not_wall_time(self):
        zone = ZoneInfo("America/New_York")
        for month, day, elapsed in ((3, 8, 23), (11, 1, 25)):
            with self.subTest(month=month):
                created = datetime(2026, month, day, tzinfo=zone)
                now = created + timedelta(days=1)
                item = rank([Candidate("id", "author", created)], now=now)[0]
                self.assertAlmostEqual(item.score, math.exp2(-elapsed / 24), places=14)
                utc_item = rank(
                    [Candidate("id", "author", created.astimezone(UTC))],
                    now=now.astimezone(UTC),
                )[0]
                self.assertEqual(item.score, utc_item.score)

    def test_future_timestamps_cannot_exceed_maximum_freshness(self):
        candidates = [Candidate(str(i), str(i), NOW + timedelta(days=i)) for i in (0, 1, 100)]
        self.assertTrue(all(item.score == 1 for item in rank(candidates, now=NOW)))

    def test_unicode_whitespace_and_duplicates_match_one_interest(self):
        item = Candidate("id", "author", NOW, (" Ｐｙｔｈｏｎ ", "PYTHON", "cafe\u0301"))
        result = rank([item], now=NOW, interests=["python", " Python ", "Café", "rust"])
        self.assertEqual(result[0].score, 1 + 2 * 2 / 3)
        self.assertEqual(result[0].candidate.tags, item.tags)

    def test_author_and_post_identifiers_are_not_normalized(self):
        item = Candidate("ID", "AUTHOR", NOW)
        result = rank([item], now=NOW, following=["author"], exclude_ids=["id"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].score, 1)

    def test_explicit_exclusion_has_no_stored_history(self):
        pool = [Candidate("a", "one", NOW), Candidate("b", "two", NOW)]
        self.assertEqual([r.candidate.id for r in rank(pool, now=NOW, exclude_ids=["a"])], ["b"])
        self.assertEqual([r.candidate.id for r in rank(pool, now=NOW)], ["a", "b"])

    def test_strict_author_cap_does_not_backfill_with_same_author(self):
        pool = [Candidate(str(i), "one", NOW) for i in range(5)]
        pool.append(Candidate("other", "two", NOW - timedelta(days=1)))
        result = rank(pool, now=NOW, following=["one"], max_per_author=2)
        self.assertEqual(Counter(r.candidate.author for r in result), {"one": 2, "two": 1})
        self.assertEqual(len(result), 3)

    def test_age_filter_includes_boundary_and_excludes_stale_follow(self):
        pool = [
            Candidate("stale", "followed", NOW - timedelta(hours=24, microseconds=1)),
            Candidate("boundary", "other", NOW - timedelta(hours=24)),
            Candidate("fresh", "other", NOW),
        ]
        result = rank(pool, now=NOW, following=["followed"], max_age_hours=24)
        self.assertEqual({r.candidate.id for r in result}, {"boundary", "fresh"})
        self.assertEqual([r.candidate.id for r in rank(pool, now=NOW, max_age_hours=0)], ["fresh"])

    def test_selection_score_explains_diversity_without_changing_raw_score(self):
        pool = [Candidate(str(i), "author", NOW) for i in range(3)]
        result = rank(pool, now=NOW)
        self.assertEqual([r.score for r in result], [1, 1, 1])
        self.assertEqual([r.selection_score for r in result], [1, 0.5, 1 / 3])
        self.assertIsNone(Recommendation(pool[0], 1, ("recent",)).selection_score)

    def test_float_rounding_ties_still_use_id_not_raw_score(self):
        pool = [
            Candidate("head", "author", NOW),
            Candidate("z", "author", NOW - timedelta(hours=24 * 1074)),
            Candidate("a", "author", NOW - timedelta(hours=24 * 1075)),
        ]
        result = rank(pool, now=NOW)
        self.assertEqual([r.candidate.id for r in result], ["head", "a", "z"])
        self.assertTrue(all(math.isfinite(r.score) for r in result))

    def test_empty_pool_and_fully_filtered_pool(self):
        self.assertEqual(rank([], now=NOW), [])
        self.assertEqual(rank([Candidate("id", "a", NOW)], now=NOW, exclude_ids=["id"]), [])

    def test_matches_original_scan_on_seeded_cases(self):
        # A frozen copy of 0.1.0 is independent of the new scoring/selection code.
        spec = importlib.util.spec_from_file_location("legacy_ranker", ROOT / "benchmarks/baseline.py")
        baseline = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = baseline
        spec.loader.exec_module(baseline)
        rng = random.Random(20261012)
        for case in range(150):
            size = rng.randrange(1, 257)
            authors = rng.randrange(1, size + 1)
            pool = [
                Candidate(
                    f"{i:04}", str(rng.randrange(authors)),
                    NOW - timedelta(seconds=rng.randrange(-3600, 90 * 86400)),
                    tuple(rng.sample(["python", "rust", "go", "misc"], rng.randrange(5))),
                )
                for i in range(size)
            ]
            options = {
                "now": NOW, "limit": rng.randrange(1, 101),
                "following": {str(i) for i in range(authors // 2)},
                "interests": rng.sample(["python", "rust", "go", "misc"], rng.randrange(5)),
            }
            with self.subTest(case=case):
                expected = signature(baseline.rank(pool, **options))
                result = rank(pool, **options)
                self.assertEqual(signature(result), expected)
                rng.shuffle(pool)
                self.assertEqual(rank(pool, **options), result)
                self.assertEqual(len({r.candidate.id for r in result}), len(result))
                adjusted = [r.selection_score for r in result]
                self.assertEqual(adjusted, sorted(adjusted, reverse=True))


class IntegrationTests(unittest.TestCase):
    def test_legacy_msg_subtree_import_in_separate_process(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "msg"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            # Copy just the production layout. No installed msg_algorithm is used.
            import shutil
            shutil.copytree(ROOT / "src", package / "algorithm/src")
            for name in ("__init__.py", "ranker.py"):
                shutil.copyfile(ROOT / name, package / "algorithm" / name)
            code = (
                "from datetime import UTC, datetime; "
                "from msg.algorithm import Candidate, rank; "
                "from msg.algorithm.ranker import Candidate as C, MAX_CANDIDATES; "
                "assert C is Candidate; assert MAX_CANDIDATES == 256; "
                "now = datetime.now(UTC); "
                "assert rank([C('id', 'author', now)], now=now)[0].score == 1"
            )
            subprocess.run([sys.executable, "-S", "-c", code], cwd=directory, check=True)

    def test_dataclass_serialization_and_pickle_remain_available(self):
        result = rank([Candidate("id", "author", NOW)], now=NOW)[0]
        self.assertEqual(pickle.loads(pickle.dumps(result)), result)
        self.assertEqual(asdict(result)["candidate"]["id"], "id")

    def test_package_and_algorithm_versions_agree(self):
        from importlib.metadata import version
        self.assertEqual(version("msg-algorithm"), ALGORITHM_VERSION)
