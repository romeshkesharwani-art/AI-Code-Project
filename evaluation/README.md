# RAG Evaluation Studio

Run this separate Streamlit UI from the project root:

```powershell
.\venv\python.exe -m streamlit run evaluation\app.py
```

## Evaluation inputs

- **Example results** loads illustrative A/B answers and retrieval IDs. The
  example answers are prewritten; they do not call either model. The
- **Upload results CSV** requires `question`, `expected_answer`, `answer_a`, and
  `answer_b`. Optional `relevant_doc_ids`, `retrieved_ids_a` /
  `retrieved_ids_b`, and `retrieved_documents_a` / `retrieved_documents_b`
  provide retrieval labels and passages. List values can be JSON arrays or
  semicolon-delimited text.
- **Call RAG API endpoints** sends each question to both configured endpoints as
  a JSON `POST` with `question`, `relevant_doc_ids`, and a `config` object
  containing the system name, model, embedding model, prompt label, retriever,
  and `top_k`. Responses must be JSON objects with a string `answer` and an
  optional `retrieved_documents` array. Each retrieved document may contain
  `id` and `text` (or `document_id` and `content`). The optional bearer token is
  sent to both endpoints and is not saved in history.

## Metrics and history

Retrieval metrics (Precision@K, Recall@K, MRR, NDCG) require relevant and
retrieved document IDs; stable filenames can be used for reference IDs when
scoring live API results. Answer metrics include BLEU, ROUGE-L, token F1, exact
match, and character-level text similarity. Text similarity is not a semantic
embedding score; the app does not make embedding API calls.

## Automatic A/B decision

Both systems are evaluated on the same question rows. The automatic selection
uses the mean of BLEU/100, ROUGE-L, and token F1 as the answer score. When
relevant-document labels and retrieval metrics are available for both systems,
the composite is 60% answer score and 40% mean Precision@K, Recall@K, MRR, and
NDCG. Without
retrieval labels, the generation score alone is used. A tie is reported without
choosing a winner; if either system fails on any question, no winner is chosen
from the incomplete run. The UI displays the composite and its rule. This is a
reference-metric winner, not a guarantee of semantic correctness or suitability
for a real insurance decision.

Evaluation history is saved locally to `evaluation/results/runs.json` only when
**Save evaluation run** is selected. Saved runs include the questions,
references, returned answers/passages, scores, and configuration. Do not save
sensitive datasets unless local retention is appropriate.

The two additional PDFs in `rag/` are fictional water-backup and cyber-response
endorsement fixtures and are clearly marked as test documents, not valid
insurance policies. The example results dataset adds matching questions,
references, document labels, and contrasting A/B answers for those fixtures.
Use the live endpoint mode after indexing to generate actual model answers.

## Run a live A/B test

1. Start the API and use **Index bundled docs** in the policy UI to index the
   included sources (this requires PostgreSQL/pgvector and the configured
   embedding provider).
2. Open **New evaluation → Call RAG API endpoints** and upload
   `evaluation/sample_results.csv` as the question dataset. Its six questions
   and references are shared across both systems; the two additional PDF
   questions use their stable filenames as relevance labels.
3. Point both system endpoints at
   `http://localhost:8001/api/v1/evaluate`. Choose different answer models,
   prompt instructions, or Top-K values for A and B. Keep the embedding model
   and retriever fixed to the index that is actually stored.
4. Run the evaluation. Each endpoint receives every question, and the dashboard
   shows per-answer outputs/sources, per-query and aggregate metrics, workflow,
   and the automatic composite-score winner (or tie/incomplete result). Save
   the run if it should remain in local history.
