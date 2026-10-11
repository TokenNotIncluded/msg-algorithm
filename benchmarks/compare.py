"""Compare 0.2.0 with the frozen 0.1.0 implementation on identical inputs."""

import argparse
import json
import platform
import random
import statistics
import timeit
import tracemalloc
from datetime import UTC, datetime, timedelta

import baseline
from msg_algorithm import Candidate, rank


def signature(items):
    return [(item.candidate.id, item.score, item.reasons) for item in items]


def measure(function, number, repeats):
    elapsed = timeit.repeat(function, number=number, repeat=repeats)
    tracemalloc.start()
    function()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "median_us": round(statistics.median(elapsed) / number * 1_000_000, 2),
        "peak_bytes": peak,
    }


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--number", type=positive, default=100)
    parser.add_argument("--repeat", type=positive, default=5)
    args = parser.parse_args()
    rng = random.Random(20261012)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "number": args.number, "repeat": args.repeat, "seed": 20261012, "cases": []}
    for size, authors, limit in ((16, 8, 5), (256, 1, 20), (256, 16, 20),
                                 (256, 64, 20), (256, 256, 20), (256, 64, 100)):
        rows = [
            (f"{i:04}", str(i % authors), now - timedelta(seconds=rng.randrange(30 * 86400)),
             tuple(rng.sample(["python", "rust", "go", "misc"], 2)))
            for i in range(size)
        ]
        options = {"now": now, "limit": limit, "following": {str(i) for i in range(authors // 2)},
                   "interests": {"python", "rust"}}
        old_pool = [baseline.Candidate(*row) for row in rows]
        new_pool = [Candidate(*row) for row in rows]
        assert signature(baseline.rank(old_pool, **options)) == signature(rank(new_pool, **options))
        old = measure(lambda: baseline.rank(old_pool, **options), args.number, args.repeat)
        new = measure(lambda: rank(new_pool, **options), args.number, args.repeat)
        old_total = measure(lambda: baseline.rank([baseline.Candidate(*r) for r in rows], **options),
                            args.number, args.repeat)
        new_total = measure(lambda: rank([Candidate(*r) for r in rows], **options),
                            args.number, args.repeat)
        report["cases"].append({
            "candidates": size, "authors": authors, "limit": limit,
            "baseline_rank": old, "new_rank": new,
            "baseline_construct_and_rank": old_total, "new_construct_and_rank": new_total,
            "rank_speedup": round(old["median_us"] / new["median_us"], 2),
            "construct_and_rank_speedup": round(old_total["median_us"] / new_total["median_us"], 2),
        })
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
