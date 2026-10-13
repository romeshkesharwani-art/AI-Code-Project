import json
import math
import re
from difflib import SequenceMatcher
from typing import Any

from rouge_score import rouge_scorer
from sacrebleu.metrics import BLEU


_ROUGE = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
_BLEU = BLEU(effective_order=True)


def parse_list(value: Any) -> list[Any]:
    """Parse a JSON array or a semicolon/newline-delimited list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if isinstance(value, float) and value != value:
        return []

    text = str(value).strip()
    if not text:
        return []
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return [item.strip() for item in re.split(r"[;\n]", text) if item.strip()]
    if isinstance(decoded, list):
        return decoded
    if isinstance(decoded, dict):
        return [decoded]
    return [str(decoded)]


def document_parts(document: Any) -> tuple[str | None, str]:
    if isinstance(document, dict):
        identifier = next(
            (
                document[key]
                for key in ("id", "document_id", "source_id")
                if document.get(key) is not None and document.get(key) != ""
            ),
            None,
        )
        text = document.get("text") or document.get("content") or document.get("page_content") or ""
        return (str(identifier) if identifier is not None else None, str(text))
    return None, str(document)


def document_identifiers(document: Any) -> set[str]:
    if not isinstance(document, dict):
        return set()
    return {
        str(document[key])
        for key in ("id", "document_id", "source_id", "policy_id", "filename")
        if document.get(key) is not None and document.get(key) != ""
    }


def score_retrieval(
    relevant_ids: list[Any],
    retrieved_documents: list[Any],
    k: int | None = None,
) -> dict[str, float | None]:
    relevant = {
        str(identifier)
        for identifier in relevant_ids
        if identifier is not None and str(identifier)
    }
    if not relevant:
        return {"precision_at_k": None, "recall_at_k": None, "mrr": None, "ndcg": None}
    if not retrieved_documents:
        return {"precision_at_k": 0.0, "recall_at_k": 0.0, "mrr": 0.0, "ndcg": 0.0}

    retrieved_identifiers = [
        document_identifiers(document) for document in retrieved_documents
    ]
    if not any(retrieved_identifiers):
        return {"precision_at_k": None, "recall_at_k": None, "mrr": None, "ndcg": None}

    relevant_ranks: list[int] = []
    found_relevant: set[str] = set()
    seen_documents: set[str] = set()
    for rank, (document, identifiers) in enumerate(
        zip(retrieved_documents, retrieved_identifiers),
        start=1,
    ):
        if isinstance(document, dict):
            document_key = next(
                (
                    str(document[key])
                    for key in ("document_id", "policy_id", "filename", "id")
                    if document.get(key) is not None
                ),
                f"rank:{rank}",
            )
        else:
            document_key = f"rank:{rank}"
        if document_key in seen_documents:
            continue
        seen_documents.add(document_key)
        newly_found = (identifiers & relevant) - found_relevant
        if newly_found:
            relevant_ranks.append(rank)
            found_relevant.update(newly_found)
    precision = len(found_relevant) / (k if k is not None else len(retrieved_documents))
    recall = len(found_relevant) / len(relevant)
    mrr = 1 / relevant_ranks[0] if relevant_ranks else 0.0
    dcg = sum(1 / math.log2(rank + 1) for rank in relevant_ranks)
    ideal_count = min(len(relevant), k if k is not None else len(retrieved_documents))
    ideal_dcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    ndcg = dcg / ideal_dcg if ideal_dcg else 0.0
    return {
        "precision_at_k": precision,
        "recall_at_k": recall,
        "mrr": mrr,
        "ndcg": ndcg,
    }


def score_generation(reference: str, answer: str) -> dict[str, float | None]:
    reference = reference.strip()
    answer = answer.strip()
    if not reference or not answer:
        return {
            "bleu": None,
            "rouge_l": None,
            "token_f1": None,
            "text_similarity": None,
            "exact_match": None,
        }

    reference_tokens = re.findall(r"\w+", reference.casefold())
    answer_tokens = re.findall(r"\w+", answer.casefold())
    reference_counts: dict[str, int] = {}
    answer_counts: dict[str, int] = {}
    for token in reference_tokens:
        reference_counts[token] = reference_counts.get(token, 0) + 1
    for token in answer_tokens:
        answer_counts[token] = answer_counts.get(token, 0) + 1
    overlap = sum(min(count, answer_counts.get(token, 0)) for token, count in reference_counts.items())
    precision = overlap / len(answer_tokens) if answer_tokens else 0.0
    recall = overlap / len(reference_tokens) if reference_tokens else 0.0
    token_f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    rouge_l = _ROUGE.score(reference, answer)["rougeL"].fmeasure
    text_similarity = SequenceMatcher(None, reference.casefold(), answer.casefold()).ratio()

    return {
        "bleu": _BLEU.sentence_score(answer, [reference]).score,
        "rouge_l": rouge_l,
        "token_f1": token_f1,
        "text_similarity": text_similarity,
        "exact_match": float(" ".join(reference_tokens) == " ".join(answer_tokens)),
    }
