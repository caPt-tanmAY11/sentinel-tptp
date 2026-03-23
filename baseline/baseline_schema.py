"""
baseline/baseline_schema.py
─────────────────────────────────────────────────────────────────────────────
Pydantic schema for a customer's statistical baseline.
Computed from days 1-90 of history. Ground-zero for deviation scoring.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Dict, Optional
from pydantic import BaseModel


class CustomerBaseline(BaseModel):
    customer_id:        str
    computed_at:        datetime
    window_days:        int = 90
    history_start_date: Optional[str] = None
    history_end_date:   Optional[str] = None
    transaction_count:  int = 0
    low_confidence:     bool = False   # True if < BASELINE_MIN_TRANSACTIONS

    feature_means: Dict[str, float] = {}
    feature_stds:  Dict[str, float] = {}
    feature_p25:   Dict[str, float] = {}
    feature_p75:   Dict[str, float] = {}
    feature_p95:   Dict[str, float] = {}

    def z_score(self, feature_name: str, value: float) -> float:
        """Z-score of value vs this customer's baseline. Returns 0.0 if unknown."""
        if feature_name not in self.feature_means:
            return 0.0
        mu    = self.feature_means[feature_name]
        sigma = self.feature_stds.get(feature_name, 1.0)
        if sigma < 1e-6 or not math.isfinite(sigma):
            return 0.0
        z = (value - mu) / sigma
        z = z if math.isfinite(z) else 0.0
        # Dampen scores for low-confidence baselines
        if self.low_confidence:
            z *= 0.5
        return round(z, 4)

    def is_anomalous(self, feature_name: str, value: float, z_threshold: float = 2.5) -> bool:
        return abs(self.z_score(feature_name, value)) > z_threshold

    def to_redis_dict(self) -> dict:
        return {
            "customer_id":       self.customer_id,
            "computed_at":       self.computed_at.isoformat(),
            "window_days":       self.window_days,
            "transaction_count": self.transaction_count,
            "low_confidence":    self.low_confidence,
            "feature_means":     self.feature_means,
            "feature_stds":      self.feature_stds,
            "feature_p25":       self.feature_p25,
            "feature_p75":       self.feature_p75,
            "feature_p95":       self.feature_p95,
        }

    @classmethod
    def from_redis_dict(cls, data: dict) -> "CustomerBaseline":
        dt = datetime.fromisoformat(data["computed_at"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return cls(
            customer_id=data["customer_id"],
            computed_at=dt,
            window_days=data.get("window_days", 90),
            transaction_count=data.get("transaction_count", 0),
            low_confidence=data.get("low_confidence", False),
            feature_means=data.get("feature_means", {}),
            feature_stds=data.get("feature_stds",   {}),
            feature_p25=data.get("feature_p25",     {}),
            feature_p75=data.get("feature_p75",     {}),
            feature_p95=data.get("feature_p95",     {}),
        )