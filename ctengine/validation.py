"""Data validation layer: completeness, validity and uniqueness checks before any control is tested.

Records that fail are quarantined with a reason, never silently dropped, and a reconciliation
(records in = records passed + records quarantined) is produced as audit evidence.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

REQUIRED = ["txn_id", "card_id", "merchant_id", "amount", "txn_timestamp", "status", "credit_limit", "initiated_by"]
VALID_STATUS = {"APPROVED", "DECLINED"}


@dataclass
class ValidationResult:
    clean: pd.DataFrame
    quarantine: pd.DataFrame
    checks: pd.DataFrame  # one row per check with failure counts

    @property
    def reconciles(self) -> bool:
        return len(self.clean) + len(self.quarantine) == int(self.checks.attrs["records_in"])


def validate(df: pd.DataFrame) -> ValidationResult:
    df = df.copy()
    records_in = len(df)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["credit_limit"] = pd.to_numeric(df["credit_limit"], errors="coerce")
    df["balance_before"] = pd.to_numeric(df["balance_before"], errors="coerce")
    parsed_ts = pd.to_datetime(df["txn_timestamp"], errors="coerce")

    rules: dict[str, pd.Series] = {}
    for col in REQUIRED:
        rules[f"Completeness: {col} is populated"] = df[col].isna() | (df[col].astype(str).str.strip() == "")
    rules["Validity: amount > 0"] = df["amount"].notna() & (df["amount"] <= 0)
    rules["Validity: credit_limit > 0"] = df["credit_limit"].notna() & (df["credit_limit"] <= 0)
    rules["Validity: timestamp parses"] = df["txn_timestamp"].notna() & parsed_ts.isna()
    rules["Validity: status in {APPROVED, DECLINED}"] = df["status"].notna() & ~df["status"].isin(VALID_STATUS)
    rules["Uniqueness: txn_id is unique"] = df["txn_id"].notna() & df["txn_id"].duplicated(keep=False)

    reasons = pd.Series("", index=df.index)
    rows = []
    for name, failed in rules.items():
        reasons[failed] += name + "; "
        rows.append({"check": name, "records_tested": records_in, "failures": int(failed.sum()),
                     "result": "PASS" if failed.sum() == 0 else "EXCEPTIONS QUARANTINED"})

    bad = reasons != ""
    quarantine = df[bad].assign(quarantine_reason=reasons[bad].str.rstrip("; "))
    clean = df[~bad].copy()
    clean["txn_timestamp"] = parsed_ts[~bad]

    checks = pd.DataFrame(rows)
    checks.attrs["records_in"] = records_in
    return ValidationResult(clean=clean.reset_index(drop=True), quarantine=quarantine.reset_index(drop=True), checks=checks)
