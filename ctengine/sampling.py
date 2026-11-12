"""Audit sampling: random, stratified and judgmental selection from a control's population."""
from __future__ import annotations

import numpy as np
import pandas as pd

AMOUNT_BANDS = [0, 5_000, 50_000, 200_000, 500_000, float("inf")]
BAND_LABELS = ["<5k", "5k-50k", "50k-2L", "2L-5L", ">5L"]


def random_sample(pop: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    return pop.sample(n=min(n, len(pop)), random_state=seed).assign(sample_method="Random")


def stratified_sample(pop: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Proportional allocation across amount bands, at least one item from every non-empty band."""
    pop = pop.assign(stratum=pd.cut(pop["amount"], AMOUNT_BANDS, labels=BAND_LABELS, right=False))
    sizes = pop["stratum"].value_counts()
    sizes = sizes[sizes > 0]
    alloc = np.maximum(1, np.floor(sizes / sizes.sum() * n)).astype(int)
    while alloc.sum() < min(n, len(pop)):  # hand out the remainder to the largest strata
        for s in sizes.sort_values(ascending=False).index:
            if alloc.sum() >= n:
                break
            if alloc[s] < sizes[s]:
                alloc[s] += 1
    parts = [pop[pop["stratum"] == s].sample(n=min(int(k), int(sizes[s])), random_state=seed) for s, k in alloc.items()]
    return pd.concat(parts).assign(sample_method="Stratified (amount band)")


def judgmental_sample(pop: pd.DataFrame, n: int) -> pd.DataFrame:
    """Risk-based selection: largest amounts, off-hours activity and high-risk merchant categories."""
    ts = pd.to_datetime(pop["txn_timestamp"])
    score = (
        pop["amount"].rank(pct=True) * 2
        + ts.dt.hour.isin([0, 1, 2, 3, 4]).astype(int)
        + (ts.dt.dayofweek >= 5).astype(int) * 0.5
        + pop["merchant_category"].isin(["Jewellery", "Luxury Retail", "Electronics"]).astype(int)
    )
    return pop.assign(risk_score=score.round(3)).nlargest(min(n, len(pop)), "risk_score").assign(sample_method="Judgmental (risk-based)")


def select(pop: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Combined sample: n random + n stratified + n/2 judgmental, de-duplicated."""
    s = pd.concat([random_sample(pop, n, seed), stratified_sample(pop, n, seed + 1), judgmental_sample(pop, max(1, n // 2))])
    s = s.groupby("txn_id", as_index=False).agg({**{c: "first" for c in s.columns if c not in ("txn_id", "sample_method")},
                                                "sample_method": lambda x: " + ".join(sorted(set(x)))})
    return s
