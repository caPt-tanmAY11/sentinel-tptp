"""
ml_models/lstm_encoder.py
─────────────────────────────────────────────────────────────────────────────
LSTM-based transaction sequence encoder for the Sentinel V2 pipeline.

Produces a 16-dimensional embedding from the last N transactions for a
customer, capturing temporal spending patterns that point-in-time features
cannot represent (e.g., accelerating spend, sudden behaviour shifts).

Architecture:
    Input:  (batch, seq_len=20, 11)  — per-transaction features
    LSTM:   hidden=32, 1 layer, batch_first
    FC:     32 → 16 (ReLU)
    Output: (batch, 16)

Training strategy:
    Self-supervised next-transaction-amount-bucket prediction.
    The encoder learns useful representations without requiring labels.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

from enrichment.transaction_classifier import classify_transaction

# Local copy of category encoding to avoid circular import with delta_features.py
_CATEGORY_ENCODING = {
    "SALARY_CREDIT": 0, "EMI_DEBIT": 1, "FAILED_EMI_DEBIT": 2,
    "LENDING_APP_DEBIT": 3, "LENDING_APP_CREDIT": 4, "UTILITY_PAYMENT": 5,
    "ATM_WITHDRAWAL": 6, "GROCERY": 7, "FOOD_DELIVERY": 8, "FUEL": 9,
    "ECOMMERCE": 10, "OTT": 11, "GENERAL_DEBIT": 12, "GENERAL_CREDIT": 13,
    "UNKNOWN": 14, "INVESTMENT_DEBIT": 15,
}

# ── Constants ─────────────────────────────────────────────────────────────────

SEQ_LEN         = 20      # last N transactions per sample
PER_TXN_DIM     = 11      # features per timestep
LSTM_HIDDEN     = 32
EMBEDDING_DIM   = 16
NUM_AMT_BUCKETS = 8       # for self-supervised pretraining target

LSTM_FEATURE_NAMES: List[str] = [f"lstm_emb_{i}" for i in range(EMBEDDING_DIM)]

MODEL_DIR = Path(__file__).parent / "saved_models"
MODEL_DIR.mkdir(exist_ok=True)
ENCODER_PATH = MODEL_DIR / "lstm_encoder.pt"

# Platform ordinal encoding (stable — never reorder)
PLATFORM_ENCODING: Dict[str, int] = {
    "UPI": 0, "NEFT": 1, "IMPS": 2, "RTGS": 3, "ATM": 4,
    "NACH": 5, "ECS": 6, "BBPS": 7, "POS": 8, "MOBILE": 9, "BRANCH": 10,
}


# ── Per-Transaction Feature Builder ──────────────────────────────────────────

def _encode_txn(txn: dict, prev_ts: Optional[datetime] = None) -> np.ndarray:
    """
    Encode a single transaction row into an 11-dimensional feature vector.

    Features (11):
        0: amount_log          — log(1 + amount), normalised
        1: balance_change_pct  — (after - before) / |before|
        2: category_encoded    — ordinal 0-15
        3: platform_encoded    — ordinal 0-10
        4: is_debit            — 1.0 if balance_after < balance_before
        5: is_failed           — 1.0 if failed/reversed
        6: hour_sin            — sin(2π · hour / 24)
        7: hour_cos            — cos(2π · hour / 24)
        8: day_sin             — sin(2π · day / 31)
        9: day_cos             — cos(2π · day / 31)
       10: time_gap_hours      — hours since previous transaction (capped at 168)
    """
    feat = np.zeros(PER_TXN_DIM, dtype=np.float32)

    # 0: Amount (log-scaled, roughly normalised to [0, 1] range)
    amount = float(txn.get("amount", 0.0))
    feat[0] = math.log1p(amount) / 12.0  # log(1+100000) ≈ 11.5

    # 1: Balance change
    bb = txn.get("balance_before")
    ba = txn.get("balance_after")
    if bb is not None and ba is not None and abs(float(bb)) > 0:
        feat[1] = max(-2.0, min(2.0, (float(ba) - float(bb)) / abs(float(bb))))

    # 2: Category (classify using the existing classifier)
    try:
        cat = classify_transaction(txn)
        feat[2] = float(_CATEGORY_ENCODING.get(cat.category, 14)) / 15.0
    except Exception:
        feat[2] = 14.0 / 15.0

    # 3: Platform
    platform = str(txn.get("platform", "UPI")).upper()
    feat[3] = float(PLATFORM_ENCODING.get(platform, 0)) / 10.0

    # 4: Is debit
    if bb is not None and ba is not None:
        feat[4] = 1.0 if float(ba) < float(bb) else 0.0

    # 5: Is failed
    status = str(txn.get("payment_status", "success")).lower()
    feat[5] = 1.0 if status in ("failed", "reversed") else 0.0

    # 6-9: Cyclical time features
    ts = txn.get("txn_timestamp")
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            ts = None
    if ts and hasattr(ts, "hour"):
        hour = ts.hour
        day  = ts.day
        feat[6] = math.sin(2 * math.pi * hour / 24.0)
        feat[7] = math.cos(2 * math.pi * hour / 24.0)
        feat[8] = math.sin(2 * math.pi * day / 31.0)
        feat[9] = math.cos(2 * math.pi * day / 31.0)

    # 10: Time gap from previous transaction
    if prev_ts is not None and ts is not None:
        try:
            if isinstance(prev_ts, str):
                prev_ts = datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))
            gap = (ts - prev_ts).total_seconds() / 3600.0
            feat[10] = min(gap, 168.0) / 168.0  # cap at 7 days
        except Exception:
            feat[10] = 0.5  # default: ~3.5 days

    return feat


def build_sequence_features(
    txn_history: List[dict],
    seq_len: int = SEQ_LEN,
) -> np.ndarray:
    """
    Build (seq_len, PER_TXN_DIM) array from a list of transaction dicts.
    Transactions should be sorted chronologically (oldest first).
    Pads with zeros if fewer than seq_len transactions.
    Truncates from the beginning (keeps most recent) if more.

    Returns: np.ndarray of shape (seq_len, PER_TXN_DIM)
    """
    # Take the most recent seq_len transactions
    recent = txn_history[-seq_len:] if len(txn_history) > seq_len else txn_history

    seq = np.zeros((seq_len, PER_TXN_DIM), dtype=np.float32)
    offset = seq_len - len(recent)  # left-pad with zeros

    prev_ts = None
    for i, txn in enumerate(recent):
        seq[offset + i] = _encode_txn(txn, prev_ts)
        prev_ts = txn.get("txn_timestamp")

    return seq


# ── PyTorch LSTM Model ────────────────────────────────────────────────────────

class TransactionSequenceEncoder(nn.Module):
    """
    LSTM encoder that maps (batch, seq_len, 11) → (batch, 16).
    """

    def __init__(
        self,
        input_dim:     int = PER_TXN_DIM,
        hidden_dim:    int = LSTM_HIDDEN,
        embedding_dim: int = EMBEDDING_DIM,
        num_layers:    int = 1,
        dropout:       float = 0.0,
    ):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_dim, embedding_dim),
            nn.ReLU(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (batch, seq_len, input_dim)
        Returns:
            embedding: (batch, embedding_dim)
        """
        # LSTM output: (batch, seq_len, hidden_dim)
        _, (h_n, _) = self.lstm(x)
        # h_n: (num_layers, batch, hidden_dim) → take last layer
        last_hidden = h_n[-1]  # (batch, hidden_dim)
        return self.fc(last_hidden)


