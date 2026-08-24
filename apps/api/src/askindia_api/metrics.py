"""Prometheus metrics: RED on the ask endpoints plus the integrity signals the design calls out."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

REQUESTS = Counter("askindia_requests_total", "Answers by outcome", ["status"])
LATENCY = Histogram(
    "askindia_request_seconds",
    "End-to-end latency of one question",
    buckets=(1, 2, 5, 10, 20, 40, 60, 120),
)
ATTEMPTS = Histogram(
    "askindia_sql_attempts", "SQL generation attempts per question", buckets=(1, 2, 3)
)
GUARD_REJECTIONS = Counter(
    "askindia_guard_rejections_total", "Answers rejected by the groundedness guard"
)
RETRIEVAL_DATASET = Counter(
    "askindia_retrieval_top_dataset_total", "Dataset ranked first by retrieval", ["dataset"]
)


def observe_final(final: dict[str, object], seconds: float) -> None:
    REQUESTS.labels(status=str(final.get("status"))).inc()
    LATENCY.observe(seconds)
    attempts = final.get("attempts")
    if isinstance(attempts, int) and attempts > 0:
        ATTEMPTS.observe(attempts)
    guard = final.get("guard")
    if isinstance(guard, dict) and guard.get("passed") is False:
        GUARD_REJECTIONS.inc()
    citation = final.get("citation")
    if isinstance(citation, dict) and citation.get("dataset"):
        RETRIEVAL_DATASET.labels(dataset=str(citation["dataset"])).inc()
