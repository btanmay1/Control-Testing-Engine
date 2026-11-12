"""Design effectiveness, operating effectiveness and overall control rating."""
from __future__ import annotations

DESIGN_LABELS = {
    "owner_assigned": "Control owner assigned",
    "procedure_documented": "Procedure documented",
    "threshold_defined": "Threshold / precision defined",
    "evidence_retained": "Evidence of performance retained",
    "addresses_risk": "Control addresses the stated risk",
    "timely_execution": "Executed in time to prevent/detect",
}


def design_effectiveness(ctl: dict) -> dict:
    attrs = ctl["design_attributes"]
    gaps = [DESIGN_LABELS[k] for k, ok in attrs.items() if not ok]
    if not gaps:
        verdict = "Effective"
    elif "addresses_risk" in [k for k, ok in attrs.items() if not ok]:
        verdict = "Ineffective"
    else:
        verdict = "Needs Improvement"
    return {"design_verdict": verdict, "design_score": f"{len(attrs) - len(gaps)}/{len(attrs)}",
            "design_gaps": "; ".join(gaps) if gaps else "None"}


def operating_effectiveness(sample_deviations: int, allowable: int, population_rate: float, tolerable_rate: float) -> str:
    if sample_deviations <= allowable and population_rate <= tolerable_rate:
        return "Effective"
    if population_rate <= 2 * tolerable_rate:
        return "Needs Improvement"
    return "Ineffective"


def overall_rating(design: str, operating: str) -> str:
    if design == "Ineffective" or operating == "Ineffective":
        return "Ineffective"
    if design == "Effective" and operating == "Effective":
        return "Effective"
    return "Partially Effective"
