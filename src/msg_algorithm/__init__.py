"""Small, transparent recommendations. No tracking, network or runtime dependencies."""

from .ranker import ALGORITHM_VERSION, Candidate, Recommendation, rank

__all__ = ["ALGORITHM_VERSION", "Candidate", "Recommendation", "rank"]
