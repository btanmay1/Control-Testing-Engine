"""End-to-end control testing run.

    python -m ctengine.main                      # generate 50,000 synthetic transactions and test them
    python -m ctengine.main --input my.csv       # test your own extract (same columns)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from . import controls as C
from . import evaluation as E
from . import report as R
from . import sampling as S
from .generate_data import generate
from .validation import validate

ROOT = Path(__file__).resolve().parent.parent


def run(df_raw: pd.DataFrame, cfg: dict, out_dir: Path, seed: int = 7, db_path: Path | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    truth = df_raw.pop("_injected") if "_injected" in df_raw.columns else None

    # 1. Validate
    v = validate(df_raw)
    assert v.reconciles, "Record count does not reconcile after validation"
    df = v.clean
    print(f"[validate] {len(df_raw):,} in | {len(df):,} passed | {len(v.quarantine):,} quarantined")

    # 2. Full-population SQL tests + 3. Pandas re-performance
    con = C.to_sqlite(df, db_path or ":memory:")
    sql_results = C.run_sql(con, cfg["controls"])
    reperformed = C.reperform(df, cfg["controls"])

    recon_rows, summary_rows, exc_frames, sample_frames = [], [], [], []
    for ctl in cfg["controls"]:
        cid = ctl["control_id"]
        exc = sql_results[cid]
        sql_ids = set(exc["txn_id"])
        pd_ids = reperformed[cid]
        if sql_ids != pd_ids:
            raise RuntimeError(f"{cid}: SQL and Pandas disagree ({len(sql_ids ^ pd_ids)} differences)")
        row = {"Control ID": cid, "SQL exceptions": len(sql_ids), "Pandas exceptions": len(pd_ids), "SQL = Pandas": "Yes"}
        if truth is not None:
            planted = set(df_raw.loc[truth.fillna("").str.contains(cid) & df_raw["txn_id"].isin(df["txn_id"]), "txn_id"])
            row.update({"Planted (ground truth)": len(planted), "Detected planted": len(planted & sql_ids),
                        "Missed": len(planted - sql_ids), "Unplanted detections": len(sql_ids - planted)})
        recon_rows.append(row)

        pop = C.population_in_scope(df, ctl)
        rate = len(sql_ids) / len(pop) if len(pop) else 0.0

        # 4. Sampling and sample testing
        sample = S.select(pop, cfg["sample_size"], seed)
        sample["control_id"] = cid
        sample["test_result"] = sample["txn_id"].isin(sql_ids).map({True: "Deviation", False: "Pass"})
        deviations = int((sample["test_result"] == "Deviation").sum())
        sample_frames.append(sample[["control_id", "txn_id", "card_id", "amount", "txn_timestamp", "sample_method", "test_result"]])

        # 5-7. Effectiveness and rating
        d = E.design_effectiveness(ctl)
        oe = E.operating_effectiveness(deviations, cfg["allowable_sample_deviations"], rate, cfg["tolerable_exception_rate"])
        rating = E.overall_rating(d["design_verdict"], oe)
        obs = (f"{len(sql_ids):,} exceptions in {len(pop):,} in-scope transactions ({rate:.2%}) against a "
               f"{cfg['tolerable_exception_rate']:.0%} tolerance; {deviations} deviation(s) in a sample of {len(sample)}.")
        summary_rows.append({
            "Control ID": cid, "Control": ctl["name"], "Type": f"{ctl['type']} / {ctl['nature']}", "Owner": ctl["owner"],
            "Population": f"{len(pop):,}", "Exceptions": f"{len(sql_ids):,}", "Exception rate": f"{rate:.2%}",
            "Sample size": len(sample), "Sample deviations": deviations,
            "Design score": d["design_score"], "Design effectiveness": d["design_verdict"], "Design gaps": d["design_gaps"],
            "Operating effectiveness": oe, "Control rating": rating, "Observation": obs})

        exc = exc.copy()
        exc.insert(0, "control_id", cid)
        exc.insert(1, "control_name", ctl["name"])
        exc_frames.append(exc)

    summary = pd.DataFrame(summary_rows)
    exceptions = pd.concat(exc_frames, ignore_index=True)
    exceptions.insert(0, "exception_id", [f"EXC-{i:05d}" for i in range(1, len(exceptions) + 1)])
    exceptions["detected_by"] = "SQL full-population test; re-performed in Pandas"
    exceptions["status"] = "Open - pending owner response"
    exceptions = exceptions[["exception_id", "control_id", "control_name", "txn_id", "card_id", "amount", "txn_timestamp",
                             "exception_detail", "initiated_by", "approver_1", "approver_2", "balance_before", "credit_limit",
                             "excess_over_limit", "original_txn_id", "seconds_after_original", "detected_by", "status"]]
    samples = pd.concat(sample_frames, ignore_index=True)
    recon = pd.DataFrame(recon_rows)

    ts = pd.to_datetime(df["txn_timestamp"])
    meta = {"period": f"{ts.min():%d %b %Y} - {ts.max():%d %b %Y}", "generated": R.now(), "records_in": len(df_raw),
            "records_clean": len(df), "records_quarantined": len(v.quarantine), "sample_size": cfg["sample_size"],
            "allowable": cfg["allowable_sample_deviations"], "tolerable": cfg["tolerable_exception_rate"]}

    exceptions.to_csv(out_dir / "exception_evidence_log.csv", index=False)
    R.write_excel(out_dir / "control_testing_report.xlsx", summary, exceptions, samples, v.checks, v.quarantine, recon, meta)
    R.write_pdf(out_dir / "control_testing_report.pdf", summary, exceptions.nlargest(15, "amount"), meta)
    (out_dir / "summary.json").write_text(json.dumps({"meta": meta, "controls": summary_rows, "reconciliation": recon_rows}, indent=2, default=str))

    print(summary[["Control ID", "Population", "Exceptions", "Exception rate", "Sample deviations",
                   "Design effectiveness", "Operating effectiveness", "Control rating"]].to_string(index=False))
    print("\n" + recon.to_string(index=False))
    print(f"\nReports written to {out_dir}")
    return {"summary": summary, "exceptions": exceptions, "samples": samples, "reconciliation": recon}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, help="CSV of transactions; omit to generate synthetic data")
    ap.add_argument("--n", type=int, default=50_000, help="synthetic transactions to generate")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "controls.json")
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    ap.add_argument("--db", type=Path, help="optional SQLite file to persist the tested population")
    args = ap.parse_args()

    cfg = json.loads(args.config.read_text())
    if args.input:
        df = pd.read_csv(args.input)
    else:
        df = generate(args.n, args.seed)
        args.out.mkdir(parents=True, exist_ok=True)
        print(f"[generate] {len(df):,} synthetic transactions (seed {args.seed})")
    run(df, cfg, args.out, db_path=args.db)


if __name__ == "__main__":
    main()
