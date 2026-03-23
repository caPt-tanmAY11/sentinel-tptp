"""
schemas/transaction_event.py
─────────────────────────────────────────────────────────────────────────────
Defines the canonical shape of every transaction event in Sentinel V2.

DESIGN PRINCIPLE — RAW FACTS ONLY:
  A TransactionEvent carries only observable facts from the bank ledger.
  It does NOT carry interpretive labels.

  NEVER stored on this event:
    - transaction_type  (pre-classified label)
    - is_salary         (derived flag)
    - is_lending_app    (derived flag)
    - is_emi_payment    (derived flag)

  The enrichment/transaction_classifier.py infers purpose from:
    - receiver_id  (e.g. "slice@upi" → lending app)
    - sender_name  (e.g. "TCS Payroll Services" → salary)
    - platform     (e.g. "NACH" + receiver pattern → EMI)

  Classifier output is EPHEMERAL — used for feature computation only.
  It is never written back to this object or to the transactions table.

Indian Banking Context:
  UPI VPA format:  name@bankcode  (e.g. rahul.sharma@sbi, slice@upi)
  NACH/ECS:        recurring EMI auto-debits from savings account
  BBPS:            utility bill payments (bescom@bbps, tatapower@bbps)
  IMPS/NEFT/RTGS:  salary credits and large transfers
  ATM:             cash withdrawals; counterparty is ATM location code
  Reference:       UTR (NEFT/RTGS) or RRN (UPI) — unique per transaction
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# Valid platforms — matches CHECK constraint in init.sql
VALID_PLATFORMS = frozenset({
    "UPI", "NEFT", "IMPS", "RTGS", "ATM",
    "NACH", "ECS", "BBPS", "POS", "MOBILE", "BRANCH",
})

# Valid payment statuses — lowercase to match Indian payment gateway conventions
VALID_STATUSES = frozenset({"success", "failed", "pending", "reversed"})


class TransactionEvent(BaseModel):
    """
    Single raw transaction event — the atomic unit of the entire Sentinel pipeline.

    This is a FACT RECORD. The model infers everything else from these raw facts.
    """

    # ── Identity ─────────────────────────────────────────────────
    event_id:       str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_id:    str = Field(..., min_length=1, max_length=50)
    account_number: Optional[str] = None   # customer's bank account number

    # ── Counterparty (raw VPA or account reference) ───────────────
    # For a DEBIT: sender = customer, receiver = payee
    # For a CREDIT: sender = payer, receiver = customer
    sender_id:      Optional[str] = None   # UPI VPA or bank account ref
    sender_name:    Optional[str] = None   # e.g. "Rahul Sharma", "TCS Payroll Services"
    receiver_id:    Optional[str] = None   # e.g. "slice@upi", "bescom@bbps"
    receiver_name:  Optional[str] = None   # e.g. "Slice Fintech Pvt Ltd", "BESCOM"

    # ── Transaction Facts ─────────────────────────────────────────
    amount:         float = Field(..., gt=0, description="Transaction amount in INR")
    platform:       str   = Field(..., description="Payment platform: UPI/NEFT/IMPS/ATM/NACH/ECS/BBPS/POS/MOBILE/BRANCH/RTGS")
    payment_status: str   = Field(default="success", description="success/failed/pending/reversed")
    reference_number: Optional[str] = None  # UTR (NEFT/RTGS) or RRN (UPI)

    # ── Balance Tracking ─────────────────────────────────────────
    # Represents the customer's PRIMARY savings account balance.
    # balance_change_pct is auto-computed if not provided.
    balance_before:     Optional[float] = None
    balance_after:      Optional[float] = None
    balance_change_pct: Optional[float] = None   # (after - before) / |before|

    # ── Timing ───────────────────────────────────────────────────
    txn_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # ── Kafka Metadata (filled by consumer, not by producer) ──────
    kafka_partition: Optional[int] = None
    kafka_offset:    Optional[int] = None
    ingested_at:     Optional[datetime] = None

    # ── Validators ───────────────────────────────────────────────

    @field_validator("amount")
    @classmethod
    def round_amount(cls, v: float) -> float:
        return round(v, 2)

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        upper = v.upper()
        if upper not in VALID_PLATFORMS:
            raise ValueError(
                f"platform must be one of {sorted(VALID_PLATFORMS)}, got '{v}'"
            )
        return upper

    @field_validator("payment_status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        lower = v.lower()
        if lower not in VALID_STATUSES:
            raise ValueError(
                f"payment_status must be one of {sorted(VALID_STATUSES)}, got '{v}'"
            )
        return lower

    @field_validator("reference_number")
    @classmethod
    def truncate_reference(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return v[:60]
        return v

    @model_validator(mode="after")
    def compute_balance_change(self) -> "TransactionEvent":
        """Auto-compute balance_change_pct when balances are present."""
        if (
            self.balance_change_pct is None
            and self.balance_before is not None
            and self.balance_after is not None
            and abs(self.balance_before) > 0
        ):
            self.balance_change_pct = round(
                (self.balance_after - self.balance_before) / abs(self.balance_before), 4
            )
        return self

    # ── Serialization Helpers ────────────────────────────────────

    def to_dict(self) -> dict:
        data = self.model_dump()
        data["txn_timestamp"] = self.txn_timestamp.isoformat()
        if self.ingested_at:
            data["ingested_at"] = self.ingested_at.isoformat()
        return data

    def to_kafka_payload(self) -> bytes:
        """Serialize for publishing to Kafka."""
        import json
        return json.dumps(self.to_dict()).encode("utf-8")

    @classmethod
    def from_dict(cls, data: dict) -> "TransactionEvent":
        return cls(**data)

    @classmethod
    def from_kafka_payload(cls, payload: bytes) -> "TransactionEvent":
        import json
        return cls.from_dict(json.loads(payload.decode("utf-8")))