# Automated Control Testing Engine – Card Transaction Controls

A Python + SQL framework that tests four first-line card-transaction controls across a full population of
**50,000+ synthetic transactions**, re-performs every test independently, draws audit samples, rates design and
operating effectiveness, and produces an Excel workbook and PDF report on every run.

The project is documented the way a control-testing file would be: objective, scope, data flow, assumptions,
test steps and evidence.

---

## 1. Objective

Give a first line of defence team repeatable, evidence-backed answers to two questions for each control:

1. **Is the control designed to address its risk?** (design effectiveness)
2. **Did it actually operate across the period?** (operating effectiveness, on the full population and on a sample)

## 2. Controls in scope

| ID | Control | Type | Test logic (exception when…) |
|----|---------|------|------------------------------|
| CTL-01 | Dual approval above Rs. 2,00,000 | Preventive / Manual | Approved, amount > 2,00,000, and second approver missing **or** same as first approver |
| CTL-02 | Segregation of duties | Preventive / Automated | Initiator also appears as approver 1 or approver 2 |
| CTL-03 | Credit-limit breach block | Preventive / Automated | Approved and `balance_before + amount > credit_limit` |
| CTL-04 | Duplicate transactions within 60 seconds | Detective / Automated | Same card, merchant and amount as the previous approved transaction, ≤ 60 seconds later |

Thresholds, tolerances, sample sizes and the design attributes of each control are kept in
[`config/controls.json`](config/controls.json), not in the code.

## 3. Data flow

```
generate_data.py ──► validation.py ──► SQLite ──► sql/control_tests.sql ──► exceptions ─┐
  (50,350 txns,       completeness,               full-population tests                  │
   planted defects)   validity, uniqueness                                               ├─► report.py
                      quarantine + reconcile ──► controls.py (Pandas re-performance) ────┤    Excel + PDF
                                                 must equal SQL, else run fails          │    + evidence log
                                              ──► sampling.py (random / stratified /     │
                                                  judgmental) ──► evaluation.py ─────────┘
                                                  design, operating, overall rating
```

## 4. Test steps

1. **Data validation** – 8 completeness checks, 4 validity checks (amount > 0, credit limit > 0, timestamp parses,
   valid status) and a uniqueness check on `txn_id`. Failing records are **quarantined with a reason**, not dropped,
   and record counts are reconciled (in = passed + quarantined).
2. **Full-population testing** – each control runs as a SQL query in SQLite ([`sql/control_tests.sql`](sql/control_tests.sql)).
   CTL-04 uses a `LAG()` window over `(card, merchant, amount)` ordered by time.
3. **Re-performance** – every test is coded a second time in Pandas. If the two sets of exceptions differ, the run stops.
4. **Sampling** – per control: random (n = 60), stratified by amount band with proportional allocation (n = 60), and
   judgmental/risk-based (n = 30: largest amounts, 00:00–05:00 activity, weekends, high-risk merchant categories).
   Overlapping selections are de-duplicated. Sample size follows attribute sampling at 95% confidence and 5% tolerable
   deviation rate with zero expected deviations (≈ 59).
5. **Design effectiveness** – six attributes: owner assigned, procedure documented, threshold defined, evidence retained,
   addresses the risk, timely execution.
6. **Operating effectiveness** – *Effective* when sample deviations ≤ 0 and the population exception rate ≤ 2%;
   *Needs Improvement* up to 2× tolerance; otherwise *Ineffective*.
7. **Control rating** – *Effective* only when design and operation are both effective; *Ineffective* if either is;
   otherwise *Partially Effective*.

## 5. Results on the default run (seed 42)

| Control | In-scope population | Exceptions | Exception rate | Sample deviations | Design | Operating | Rating |
|---|---:|---:|---:|---:|---|---|---|
| CTL-01 Dual approval | 264 | 10 | 3.79% | 4 | Effective | Needs Improvement | Partially Effective |
| CTL-02 Segregation of duties | 50,320 | 401 | 0.80% | 1 | Effective | Needs Improvement | Partially Effective |
| CTL-03 Credit-limit breach | 47,618 | 606 | 1.27% | 3 | Effective | Needs Improvement | Partially Effective |
| CTL-04 Duplicates (60s) | 47,618 | 249 | 0.52% | 1 | Needs Improvement (procedure not documented) | Needs Improvement | Partially Effective |

**Accuracy check against planted ground truth:** SQL and Pandas agreed on every control. All planted exceptions were
found with zero false positives, except one CTL-04 duplicate whose original transaction had a planted data-quality
defect (negative amount) and was quarantined, so there was no original left to match it against. 100 "near-miss"
repeats placed 61–300 seconds apart were correctly **not** flagged.

Sample outputs from this run are in [`sample_output/`](sample_output):

- `control_testing_report.xlsx` – Summary, Exception Log, Sample Testing, Data Validation, Quarantine,
  Reconciliation and Methodology sheets, with RAG-coloured ratings
- `control_testing_report.pdf` – one-page summary for stakeholders
- `exception_evidence_log.csv` – one row per exception with the evidence fields (approvers, balance, limit,
  excess over limit, original transaction id, seconds apart) and an open status for owner follow-up
- `summary.json` – machine-readable results

## 6. How to run

```bash
pip install -r requirements.txt
python -m ctengine.main                         # generate 50,000 synthetic transactions and test them
python -m ctengine.main --n 100000 --seed 7     # bigger or different population
python -m ctengine.main --input extract.csv     # test your own extract (same columns)
python -m ctengine.main --db output/txns.db     # also persist the tested population to SQLite
python -m pytest -q                             # unit tests for every control, validation, sampling and ratings
```

Expected input columns: `txn_id, card_id, merchant_id, merchant_category, channel, amount, currency, txn_timestamp,
credit_limit, balance_before, status, initiated_by, approver_1, approver_2`.

## 7. Assumptions and limitations

- All data is **synthetic** and generated with a fixed seed; no real customer or card data is used.
- Exceptions are planted at known rates (≈4% of high-value approvals, 0.8% SoD, 1.2% limit breaches, 250 duplicates)
  so the engine's detection can be checked against ground truth.
- Design attributes come from the control catalogue in `config/controls.json`. In practice they would come from a
  walkthrough with the control owner.
- A declined over-limit transaction is treated as the control **working**, not as an exception.
- Duplicate detection compares each transaction with the one immediately before it in the same card/merchant/amount
  group, so a burst of three charges inside 60 seconds produces two exceptions.

## 8. Project structure

```
ctengine/
  generate_data.py   synthetic population with planted exceptions and data-quality defects
  validation.py      completeness / validity / uniqueness checks, quarantine, reconciliation
  controls.py        SQLite loader, SQL test runner, independent Pandas re-performance
  sampling.py        random, stratified and judgmental sampling
  evaluation.py      design effectiveness, operating effectiveness, control rating
  report.py          Excel (openpyxl) and PDF (ReportLab) report writers
  main.py            end-to-end run / CLI
sql/control_tests.sql   one named query per control
config/controls.json    control catalogue, thresholds, tolerances, sample size
tests/test_controls.py  boundary-value unit tests
```
