import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pandas as pd
import streamlit as st

from evaluation.history import load_runs, save_run
from evaluation.comparison import compare_run
from evaluation.metrics import document_parts, parse_list, score_generation, score_retrieval


SAMPLE_PATH = Path(__file__).resolve().parent / "sample_results.csv"
METRIC_LABELS = {
    "precision_at_k": "Precision@K",
    "recall_at_k": "Recall@K",
    "mrr": "MRR",
    "ndcg": "NDCG",
    "bleu": "BLEU (0–100)",
    "rouge_l": "ROUGE-L",
    "token_f1": "Token F1",
    "text_similarity": "Text similarity",
    "exact_match": "Exact match",
}
st.set_page_config(page_title="RAG Evaluation Studio", page_icon="📊", layout="wide")
st.markdown(
    """
    <style>
    .stApp { background: #f5f7fb; }
    .block-container { max-width: 1440px; padding-top: 2rem; padding-bottom: 3rem; }
    [data-testid="stMetric"] {
        background: white; border: 1px solid #e7eaf1; padding: 1rem 1.1rem;
        border-radius: 14px;
    }
    div[data-testid="stForm"] {
        background: white; border: 1px solid #e7eaf1;
        border-radius: 14px; padding: 1.1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.sidebar.title("Evaluation Studio")
st.sidebar.caption("RAG quality, one run at a time.")
page = st.sidebar.radio("Workspace", ["Overview", "New evaluation", "Run history"])
st.sidebar.divider()
st.sidebar.caption("Runs are stored locally in evaluation/results/runs.json.")


def average_metric(rows: list[dict[str, Any]], metric: str) -> float | None:
    values = [
        row["metrics"].get(metric)
        for row in rows
        if row.get("metrics") and row["metrics"].get(metric) is not None
    ]
    return sum(values) / len(values) if values else None


def parse_documents(row: dict[str, Any], system_key: str) -> list[dict[str, Any]]:
    raw_documents = parse_list(row.get(f"retrieved_documents_{system_key}"))
    raw_ids = parse_list(row.get(f"retrieved_ids_{system_key}"))
    documents: list[dict[str, Any]] = []
    for index, raw_document in enumerate(raw_documents):
        identifier, text = document_parts(raw_document)
        if identifier is None and index < len(raw_ids):
            identifier = str(raw_ids[index])
        document = raw_document.copy() if isinstance(raw_document, dict) else {}
        document.update({"id": identifier, "text": text})
        documents.append(document)
    if not documents:
        documents = [{"id": str(identifier), "text": ""} for identifier in raw_ids]
    return documents


def validate_dataset(frame: pd.DataFrame, require_results: bool) -> None:
    required = {"question", "expected_answer"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Dataset is missing required column(s): {', '.join(sorted(missing))}.")
    if frame.empty:
        raise ValueError("The uploaded dataset has no rows.")
    if (
        frame["question"].astype(str).str.strip().eq("").any()
        or frame["expected_answer"].astype(str).str.strip().eq("").any()
    ):
        raise ValueError("Every dataset row must have both a question and an expected_answer.")
    if require_results:
        missing_outputs = {
            f"answer_{system}" for system in ("a", "b")
        } - set(frame.columns)
        if missing_outputs:
            raise ValueError(
                "Results CSV is missing required output column(s): "
                f"{', '.join(sorted(missing_outputs))}."
            )


def endpoint_result(
    endpoint: str,
    token: str,
    question: str,
    relevant_ids: list[Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = httpx.post(
        endpoint,
        json={
            "question": question,
            "relevant_doc_ids": relevant_ids,
            "config": config,
        },
        headers=headers,
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("The RAG endpoint must return a JSON object.")
    answer = payload.get("answer", payload.get("generated_answer"))
    if not isinstance(answer, str):
        raise ValueError("The RAG endpoint response must include a string 'answer'.")
    raw_documents = payload.get("retrieved_documents", payload.get("retrieved_contexts", []))
    if not isinstance(raw_documents, list):
        raise ValueError("'retrieved_documents' must be a JSON array.")
    documents = []
    for document in raw_documents[: config["top_k"]]:
        identifier, text = document_parts(document)
        normalized = document.copy() if isinstance(document, dict) else {}
        normalized.update({"id": identifier, "text": text})
        documents.append(normalized)
    return {"answer": answer, "retrieved_documents": documents, "error": None}


def build_run(
    dataset: pd.DataFrame,
    configs: dict[str, dict[str, Any]],
    mode: str,
    endpoints: dict[str, str] | None = None,
    token: str = "",
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    progress = st.progress(0, text="Starting evaluation…")
    total = len(dataset) * (len(configs) if mode == "api" else 0)
    completed = 0
    for row_index, raw_row in dataset.iterrows():
        source = raw_row.to_dict()
        question = str(source["question"]).strip()
        reference = str(source["expected_answer"]).strip()
        relevant_ids = parse_list(source.get("relevant_doc_ids"))
        systems: dict[str, Any] = {}
        for system_key, config in configs.items():
            if mode == "api":
                completed += 1
                progress.progress(
                    completed / total,
                    text=f"Evaluating row {row_index + 1} of {len(dataset)} · System {system_key.upper()}",
                )
                try:
                    output = endpoint_result(
                        endpoints[system_key], token, question, relevant_ids, config
                    )
                except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
                    output = {
                        "answer": "",
                        "retrieved_documents": [],
                        "error": f"{type(error).__name__}: {error}",
                    }
            else:
                output = {
                    "answer": str(source.get(f"answer_{system_key}") or ""),
                    "retrieved_documents": parse_documents(source, system_key),
                    "error": None,
                }
                output["retrieved_documents"] = output["retrieved_documents"][: config["top_k"]]
            output["metrics"] = {
                **score_generation(reference, output["answer"]),
                **score_retrieval(
                    relevant_ids,
                    output["retrieved_documents"],
                    k=config["top_k"],
                ),
            }
            systems[system_key] = output
        rows.append(
            {
                "question": question,
                "expected_answer": reference,
                "relevant_doc_ids": [str(item) for item in relevant_ids],
                "systems": systems,
            }
        )
    progress.empty()
    return {
        "id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_name": st.session_state.get("dataset_name", "Uploaded dataset"),
        "mode": mode,
        "configs": configs,
        "rows": rows,
    }


def metric_summary(run: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    return {
        system: {
            metric: average_metric(
                [
                    row["systems"][system]
                    for row in run["rows"]
                    if system in row.get("systems", {})
                    and not row["systems"][system].get("error")
                ],
                metric,
            )
            for metric in METRIC_LABELS
        }
        for system in run["configs"]
    }


def show_workflow() -> None:
    st.markdown("#### Evaluation workflow")
    st.graphviz_chart(
        """
        digraph {
          rankdir=TB;
          node [shape=box style="rounded,filled" fillcolor="#ffffff" color="#dbe2ef" fontname="Arial"];
          question [label="Same test question"];
          retrieval_a [label="A · Retrieve top-K"];
          retrieval_b [label="B · Retrieve top-K"];
          answer_a [label="A · Generate answer"];
          answer_b [label="B · Generate answer"];
          score_a [label="A · Score retrieval + answer"];
          score_b [label="B · Score retrieval + answer"];
          compare [label="Weighted A/B score"];
          winner [label="Automatic winner or tie"];
          question -> retrieval_a -> answer_a -> score_a;
          question -> retrieval_b -> answer_b -> score_b;
          score_a -> compare;
          score_b -> compare;
          compare -> winner;
        }
        """,
        width="stretch",
    )


def show_run(run: dict[str, Any]) -> None:
    summary = metric_summary(run)
    comparison_result = compare_run(run)
    st.subheader("Run dashboard")
    left, right, count = st.columns(3)
    left.metric("Test questions", len(run["rows"]))
    right.metric("Systems compared", len(run["configs"]))
    failed = sum(
        bool(output.get("error"))
        for row in run["rows"]
        for output in row.get("systems", {}).values()
    )
    count.metric("Endpoint errors", failed)
    st.markdown("##### Automatic A/B decision")
    if comparison_result["status"] == "winner":
        winner_key = comparison_result["winner"]
        winner_config = run["configs"][winner_key]
        st.success(
            f"**{winner_config['name']}** "
            f"({winner_config['model']}, Top-K {winner_config['top_k']}) scored highest "
            f"({comparison_result['scores'][winner_key]:.3f}/1.000) across "
            f"{comparison_result['questions_scored']} shared questions."
        )
    elif comparison_result["status"] == "tie":
        st.info(comparison_result["reason"])
    elif comparison_result["status"] == "incomplete":
        st.warning(comparison_result["reason"])
    else:
        st.info(comparison_result["reason"])
    if comparison_result.get("scores"):
        decision_rows = [
            {
                "System": run["configs"][system]["name"],
                "LLM": run["configs"][system]["model"],
                "Retriever": run["configs"][system]["retriever"],
                "Top-K": run["configs"][system]["top_k"],
                "Composite score / 1.000": score,
                "Answer score / 1.000": comparison_result["generation_scores"][system],
                "Retrieval score / 1.000": comparison_result["retrieval_scores"][system],
            }
            for system, score in comparison_result["scores"].items()
        ]
        st.dataframe(pd.DataFrame(decision_rows), hide_index=True, width="stretch")
    st.caption(
        "Decision rule: average of BLEU/100, ROUGE-L, and token F1 for answer quality. "
        "When relevant document labels exist for both systems, the final score weights "
        "generation 60% and retrieval Precision@K/Recall@K/MRR/NDCG 40%. The selected system is the "
        "winner on these reference-based metrics, not a human or semantic-accuracy guarantee."
    )

    retrieval_metrics = ["precision_at_k", "recall_at_k", "mrr", "ndcg"]
    generation_metrics = ["bleu", "rouge_l", "token_f1", "text_similarity", "exact_match"]
    col_retrieval, col_generation = st.columns(2)
    with col_retrieval:
        st.markdown("##### Retrieval")
        available = [
            metric
            for metric in retrieval_metrics
            if any(values[metric] is not None for values in summary.values())
        ]
        if available:
            tabs = st.tabs([METRIC_LABELS[metric] for metric in available])
            for tab, metric in zip(tabs, available):
                with tab:
                    chart_data = pd.DataFrame(
                        [
                            {
                                "System": run["configs"][system]["name"],
                                "Score": values[metric],
                            }
                            for system, values in summary.items()
                            if values[metric] is not None
                        ]
                    ).set_index("System")
                    st.bar_chart(chart_data, y="Score", width="stretch")
        else:
            st.info("Add relevant_doc_ids and retrieved document IDs to calculate retrieval metrics.")
    with col_generation:
        st.markdown("##### Answer quality")
        available = [
            metric
            for metric in generation_metrics
            if any(values[metric] is not None for values in summary.values())
        ]
        if available:
            tabs = st.tabs([METRIC_LABELS[metric] for metric in available])
            for tab, metric in zip(tabs, available):
                with tab:
                    chart_data = pd.DataFrame(
                        [
                            {
                                "System": run["configs"][system]["name"],
                                "Score": values[metric],
                            }
                            for system, values in summary.items()
                            if values[metric] is not None
                        ]
                    ).set_index("System")
                    st.bar_chart(chart_data, y="Score", width="stretch")
        else:
            st.info("Add generated answers and expected_answer values to calculate generation metrics.")
    st.caption(
        "BLEU is scaled 0–100; other displayed metrics are 0–1. "
        "Text similarity is character-level, not a semantic embedding score. "
        "Retrieval scores require relevant_doc_ids and retrieved document IDs."
    )

    st.markdown("##### A/B metric comparison")
    if len(summary) >= 2:
        system_a, system_b = list(summary)[:2]
        comparison = []
        for metric, label in METRIC_LABELS.items():
            a_score = summary[system_a][metric]
            b_score = summary[system_b][metric]
            if a_score is None and b_score is None:
                continue
            comparison.append(
                {
                    "Metric": label,
                    "System A": a_score,
                    "System B": b_score,
                    "Delta (B − A)": b_score - a_score
                    if a_score is not None and b_score is not None
                    else None,
                }
            )
        if comparison:
            st.dataframe(pd.DataFrame(comparison), hide_index=True, width="stretch")

    show_workflow()
    st.markdown("#### Query-level results")
    if not run["rows"]:
        st.info("This evaluation run has no query rows.")
        return
    labels = [
        f"{index + 1}. {row['question'][:100]}"
        for index, row in enumerate(run["rows"])
    ]
    selected = st.selectbox("Choose a question", range(len(labels)), format_func=lambda i: labels[i])
    query = run["rows"][selected]
    st.markdown(f"**Question:** {query['question']}")
    st.markdown(f"**Expected answer:** {query['expected_answer']}")
    for system_key, output in query["systems"].items():
        config = run["configs"][system_key]
        with st.expander(f"System {system_key.upper()} · {config['name']}", expanded=True):
            if output.get("error"):
                st.error(output["error"])
            st.markdown(f"**Generated answer**\n\n{output['answer'] or 'No answer returned.'}")
            metrics = output["metrics"]
            metric_cols = st.columns(4)
            for index, metric in enumerate(
                ["recall_at_k", "mrr", "bleu", "rouge_l"]
            ):
                value = metrics.get(metric)
                metric_cols[index].metric(
                    METRIC_LABELS[metric],
                    f"{value:.3f}" if value is not None else "N/A",
                )
            documents = output.get("retrieved_documents", [])
            st.markdown(f"**Retrieved documents ({len(documents)})**")
            if documents:
                for rank, document in enumerate(documents, start=1):
                    identifier, text = document_parts(document)
                    title = f"{rank}. {identifier or 'No document ID'}"
                    with st.container(border=True):
                        st.caption(title)
                        st.write(text or "No passage text supplied.")
            else:
                st.caption("No retrieved documents returned.")


st.title("RAG Evaluation Studio")
st.caption("A clear workspace to test retrieval, answers, and configuration changes side by side.")

if page == "Overview":
    st.markdown(
        "Upload a test set, compare two RAG configurations, review scores per query, "
        "and keep a local history of evaluation runs."
    )
    try:
        runs = load_runs()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        st.error(f"Could not read saved run history: {error}")
        runs = []
    latest = runs[0] if runs else None
    columns = st.columns(3)
    columns[0].metric("Saved runs", len(runs))
    columns[1].metric(
        "Latest test questions", len(latest["rows"]) if latest else 0
    )
    columns[2].metric(
        "Latest run", latest["created_at"][:10] if latest else "—"
    )
    show_workflow()
    st.info(
        "No RAG backend is bundled in this repository yet. Start with the included "
        "example results, upload a results CSV, or connect two compatible HTTP endpoints."
    )
    if latest:
        st.subheader("Latest saved run")
        show_run(latest)

elif page == "New evaluation":
    mode = st.radio(
        "How will this run get its answers?",
        ["Example results", "Upload results CSV", "Call RAG API endpoints"],
        horizontal=True,
    )
    dataset: pd.DataFrame | None = None
    if mode == "Example results":
        dataset = pd.read_csv(SAMPLE_PATH, keep_default_na=False)
        dataset_name = "Illustrative insurance examples"
        st.info(
            "Example answers and retrieved results are prewritten demonstrations, not live "
            "model outputs. Use “Call RAG API endpoints” to generate answers from both systems."
        )
    elif mode == "Upload results CSV":
        uploaded = st.file_uploader(
            "Upload results CSV",
            type=["csv"],
            help=(
                "Required columns: question, expected_answer, answer_a, answer_b. "
                "Optional retrieval columns: relevant_doc_ids, retrieved_ids_a/b, "
                "retrieved_documents_a/b."
            ),
        )
        if uploaded:
            try:
                dataset = pd.read_csv(uploaded, keep_default_na=False)
                validate_dataset(dataset, require_results=True)
                dataset_name = uploaded.name
            except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as error:
                st.error(f"Could not use this CSV: {error}")
    else:
        uploaded = st.file_uploader(
            "Upload question dataset CSV",
            type=["csv"],
            help="Required columns: question, expected_answer. Optional: relevant_doc_ids.",
        )
        if uploaded:
            try:
                dataset = pd.read_csv(uploaded, keep_default_na=False)
                validate_dataset(dataset, require_results=False)
                dataset_name = uploaded.name
            except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as error:
                st.error(f"Could not use this CSV: {error}")

    st.markdown("#### Compare configurations")
    system_columns = st.columns(2)
    configs: dict[str, dict[str, Any]] = {}
    endpoints: dict[str, str] = {}
    with system_columns[0]:
        st.markdown("**System A**")
        name_a = st.text_input("Name", "Baseline", key="name_a")
        model_a = st.text_input("Answer model", "gpt-4o-mini", key="model_a")
        embedding_a = st.text_input(
            "Indexed embedding model",
            "text-embedding-3-small",
            key="embedding_a",
            disabled=True,
        )
        prompt_a = st.text_area(
            "Additional prompt instructions",
            "",
            max_chars=4000,
            key="prompt_a",
            help="Optional experiment instructions; system grounding and safety rules remain enforced.",
        )
        retriever_a = "pgvector cosine"
        st.caption("Retriever: exact pgvector cosine (the only indexed retriever in this deployment).")
        top_k_a = st.slider("Top-K", 1, 10, 3, key="top_k_a")
        endpoint_a = ""
        if mode == "Call RAG API endpoints":
            endpoint_a = st.text_input("System A endpoint", "http://localhost:8001/api/v1/evaluate")
        configs["a"] = {
            "name": name_a,
            "model": model_a,
            "embedding_model": embedding_a,
            "prompt": prompt_a,
            "retriever": retriever_a,
            "top_k": top_k_a,
        }
        endpoints["a"] = endpoint_a
    with system_columns[1]:
        st.markdown("**System B**")
        name_b = st.text_input("Name", "Experiment", key="name_b")
        model_b = st.text_input("Answer model", "gpt-4o-mini", key="model_b")
        embedding_b = st.text_input(
            "Indexed embedding model",
            "text-embedding-3-small",
            key="embedding_b",
            disabled=True,
        )
        prompt_b = st.text_area(
            "Additional prompt instructions",
            "",
            max_chars=4000,
            key="prompt_b",
            help="Optional experiment instructions; system grounding and safety rules remain enforced.",
        )
        retriever_b = "pgvector cosine"
        st.caption("Retriever: exact pgvector cosine (the only indexed retriever in this deployment).")
        top_k_b = st.slider("Top-K", 1, 10, 5, key="top_k_b")
        endpoint_b = ""
        if mode == "Call RAG API endpoints":
            endpoint_b = st.text_input("System B endpoint", "http://localhost:8001/api/v1/evaluate")
        configs["b"] = {
            "name": name_b,
            "model": model_b,
            "embedding_model": embedding_b,
            "prompt": prompt_b,
            "retriever": retriever_b,
            "top_k": top_k_b,
        }
        endpoints["b"] = endpoint_b

    token = ""
    if mode == "Call RAG API endpoints":
        token = st.text_input(
            "Optional API bearer token",
            type="password",
            help="Sent to both endpoints; never saved with evaluation history.",
        ).strip()
        st.caption(
            "Each endpoint receives POST JSON with question, relevant_doc_ids, and config. "
            "Return JSON with answer and retrieved_documents (each document may include id and text)."
        )
    if dataset is not None:
        st.caption(f"Loaded {len(dataset)} test question(s) from {dataset_name}.")
    start = st.button(
        "Run evaluation",
        type="primary",
        disabled=dataset is None,
        width="stretch",
    )
    if start and dataset is not None:
        try:
            validate_dataset(dataset, require_results=mode == "Upload results CSV")
            st.session_state.dataset_name = dataset_name
            run = build_run(
                dataset,
                configs,
                "api" if mode == "Call RAG API endpoints" else "uploaded",
                endpoints if mode == "Call RAG API endpoints" else None,
                token,
            )
            st.session_state.current_run = run
            st.success("Evaluation finished. Review the dashboard, then save the run below.")
        except (ValueError, OSError) as error:
            st.error(f"Could not run evaluation: {error}")
    if st.session_state.get("current_run"):
        run = st.session_state.current_run
        show_run(run)
        if st.button("Save evaluation run", type="primary"):
            try:
                save_run(run)
                st.session_state.current_run = None
                st.success("Run saved locally.")
                st.rerun()
            except (OSError, ValueError, json.JSONDecodeError) as error:
                st.error(f"Could not save evaluation run: {error}")

else:
    st.subheader("Saved evaluation runs")
    try:
        runs = load_runs()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        st.error(f"Could not read saved run history: {error}")
        runs = []
    if not runs:
        st.info("No saved runs yet. Start an evaluation to build your comparison history.")
    else:
        run_options = {
            f"{run['created_at'][:19].replace('T', ' ')} · {run['dataset_name']} · "
            f"{len(run['rows'])} questions · {run['id'][:8]}": run
            for run in runs
        }
        selected_label = st.selectbox("Select a saved run", list(run_options))
        selected_run = run_options[selected_label]
        show_run(selected_run)
        if len(runs) > 1:
            other_labels = [label for label in run_options if label != selected_label]
            comparison_label = st.selectbox("Compare with another saved run", other_labels)
            other_run = run_options[comparison_label]
            st.markdown("#### Run-to-run comparison")
            first_summary = metric_summary(selected_run)
            second_summary = metric_summary(other_run)
            comparison_rows = []
            for system_key, first_metrics in first_summary.items():
                if system_key not in second_summary:
                    continue
                first_name = selected_run["configs"][system_key]["name"]
                second_name = other_run["configs"][system_key]["name"]
                for metric, label in METRIC_LABELS.items():
                    first_value = first_metrics[metric]
                    second_value = second_summary[system_key][metric]
                    if first_value is None and second_value is None:
                        continue
                    comparison_rows.append(
                        {
                            "System": (
                                f"{system_key.upper()}: {first_name} → {second_name}"
                            ),
                            "Metric": label,
                            "Selected run": first_value,
                            "Compared run": second_value,
                            "Delta (compared − selected)": (
                                second_value - first_value
                                if first_value is not None and second_value is not None
                                else None
                            ),
                        }
                    )
            if comparison_rows:
                st.dataframe(
                    pd.DataFrame(comparison_rows),
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info("No matching system slots and comparable metrics were found.")
