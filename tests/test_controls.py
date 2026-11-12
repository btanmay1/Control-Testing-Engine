import json
from pathlib import Path

import pandas as pd
import pytest

from ctengine import controls as C
from ctengine import evaluation as E
from ctengine import sampling as S
from ctengine.validation import validate

CFG = json.loads((Path(__file__).resolve().parent.parent / "config" / "controls.json").read_text())


def txn(i, **kw):
    base = dict(txn_id=f"T{i}", card_id="C1", merchant_id="M1", merchant_category="Grocery", channel="POS",
                amount=1000.0, currency="INR", txn_timestamp="2026-01-01 10:00:00", credit_limit=100000.0,
                balance_before=0.0, status="APPROVED", initiated_by="E1", approver_1="E2", approver_2=None)
    base.update(kw)
    return base


def run_all(rows):
    df = validate(pd.DataFrame(rows)).clean
    con = C.to_sqlite(df)
    sql = {k: set(v["txn_id"]) for k, v in C.run_sql(con, CFG["controls"]).items()}
    pdr = C.reperform(df, CFG["controls"])
    assert sql == pdr, "SQL and Pandas implementations must agree"
    return sql


def test_dual_approval():
    r = run_all([
        txn(1, amount=250000.0, approver_2="E3"),            # pass
        txn(2, amount=250000.0, approver_2=None),            # missing second approver
        txn(3, amount=250000.0, approver_2="E2"),            # same approver twice
        txn(4, amount=200000.0, approver_2=None),            # exactly at threshold -> not in scope
        txn(5, amount=250000.0, approver_2=None, status="DECLINED"),
    ])
    assert r["CTL-01"] == {"T2", "T3"}


def test_segregation_of_duties():
    r = run_all([txn(1), txn(2, approver_1="E1"), txn(3, amount=300000.0, approver_2="E1")])
    assert r["CTL-02"] == {"T2", "T3"}


def test_credit_limit():
    r = run_all([
        txn(1, balance_before=99000.0, amount=1000.0),                    # exactly at limit: pass
        txn(2, balance_before=99000.0, amount=1000.01),                   # breach
        txn(3, balance_before=99000.0, amount=5000.0, status="DECLINED"),  # control worked
    ])
    assert r["CTL-03"] == {"T2"}


def test_duplicates_window():
    r = run_all([
        txn(1, txn_timestamp="2026-01-01 10:00:00"),
        txn(2, txn_timestamp="2026-01-01 10:01:00"),                       # 60s -> duplicate
        txn(3, txn_timestamp="2026-01-01 10:02:01"),                       # 61s -> not duplicate
        txn(4, txn_timestamp="2026-01-01 10:02:05", merchant_id="M2"),     # other merchant
        txn(5, txn_timestamp="2026-01-01 10:02:10", amount=999.0),         # other amount
    ])
    assert r["CTL-04"] == {"T2"}


def test_validation_quarantines_and_reconciles():
    v = validate(pd.DataFrame([txn(1), txn(2, amount=None), txn(3, amount=-5.0), txn(4, status="X"), txn(1)]))
    assert len(v.clean) == 0
    assert v.reconciles
    assert len(v.quarantine) == 5


def test_sampling_sizes():
    pop = pd.DataFrame([txn(i, amount=float(a)) for i, a in enumerate([100, 6000, 60000, 250000, 600000] * 40)])
    s = S.stratified_sample(pop, 25, seed=1)
    assert len(s) == 25 and s["stratum"].nunique() == 5
    assert len(S.judgmental_sample(pop, 10)) == 10
    assert len(S.random_sample(pop, 500, seed=1)) == len(pop)


@pytest.mark.parametrize("design,oe,expected", [
    ("Effective", "Effective", "Effective"),
    ("Needs Improvement", "Effective", "Partially Effective"),
    ("Effective", "Ineffective", "Ineffective"),
])
def test_rating(design, oe, expected):
    assert E.overall_rating(design, oe) == expected


def test_operating_effectiveness_thresholds():
    assert E.operating_effectiveness(0, 0, 0.01, 0.02) == "Effective"
    assert E.operating_effectiveness(1, 0, 0.01, 0.02) == "Needs Improvement"
    assert E.operating_effectiveness(5, 0, 0.05, 0.02) == "Ineffective"
