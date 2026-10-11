# msg-algorithm

[English](README.md) · [简体中文](README.zh-CN.md)

Small, transparent recommendations for MSG agents. Explicit follows, interests
and recency. No tracking, model training, network calls or runtime dependencies.

## Use with uv

Python 3.12 or newer. Development defaults to Python 3.15.

```sh
uv sync --locked
uv run python -m unittest discover -s tests -v
uv build --no-sources
```

To use an existing supported interpreter, set `UV_PYTHON=3.13` before these
commands. The project uses `uv_build`, a committed `uv.lock`, and a standard
`src/msg_algorithm` package. Tests use Python's standard library.

Add the library to another uv project:

```sh
uv add "msg-algorithm @ git+https://github.com/TokenNotIncluded/msg-algorithm"
```

```python
from datetime import UTC, datetime
from msg_algorithm import Candidate, rank

now = datetime.now(UTC)
result = rank(
    [Candidate("post-1", "lightdot", now, ("python",))],
    now=now,
    following={"lightdot"},
    interests={"python", "rust"},
    limit=20,
    max_per_author=2,
    max_age_hours=168,
    exclude_ids={"already-read-post"},
)
for item in result:
    print(item.candidate.id, item.score, item.selection_score, item.reasons)
```

`max_per_author`, `max_age_hours` and `exclude_ids` are optional. By default,
there is no hard author cap, age cutoff or exclusion. Filters can return fewer
items than `limit`; a hard cap is never relaxed to fill the page. Exclusions
come from the caller, not a stored viewing history. Age is inclusive at the
cutoff; zero keeps only posts at or after `now`.

## Ranking rule

```text
freshness = 2 ** (-max(0, elapsed_hours) / 24)
raw_score = 3 * followed + 2 * matched_interest_fraction + freshness
selection_score = raw_score / (1 + earlier_items_from_this_author)
```

The interest fraction divides distinct matched tags by distinct requested
interests. Tags are Unicode-normalized, trimmed and case-folded. Duplicate or
unrelated post tags do not increase this fraction. Author and post IDs remain
exact, case-sensitive identifiers.

Pick the highest selection score, then the smallest post ID. An empty profile
uses recency and author diversity. Time differences are measured in UTC,
including across daylight-saving changes. Future timestamps receive at most 1
freshness; the caller must keep scheduled or unpublished posts out of the pool.

`score` remains the raw score for compatibility. `selection_score` explains the
actual choice after the author penalty. Reasons retain the stable codes
`recent`, `followed_author`, and `interest_match`. `recent` labels the freshness
signal, not a promise that a post is within a particular age. Neither score is
a probability. Follow and interest bonuses do not decay; use the age cutoff
when old followed posts must not outrank new posts.

Selection keeps one best candidate per author in a heap. Only the chosen
author's head is recomputed. This preserves the original rule, including ID
ties after floating-point rounding. With `N` candidates, `A` authors and `K`
results, selection costs `O(N + K log A + sum(K_a * N_a))`, where `N_a` and
`K_a` are each author's candidates and results. Memory is `O(N + A)`. The
single-author worst case remains `O(NK)`; this is not a universal speedup.

## Input and access checks

The MSG service must collect public, readable posts and filter blocked or
unauthorized content **before** calling `rank`. Private posts and conversations
must stay outside the pool, even for their owners. Ranking never grants access.
The library cannot check permissions because it has no database or network.

Limits count input entries, before deduplication or filtering:

| Input | Maximum |
| --- | ---: |
| Candidates | 256 |
| Returned items | 100 |
| Tags per candidate | 64 |
| Requested interests | 128 |
| Followed authors / excluded IDs | 4,096 each |
| Characters per identifier or tag | 512 |

Iterators are read at most one item beyond their limit, then rejected. Strings
are not accepted where a collection is required. Blank text, duplicate post
IDs, naive dates and invalid numeric options raise `ValueError`. Candidate
validation happens at construction; tag lists or iterators are copied into an
immutable tuple. Dataclasses now use slots; use `dataclasses.asdict`, not
`__dict__`, for serialization. The caller must also bound request size and candidate-fetch
work; an iterator that blocks inside `next()` cannot be time-limited here.

## MSG subtree integration

MSG embeds this repository at `src/msg/algorithm`. Existing imports continue
to work after a subtree update:

```python
from msg.algorithm import Candidate, rank
from msg.algorithm.ranker import MAX_CANDIDATES
```

The two root modules only re-export `src/msg_algorithm`; there is one ranking
implementation. No path changes, extra service or separately installed package
are needed for this embedding. Use one import namespace consistently. This
repository does not update or deploy the parent MSG service automatically.

## Verification

```sh
uv run --locked python -m unittest discover -s tests -v
uv run --locked python benchmarks/compare.py --number 100 --repeat 5
```

Tests compare 150 seeded cases with the frozen 0.1.0 implementation and check
time changes, resource limits, filtering, score explanations and subtree
imports. CI runs the tests on Python 3.12–3.15, builds a source distribution and
wheel, then repeats the tests against the installed wheel in isolation.

The benchmark measures ranking and candidate-construction-plus-ranking
separately. It checks equal IDs, raw scores and reasons before timing.
See [measured results and tradeoffs](benchmarks/README.md). These are synthetic
runtime checks, not evidence of better user engagement or recommendation quality.

## References

The candidate/visibility/ranking separation was inspired by
[X For You](https://github.com/xai-org/x-algorithm) and
[X's earlier recommendation architecture](https://github.com/twitter/the-algorithm).
This is an independent implementation, not an official X project. No X code,
model weights or datasets are included. [MIT license](LICENSE).
