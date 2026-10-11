"""Deterministic recommendations from explicit interests, follows and recency."""

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from heapq import heapify, heappop, heappush
from itertools import islice
from unicodedata import normalize

ALGORITHM_VERSION = "0.2.0"
MAX_CANDIDATES = 256
MAX_TAGS = 64
MAX_INTERESTS = 128
MAX_FOLLOWING = 4096
MAX_EXCLUDED_IDS = 4096
MAX_TEXT_LENGTH = 512
FOLLOW_WEIGHT = 3.0
INTEREST_WEIGHT = 2.0
HALF_LIFE_HOURS = 24.0

__all__ = [
    "ALGORITHM_VERSION", "MAX_CANDIDATES", "MAX_TAGS", "MAX_INTERESTS",
    "MAX_FOLLOWING", "MAX_EXCLUDED_IDS", "MAX_TEXT_LENGTH", "FOLLOW_WEIGHT",
    "INTEREST_WEIGHT", "HALF_LIFE_HOURS", "Candidate", "Recommendation", "rank",
]


def _bounded[T](values: Iterable[T], maximum: int, name: str) -> list[T]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be an iterable, not a string")
    try:
        items = list(islice(values, maximum + 1))
    except TypeError as error:
        raise ValueError(f"{name} must be an iterable") from error
    if len(items) > maximum:
        raise ValueError(f"too many {name}; maximum is {maximum}")
    return items


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH or not value.strip():
        raise ValueError(f"{name} must be non-blank text of at most {MAX_TEXT_LENGTH} characters")
    return value


def _strings(values: Iterable[str], maximum: int, name: str) -> tuple[str, ...]:
    return tuple(_text(value, name) for value in _bounded(values, maximum, name))


def _tag(value: str) -> str:
    return normalize("NFKC", value).strip().casefold()


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name} must be representable in UTC") from error


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    author: str
    created_at: datetime
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.id, "candidate ID")
        _text(self.author, "author")
        _utc(self.created_at, "candidate time")
        # Freeze caller-owned lists/generators without changing displayed tag text.
        object.__setattr__(self, "tags", _strings(self.tags, MAX_TAGS, "tags"))


@dataclass(frozen=True, slots=True)
class Recommendation:
    candidate: Candidate
    score: float
    reasons: tuple[str, ...]
    # Raw score remains compatible. This is the score used at selection time.
    selection_score: float | None = None


def _head(items: list[Recommendation], selected: int) -> tuple[float, str, str, int]:
    # Only this author's priorities change after one of their posts is selected.
    # Recompute the head with the actual divided float: sorting by raw score
    # alone can give the wrong ID tie-break when division rounds scores equal.
    index = 0 if len(items) == 1 else min(
        range(len(items)),
        key=lambda i: (-items[i].score / (1 + selected), items[i].candidate.id),
    )
    item = items[index]
    return -item.score / (1 + selected), item.candidate.id, item.candidate.author, index


def rank(
    candidates: Iterable[Candidate],
    *,
    now: datetime,
    following: Iterable[str] = (),
    interests: Iterable[str] = (),
    limit: int = 20,
    exclude_ids: Iterable[str] = (),
    max_per_author: int | None = None,
    max_age_hours: float | None = None,
) -> list[Recommendation]:
    """Rank already-visible public posts; the caller owns all access checks.

    Raw score = 3 * followed + 2 * matched-interest fraction + freshness.
    Freshness halves every 24 elapsed hours. Select by score / (1 + earlier
    posts from that author), then by ID. Optional filters are caller-supplied;
    no viewing history is recorded. Invalid input raises ValueError.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if max_per_author is not None and (
        type(max_per_author) is not int or not 1 <= max_per_author <= 100
    ):
        raise ValueError("max_per_author must be between 1 and 100")
    if max_age_hours is not None:
        if type(max_age_hours) not in (int, float):
            raise ValueError("max_age_hours must be finite and non-negative")
        try:
            valid_age = math.isfinite(max_age_hours) and max_age_hours >= 0
        except OverflowError:
            valid_age = False
        if not valid_age:
            raise ValueError("max_age_hours must be finite and non-negative")
    now = _utc(now, "now")
    pool = _bounded(candidates, MAX_CANDIDATES, "candidates")
    followed = frozenset(_strings(following, MAX_FOLLOWING, "following"))
    wanted = frozenset(map(_tag, _strings(interests, MAX_INTERESTS, "interests")))
    excluded = frozenset(_strings(exclude_ids, MAX_EXCLUDED_IDS, "exclude_ids"))
    groups: dict[str, list[Recommendation]] = defaultdict(list)
    ids: set[str] = set()
    for item in pool:
        if not isinstance(item, Candidate):
            raise ValueError("candidates must contain Candidate objects")
        if item.id in ids:
            raise ValueError("duplicate candidate ID")
        ids.add(item.id)
        age_hours = max(0.0, (now - _utc(item.created_at, "candidate time")).total_seconds() / 3600)
        if item.id in excluded or (max_age_hours is not None and age_hours > max_age_hours):
            continue
        score = math.exp2(-age_hours / HALF_LIFE_HOURS)
        reasons = ["recent"]
        if item.author in followed:
            score += FOLLOW_WEIGHT
            reasons.append("followed_author")
        matches = wanted.intersection(map(_tag, item.tags)) if wanted else set()
        if matches:
            score += INTEREST_WEIGHT * len(matches) / len(wanted)
            reasons.append("interest_match")
        groups[item.author].append(Recommendation(item, score, tuple(reasons)))

    heads = [_head(items, 0) for items in groups.values()]
    heapify(heads)
    counts: dict[str, int] = defaultdict(int)
    result: list[Recommendation] = []
    while heads and len(result) < limit:
        negative_score, _, author, index = heappop(heads)
        item = groups[author].pop(index)
        result.append(Recommendation(item.candidate, item.score, item.reasons, -negative_score))
        counts[author] += 1
        if groups[author] and (max_per_author is None or counts[author] < max_per_author):
            heappush(heads, _head(groups[author], counts[author]))
    return result
