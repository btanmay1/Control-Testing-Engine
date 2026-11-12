"""Run each control test in SQL (SQLite) and independently re-perform it in Pandas.

The two implementations must agree; a mismatch means the test itself is wrong, so the run fails.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "control_tests.sql"


def load_queries(path: Path = SQL_FILE) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"^-- name: (\S+)\s*$", text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def to_sqlite(df: pd.DataFrame, db_path: str | Path = ":memory:") -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    out = df.copy()
    ts = pd.to_datetime(out["txn_timestamp"])
    out["epoch"] = (ts - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)
    out["txn_timestamp"] = ts.dt.strftime("%Y-%m-%d %H:%M:%S")
    out.to_sql("transactions", con, index=False, if_exists="replace")
    con.execute("CREATE INDEX IF NOT EXISTS ix_dup ON transactions(card_id, merchant_id, amount, epoch)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_status_amt ON transactions(status, amount)")
    return con


def _params(ctl: dict, query: str) -> dict:
    wanted = set(re.findall(r":(\w+)", query))
    return {k: ctl[k] for k in wanted}


def run_sql(con: sqlite3.Connection, controls: list[dict]) -> dict[str, pd.DataFrame]:
    queries = load_queries()
    return {c["control_id"]: pd.read_sql_query(queries[c["control_id"]], con, params=_params(c, queries[c["control_id"]]))
            for c in controls}


# ---------- Pandas re-performance (independent second implementation) ----------

def pandas_ctl01(df: pd.DataFrame, threshold_inr: float) -> set[str]:
    m = (df["status"] == "APPROVED") & (df["amount"] > threshold_inr) & (
        df["approver_1"].isna() | df["approver_2"].isna() | (df["approver_1"] == df["approver_2"]))
    return set(df.loc[m, "txn_id"])


def pandas_ctl02(df: pd.DataFrame) -> set[str]:
    m = (df["initiated_by"] == df["approver_1"]) | (df["approver_2"].notna() & (df["initiated_by"] == df["approver_2"]))
    return set(df.loc[m, "txn_id"])


def pandas_ctl03(df: pd.DataFrame) -> set[str]:
    m = (df["status"] == "APPROVED") & (df["balance_before"] + df["amount"] > df["credit_limit"])
    return set(df.loc[m, "txn_id"])


def pandas_ctl04(df: pd.DataFrame, window_seconds: int) -> set[str]:
    a = df[df["status"] == "APPROVED"].copy()
    a["ts"] = pd.to_datetime(a["txn_timestamp"])
    a = a.sort_values(["card_id", "merchant_id", "amount", "ts", "txn_id"])
    gap = a.groupby(["card_id", "merchant_id", "amount"])["ts"].diff().dt.total_seconds()
    return set(a.loc[gap <= window_seconds, "txn_id"])


def reperform(df: pd.DataFrame, controls: list[dict]) -> dict[str, set[str]]:
    by_id = {c["control_id"]: c for c in controls}
    return {
        "CTL-01": pandas_ctl01(df, by_id["CTL-01"]["threshold_inr"]),
        "CTL-02": pandas_ctl02(df),
        "CTL-03": pandas_ctl03(df),
        "CTL-04": pandas_ctl04(df, by_id["CTL-04"]["window_seconds"]),
    }


def population_in_scope(df: pd.DataFrame, ctl: dict) -> pd.DataFrame:
    """The population each control applies to (the denominator for exception rates and sampling)."""
    cid = ctl["control_id"]
    if cid == "CTL-01":
        return df[(df["status"] == "APPROVED") & (df["amount"] > ctl["threshold_inr"])]
    if cid in ("CTL-03", "CTL-04"):
        return df[df["status"] == "APPROVED"]
    return df