class TransactionEncoderWithHead(nn.Module):
    """
    Full model for self-supervised pre-training.
    Encoder + prediction head for next-transaction amount bucket.
    """

    def __init__(self, num_buckets: int = NUM_AMT_BUCKETS):
        super().__init__()
        self.encoder = TransactionSequenceEncoder()
        self.head = nn.Linear(EMBEDDING_DIM, num_buckets)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        embedding = self.encoder(x)
        logits    = self.head(embedding)
        return embedding, logits


# ── Self-Supervised Dataset ───────────────────────────────────────────────────

def _amount_to_bucket(amount: float) -> int:
    """Map INR amount to one of 8 buckets."""
    boundaries = [50, 200, 500, 1000, 3000, 10000, 50000]
    for i, b in enumerate(boundaries):
        if amount <= b:
            return i
    return len(boundaries)  # 7 = largest


class SequencePretrainingDataset(Dataset):
    """
    Self-supervised dataset for LSTM pre-training.

    For each sample:
        X = features of transactions [i-seq_len : i]
        y = amount bucket of transaction[i] (the next one)
    """

    def __init__(
        self,
        all_customer_txns: Dict[str, List[dict]],
        seq_len: int = SEQ_LEN,
    ):
        self.samples: List[Tuple[np.ndarray, int]] = []
        for cid, txns in all_customer_txns.items():
            if len(txns) < 5:  # need minimum history
                continue
            sorted_txns = sorted(txns, key=lambda t: t["txn_timestamp"])
            for i in range(seq_len, len(sorted_txns)):
                history = sorted_txns[max(0, i - seq_len):i]
                target_txn = sorted_txns[i]
                seq_feat = build_sequence_features(history, seq_len)
                bucket = _amount_to_bucket(float(target_txn.get("amount", 0)))
                self.samples.append((seq_feat, bucket))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, int]:
        seq, bucket = self.samples[idx]
        return torch.from_numpy(seq), bucket


