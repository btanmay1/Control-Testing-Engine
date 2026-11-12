"""Generate a synthetic card-transaction population with known, injected control exceptions.

Every injected exception is recorded in a ground-truth column (`_injected`) so the engine's
results can be reconciled against what was planted. The column is dropped before testing.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

HIGH_VALUE_THRESHOLD = 200_000
CREDIT_LIMITS = np.array([50_000, 100_000, 200_000, 500_000, 1_000_000, 2_500_000])
MCC = ["Grocery", "Travel", "Electronics", "Fuel", "Dining", "Jewellery", "Utilities", "Healthcare", "Education", "Luxury Retail"]
CHANNELS = ["POS", "E-commerce", "Contactless", "ATM", "Recurring"]


def generate(n: int = 50_000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    n_cards = 6_000
    card_ids = np.array([f"CARD{i:06d}" for i in range(n_cards)])
    card_limits = rng.choice(CREDIT_LIMITS, size=n_cards, p=[0.25, 0.25, 0.2, 0.15, 0.1, 0.05])
    employees = np.array([f"EMP{i:04d}" for i in range(1, 201)])
    merchants = np.array([f"MER{i:05d}" for i in range(1, 2_501)])

    card_idx = rng.integers(0, n_cards, size=n)
    amount = np.round(rng.lognormal(mean=8.3, sigma=1.3, size=n), 2)
    # ~3% high-value transactions above Rs. 2 lakh
    hv = rng.random(n) < 0.03
    amount[hv] = np.round(rng.uniform(200_001, 1_500_000, size=hv.sum()), 2)

    start = pd.Timestamp("2025-10-01")
    seconds = rng.integers(0, 365 * 24 * 3600, size=n)
    ts = start + pd.to_timedelta(np.sort(seconds), unit="s")

    df = pd.DataFrame({
        "txn_id": [f"TXN{i:07d}" for i in range(1, n + 1)],
        "card_id": card_ids[card_idx],
        "merchant_id": rng.choice(merchants, size=n),
        "merchant_category": rng.choice(MCC, size=n),
        "channel": rng.choice(CHANNELS, size=n, p=[0.35, 0.35, 0.2, 0.05, 0.05]),
        "amount": amount,
        "currency": "INR",
        "txn_timestamp": ts,
        "credit_limit": card_limits[card_idx].astype(float),
        "initiated_by": rng.choice(employees, size=n),
    })

    # Balance before the transaction: always leaves room for the amount (clean case)
    headroom = np.maximum(df["credit_limit"] - df["amount"], 0)
    df["balance_before"] = np.round(headroom * rng.uniform(0, 0.9, size=n), 2)
    over_limit = df["amount"] > df["credit_limit"]
    df["status"] = np.where(over_limit, "DECLINED", "APPROVED")  # control working correctly
    df.loc[~over_limit & (rng.random(n) < 0.02), "status"] = "DECLINED"  # other declines

    # Approvers: approver_1 for every txn, approver_2 for high value; all distinct in the clean case
    init = df["initiated_by"].to_numpy()
    approver_1 = rng.choice(employees, size=n)
    approver_2 = rng.choice(employees, size=n)
    while True:
        bad1 = approver_1 == init
        bad2 = (approver_2 == init) | (approver_2 == approver_1)
        if not (bad1.any() or bad2.any()):
            break
        approver_1[bad1] = rng.choice(employees, size=bad1.sum())
        approver_2[bad2] = rng.choice(employees, size=bad2.sum())
    df["approver_1"] = approver_1
    df["approver_2"] = np.where(df["amount"] > HIGH_VALUE_THRESHOLD, approver_2, None)

    df["_injected"] = ""
    approved = df["status"] == "APPROVED"

    # CTL-01: ~4% of approved high-value txns miss a second approval or reuse the same approver
    hv_idx = df.index[(df["amount"] > HIGH_VALUE_THRESHOLD) & approved]
    pick = rng.choice(hv_idx, size=max(1, int(len(hv_idx) * 0.04)), replace=False)
    half = len(pick) // 2
    df.loc[pick[:half], "approver_2"] = None
    df.loc[pick[half:], "approver_2"] = df.loc[pick[half:], "approver_1"]
    df.loc[pick, "_injected"] += "CTL-01;"

    # CTL-02: ~0.8% of txns approved by the initiator
    pick = rng.choice(df.index[approved & (df["_injected"] == "")], size=int(n * 0.008), replace=False)
    df.loc[pick, "approver_1"] = df.loc[pick, "initiated_by"]
    df.loc[pick, "_injected"] += "CTL-02;"

    # CTL-03: ~1.2% approved even though balance + amount exceeds the credit limit
    eligible = df.index[approved & (df["amount"] < df["credit_limit"])]
    pick = rng.choice(eligible, size=int(n * 0.012), replace=False)
    gap = df.loc[pick, "credit_limit"] - df.loc[pick, "amount"]
    df.loc[pick, "balance_before"] = np.round(gap + df.loc[pick, "amount"] * rng.uniform(0.05, 0.6, size=len(pick)), 2)
    df.loc[pick, "_injected"] += "CTL-03;"

    # CTL-04: ~250 duplicate charges within 1-59 seconds of the original
    src = rng.choice(df.index[approved], size=250, replace=False)
    dups = df.loc[src].copy()
    dups["txn_timestamp"] = dups["txn_timestamp"] + pd.to_timedelta(rng.integers(1, 60, size=len(dups)), unit="s")
    dups["_injected"] = dups["_injected"] + "CTL-04;"
    # near-misses that must NOT be flagged (61-300 seconds later)
    near_pool = df.index[approved].difference(src)
    near = df.loc[rng.choice(near_pool, size=100, replace=False)].copy()
    near["txn_timestamp"] = near["txn_timestamp"] + pd.to_timedelta(rng.integers(61, 300, size=len(near)), unit="s")

    df = pd.concat([df, dups, near], ignore_index=True).sort_values("txn_timestamp", kind="stable").reset_index(drop=True)
    df["txn_id"] = [f"TXN{i:07d}" for i in range(1, len(df) + 1)]

    # Data-quality defects for the validation layer to quarantine
    bad = rng.choice(df.index, size=30, replace=False)
    df["amount"] = df["amount"].astype(object)
    df.loc[bad[:10], "amount"] = None
    df.loc[bad[10:18], "amount"] = -abs(rng.uniform(100, 5_000, 8)).round(2)
    df.loc[bad[18:24], "card_id"] = None
    df.loc[bad[24:27], "status"] = "UNKNOWN"
    df.loc[bad[27:], "txn_id"] = df.loc[bad[:3], "txn_id"].to_numpy()  # duplicate keys
    df["txn_timestamp"] = df["txn_timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=50_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("data/transactions.csv"))
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df = generate(args.n, args.seed)
    df.to_csv(args.out, index=False)
    print(f"Wrote {len(df):,} transactions to {args.out}")


if __name__ == "__main__":
    main()
