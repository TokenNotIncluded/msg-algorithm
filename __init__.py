"""Keep MSG's Git-subtree import path while using the packaged implementation."""

from .src.msg_algorithm import ALGORITHM_VERSION, Candidate, Recommendation, rank

__all__ = ["ALGORITHM_VERSION", "Candidate", "Recommendation", "rank"]
