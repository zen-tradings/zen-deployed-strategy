"""Optional light-ML regime filter (stub).

Scales a rule strategy's weights by a risk-on probability from a frozen,
research-trained artifact. If no artifact is configured, it is a no-op —
the system must never depend on ML availability to trade safely.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


class RegimeFilter:
    """Post-filter: weights *= p(risk-on) from a frozen model artifact.

    Stub implementation: without an artifact, passes weights through unchanged.
    """

    def __init__(self, artifact_path: Path | None = None) -> None:
        self.artifact_path = artifact_path
        self._model = None  # loaded lazily from artifact (research-repo export)

    def apply(self, weights: pd.Series, closes: pd.DataFrame) -> pd.Series:
        """Return filtered weights. No-op when no artifact is loaded."""
        if self._model is None:
            return weights
        raise NotImplementedError("load frozen artifact and scale weights by p(risk-on)")
