"""v1 detection engine — layer 1 (context.md §4.1, §6): deterministic checksum/format
identifiers. Text-in, spans-out. Must never import corpus/ or eval/.
"""
from .identifiers import Candidate, detect

__all__ = ["Candidate", "detect"]
