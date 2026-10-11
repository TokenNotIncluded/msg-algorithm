# Performance checks

```sh
uv run --locked python benchmarks/compare.py --number 100 --repeat 5
```

Measured on Python 3.13.5, Linux-6.18.44-x86_64-with-glibc2.41.
Fixed seed 20261012; median of 5 batches of 100 calls. Times are microseconds.
Inputs are synthetic and pre-authorized. IDs, raw scores and reasons must match
the unmodified 0.1.0 ranker in `baseline.py` before any timing is reported.
Candidate construction is outside rank-only timings, but included in the end-to-end column.

| Posts / authors / results | Old rank µs | New rank µs | Rank speedup | Old construct + rank µs | New construct + rank µs |
| --- | ---: | ---: | ---: | ---: | ---: |
| 16 / 8 / 5 | 54.02 | 54.17 | 1.00× | 54.75 | 95.61 |
| 256 / 1 / 20 | 1483.17 | 1241.08 | 1.20× | 2961.47 | 1545.33 |
| 256 / 16 / 20 | 1441.42 | 632.03 | 2.28× | 1545.50 | 1129.15 |
| 256 / 64 / 20 | 1534.38 | 669.01 | 2.29× | 1635.95 | 1153.95 |
| 256 / 256 / 20 | 1482.40 | 659.05 | 2.25× | 1570.41 | 1142.48 |
| 256 / 64 / 100 | 5349.33 | 821.74 | 6.51× | 5293.54 | 1282.67 |

Tradeoffs: input validation and author queues cost work and memory. In the small
16-post case, construct + rank is slower. The 256-author rank-only sample has
42,788 bytes of traced peak Python allocations in the baseline versus 86,102
bytes in the new implementation. These are per-call allocations, not process RSS.
This is not a memory-reduction claim or a promise of speedups on all workloads.

All authors concentrated in one bucket still have an O(NK) worst case.
Shared-runner timings are noisy; rerun on the deployment hardware before using
them for capacity planning. This measures execution cost, not recommendation relevance.
