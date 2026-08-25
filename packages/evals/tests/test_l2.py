"""The claim generator labels mutations consistently with the verdict bands."""

import random

import yaml

from askindia_agents.graph.claims import Decomposition, judge
from askindia_evals.l2 import CLAIMS_PATH, CLASSES, class_metrics, confusion, predicted_verdict


def test_claim_file_is_well_formed() -> None:
    spec = yaml.safe_load(CLAIMS_PATH.read_text())
    assert len(spec["templated"]) >= 15 and len(spec["unverifiable"]) >= 15
    for item in spec["templated"]:
        assert "{value" in item["template"]


def test_mutation_bands_agree_with_judge() -> None:
    rng = random.Random(3)
    for truth in (94.0, 199812341.0, 2516.2, 65.48):
        supported = truth * rng.uniform(0.97, 1.03)
        misleading = truth * rng.choice([rng.uniform(1.4, 1.7), rng.uniform(0.55, 0.7)])
        contradicted = truth * rng.choice([rng.uniform(3.2, 5.0), rng.uniform(0.1, 0.3)])
        rows = [{"v": truth}]
        assert (
            judge(Decomposition(question="what?", claimed_value=supported), rows).verdict
            == "Supported"
        )
        assert (
            judge(Decomposition(question="what?", claimed_value=misleading), rows).verdict
            == "Misleading"
        )
        assert (
            judge(Decomposition(question="what?", claimed_value=contradicted), rows).verdict
            == "Contradicted"
        )


def test_confusion_and_metrics() -> None:
    records = [
        {"label": "Supported", "predicted": "Supported"},
        {"label": "Supported", "predicted": "Misleading"},
        {"label": "Unverifiable", "predicted": "Unverifiable"},
        {"label": "Unverifiable", "predicted": "Supported"},
    ]
    m = confusion(records)
    assert [m[c][c] for c in CLASSES] == [1, 0, 0, 1]
    metrics = {r["class"]: r for r in class_metrics(m)}
    assert metrics["Unverifiable"]["recall_pct"] == 50.0
    assert metrics["Supported"]["precision_pct"] == 50.0


def test_predicted_verdict_falls_back_to_unverifiable() -> None:
    assert predicted_verdict({"status": "answered", "mode": "question"}) == "Unverifiable"
    assert (
        predicted_verdict(
            {"status": "verdict", "mode": "claim", "verdict": {"verdict": "Misleading"}}
        )
        == "Misleading"
    )