# ── Pre-Training Loop ────────────────────────────────────────────────────────

def pretrain_lstm_encoder(
    all_customer_txns: Dict[str, List[dict]],
    epochs: int = 10,
    batch_size: int = 256,
    lr: float = 1e-3,
    device: str = "cpu",
) -> TransactionSequenceEncoder:
    """
    Pre-train the LSTM encoder using next-transaction-amount prediction.

    Args:
        all_customer_txns: Dict[customer_id → list of txn dicts]
        epochs:            training epochs
        batch_size:        batch size
        lr:                learning rate
        device:            'cpu' or 'cuda'

    Returns:
        Trained encoder (frozen, eval mode)
    """
    print("  Building pre-training dataset...")
    dataset = SequencePretrainingDataset(all_customer_txns)
    print(f"  Pre-training samples: {len(dataset):,}")

    if len(dataset) < 100:
        print("  ⚠ Too few samples for LSTM pre-training — returning untrained encoder")
        encoder = TransactionSequenceEncoder()
        encoder.eval()
        return encoder

    loader = DataLoader(
        dataset, batch_size=batch_size, shuffle=True,
        num_workers=0, pin_memory=False,
    )

    model = TransactionEncoderWithHead().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.CrossEntropyLoss()

    model.train()
    for epoch in range(epochs):
        total_loss = 0.0
        n_batches  = 0
        correct    = 0
        total      = 0

        for X_batch, y_batch in loader:
            X_batch = X_batch.to(device)
            y_batch = y_batch.to(device)

            optimizer.zero_grad()
            _, logits = model(X_batch)
            loss = criterion(logits, y_batch)
            loss.backward()
            optimizer.step()

            total_loss += loss.item()
            n_batches  += 1
            preds       = logits.argmax(dim=1)
            correct    += (preds == y_batch).sum().item()
            total      += len(y_batch)

        avg_loss = total_loss / max(n_batches, 1)
        accuracy = correct / max(total, 1) * 100
        print(f"    Epoch {epoch+1}/{epochs}  loss={avg_loss:.4f}  acc={accuracy:.1f}%")

    # Extract encoder, freeze, and save
    encoder = model.encoder
    encoder.eval()
    for param in encoder.parameters():
        param.requires_grad = False

    save_encoder(encoder)
    return encoder


# ── Persistence ───────────────────────────────────────────────────────────────

def save_encoder(encoder: TransactionSequenceEncoder) -> None:
    """Save encoder weights to disk."""
    torch.save(encoder.state_dict(), str(ENCODER_PATH))
    print(f"  ✓ LSTM encoder saved → {ENCODER_PATH}")


def load_encoder(device: str = "cpu") -> Optional[TransactionSequenceEncoder]:
    """Load pre-trained encoder from disk. Returns None if not found."""
    if not ENCODER_PATH.exists():
        return None
    encoder = TransactionSequenceEncoder()
    encoder.load_state_dict(torch.load(str(ENCODER_PATH), map_location=device))
    encoder.eval()
    for param in encoder.parameters():
        param.requires_grad = False
    return encoder


# ── Embedding Extraction (used by training pipeline and pulse engine) ─────────

def extract_embedding(
    encoder: Optional[TransactionSequenceEncoder],
    txn_history: List[dict],
    device: str = "cpu",
) -> Dict[str, float]:
    """
    Extract 16d LSTM embedding for a single sample.

    Args:
        encoder:     Pre-trained encoder (or None for zero-fallback)
        txn_history: Chronologically sorted list of recent transactions

    Returns:
        Dict of {lstm_emb_0: float, ..., lstm_emb_15: float}
    """
    if encoder is None or len(txn_history) == 0:
        return {name: 0.0 for name in LSTM_FEATURE_NAMES}

    seq = build_sequence_features(txn_history)
    x   = torch.from_numpy(seq).unsqueeze(0).to(device)  # (1, 20, 11)

    with torch.no_grad():
        emb = encoder(x)  # (1, 16)

    emb_np = emb.squeeze(0).cpu().numpy()
    return {
        LSTM_FEATURE_NAMES[i]: round(float(emb_np[i]), 6)
        for i in range(EMBEDDING_DIM)
    }
