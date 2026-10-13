from typing import Any


GENERATION_METRICS = ("bleu", "rouge_l", "token_f1")
RETRIEVAL_METRICS = ("precision_at_k", "recall_at_k", "mrr", "ndcg")
GENERATION_WEIGHT = 0.6
RETRIEVAL_WEIGHT = 0.4


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _metric_mean(outputs: list[dict[str, Any]], metric: str) -> float | None:
    values = [
        float(value)
        for output in outputs
        if (value := output.get("metrics", {}).get(metric)) is not None
    ]
    return _mean(values)


def compare_run(run: dict[str, Any]) -> dict[str, Any]:
    systems = list(run.get("configs", {}))
    if len(systems) != 2:
        return {"status": "unavailable", "reason": "Exactly two systems are required."}
    baseline_embedding = run["configs"][systems[0]].get("embedding_model")
    if any(
        run["configs"][system].get("embedding_model") != baseline_embedding
        for system in systems[1:]
    ):
        return {
            "status": "unavailable",
            "reason": "Embedding configurations differ; the source corpus must be separately indexed for each embedding model.",
        }

    evaluated_rows: dict[str, list[dict[str, Any]]] = {system: [] for system in systems}
    failed_rows = 0
    for row in run.get("rows", []):
        outputs = row.get("systems", {})
        if any(system not in outputs or outputs[system].get("error") for system in systems):
            failed_rows += 1
            continue
        for system in systems:
            evaluated_rows[system].append(outputs[system])

    if failed_rows:
        return {
            "status": "incomplete",
            "reason": (
                f"{failed_rows} shared question(s) failed for at least one system. "
                "Fix endpoint errors and rerun so both systems are scored on the same questions."
            ),
            "failed_questions": failed_rows,
        }
    if not run.get("rows"):
        return {"status": "unavailable", "reason": "The run contains no questions."}

    summaries: dict[str, dict[str, float | None]] = {}
    for system, outputs in evaluated_rows.items():
        metrics: dict[str, float | None] = {}
        for metric in (*GENERATION_METRICS, *RETRIEVAL_METRICS):
            metrics[metric] = _metric_mean(outputs, metric)
        summaries[system] = metrics

    generation_available = all(
        output.get("metrics", {}).get(metric) is not None
        for outputs in evaluated_rows.values()
        for output in outputs
        for metric in GENERATION_METRICS
    )
    if not generation_available:
        return {
            "status": "unavailable",
            "reason": (
                "Both systems need a generated answer and reference score for every shared "
                "question before an automatic winner can be selected."
            ),
            "systems": summaries,
        }
    retrieval_available = all(
        output.get("metrics", {}).get(metric) is not None
        for outputs in evaluated_rows.values()
        for output in outputs
        for metric in RETRIEVAL_METRICS
    )

    scores: dict[str, float] = {}
    generation_scores: dict[str, float] = {}
    retrieval_scores: dict[str, float | None] = {}
    for system in systems:
        bleu = summaries[system]["bleu"]
        rouge_l = summaries[system]["rouge_l"]
        token_f1 = summaries[system]["token_f1"]
        if bleu is None or rouge_l is None or token_f1 is None:
            raise RuntimeError("Generation metrics were incomplete after validation.")
        generation_score = _mean(
            [
                bleu / 100,
                rouge_l,
                token_f1,
            ]
        )
        if generation_score is None:
            raise RuntimeError("The generation comparison score could not be calculated.")
        generation_scores[system] = generation_score
        if retrieval_available:
            retrieval_values = [
                summaries[system][metric] for metric in RETRIEVAL_METRICS
            ]
            if any(value is None for value in retrieval_values):
                raise RuntimeError("The retrieval comparison score could not be calculated.")
            retrieval_score = _mean(
                [float(value) for value in retrieval_values if value is not None]
            )
            retrieval_scores[system] = retrieval_score
            scores[system] = (
                GENERATION_WEIGHT * generation_score
                + RETRIEVAL_WEIGHT * retrieval_score
            )
        else:
            retrieval_scores[system] = None
            scores[system] = generation_score

    system_a, system_b = systems
    if abs(scores[system_a] - scores[system_b]) < 1e-9:
        winner = None
        status = "tie"
        reason = "The composite scores are tied; no winner is selected."
    else:
        winner = max(scores, key=scores.__getitem__)
        status = "winner"
        reason = (
            "Winner selected by the composite reference-based score."
            if retrieval_available
            else (
                "Winner selected by generation metrics; complete retrieval labels and results "
                "were unavailable for every shared question."
            )
        )
    return {
        "status": status,
        "winner": winner,
        "scores": scores,
        "generation_scores": generation_scores,
        "retrieval_scores": retrieval_scores,
        "systems": summaries,
        "retrieval_included": retrieval_available,
        "weights": (
            {"generation": GENERATION_WEIGHT, "retrieval": RETRIEVAL_WEIGHT}
            if retrieval_available
            else {"generation": 1.0, "retrieval": 0.0}
        ),
        "reason": reason,
        "questions_scored": len(run["rows"]),
    }
