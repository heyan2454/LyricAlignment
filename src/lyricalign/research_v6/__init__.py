"""Research-v6 utilities for decoder, detector, window, and realign experiments.

This package is intentionally independent from the legacy demo controllers.  It
operates on standard alignment rows and experiment requests so that the same
analysis can be reused for cached baselines, local reruns, and future planners.
"""

from .decoders import DecoderConfig, decode_rows
from .detector import DetectorConfig, inspect_alignment

__all__ = ["DecoderConfig", "decode_rows", "DetectorConfig", "inspect_alignment"]
