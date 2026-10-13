# Insurance Intelligence Hub

Insurance policy management and grounded policy question answering, following
the stack in [architecture.svg](./architecture.svg):

- FastAPI on `http://localhost:8001`
- Next.js on `http://localhost:8002`
- PostgreSQL 16 with pgvector, cosine top-K search
- OpenAI `text-embedding-3-small` embeddings (1536 dimensions) and a configurable
  OpenAI chat model (defaults to `gpt-4o-mini`)

The backend accepts PDF and DOCX policy files, retains their originals, extracts
page/paragraph/table text, creates section-aware overlapping chunks, embeds
them, and stores policy metadata and vectors in `insurance.policy_documents` and
`insurance.policy_chunks` on PostgreSQL. Search applies
policy metadata filters before exact cosine ranking; the answer endpoint
responds only from retrieved passages and abstains when retrieval evidence is
weak. This is an information tool, not an eligibility decision or a substitute
for policy declarations, endorsements, a licensed agent, or claim review.

Customer records are imported into a separate, regular PostgreSQL database
configured with `CUSTOMER_DATABASE_URL`. This customer store uses the built-in
`public.customers` table and does not require pgvector. Re-uploading a
`customer_id` updates that record; new IDs are inserted. The API validates the
complete CSV before saving, so invalid rows do not result in a partial import.

## Prerequisites

- Python 3.11 or newer
- Node.js 20.9 or newer (required by current Next.js)
- Docker Desktop or a local PostgreSQL 16 server with pgvector
- An OpenAI API key

## Configure and run

1. Copy `.env.example` to `.env` and set `OPENAI_API_KEY` plus a strong local
   `POSTGRES_PASSWORD`. Keep `.env` private; it is excluded from source control.
2. Start PostgreSQL from the project root:

   ```powershell
   docker compose up -d postgres
   ```

   Set `PGVECTOR_DATABASE_URL` to match the database credentials, for example
   `postgresql+psycopg://insurance:<POSTGRES_PASSWORD>@localhost:5432/insurance`.
   Set `CUSTOMER_DATABASE_URL` to a regular PostgreSQL connection URL, for
   example `postgresql+psycopg://postgres:<YOUR_POSTGRES_PASSWORD>@localhost:5432/postgres`.
   Customer storage uses this separate connection and does not need pgvector.
   The default SQLite database is for local policy-search smoke tests only.
3. Install Python dependencies in the project virtual environment:

   ```powershell
   .\venv\python.exe -m pip install -r requirements.txt
   ```

4. Apply the initial schema migration:

   ```powershell
   .\venv\python.exe -m alembic upgrade head
   ```

   The FastAPI startup also creates missing tables and enables pgvector, which
   keeps first-run development setup straightforward.
5. Install and run the frontend:

   ```powershell
   Set-Location frontend
   npm install
   Copy-Item .env.example .env.local
   npm run dev
   ```

6. In a second terminal at the project root, start the API:

   ```powershell
   .\venv\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8001
   ```

   The browser UI is at `http://localhost:8002`; API docs are at
   `http://localhost:8001/docs`.

## Load the included insurance sources

The 14 PDF/DOCX source files are retained in `rag/`: 12 supplied insurance
documents and two clearly labeled fictional test endorsements for evaluation.
The test endorsements are not insurance contracts or coverage offers. Start the
API, then call the local-only folder import endpoint to index those files:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8001/api/v1/policies/ingest-sources
```

The endpoint only reads PDF/DOCX files from this project's `rag/` directory.
Completed imports are skipped on subsequent runs; failed imports are reported
and can be retried. Ingestion calls the configured embedding service.

## Upload customer data

Start your local PostgreSQL service and the API. Set `CUSTOMER_DATABASE_URL` in
`.env` to your local PostgreSQL connection (the `postgres` database in the
example above is created by default). The app creates the regular
`public.customers` table on startup. Then upload the supplied CSV:

```powershell
curl.exe -X POST -F "file=@C:\AI\synthetic_insurance_customers_200.csv;type=text/csv" `
  http://localhost:8001/api/v1/customers/upload
```

The response reports the number of rows received, inserted, and updated.
Customer details can be retrieved by ID from
`GET /api/v1/customers/{customer_id}`. The CSV must contain the customer and
policy columns in the supplied dataset; malformed rows or duplicate customer
IDs within one file reject the whole upload. Customer data contains personal
information: keep the API and database on trusted networks and restrict access
to the CSV and database credentials.

## Evaluate and compare RAG runs

The separate Streamlit evaluation app supports retrieval metrics
(Precision@K, Recall@K, MRR, and NDCG), answer metrics (BLEU, ROUGE-L, token F1,
exact match, and character-level similarity), per-question results, a workflow
view, charts, and locally saved run history.

Run it from the project root in a separate terminal:

```powershell
.\venv\python.exe -m streamlit run evaluation\app.py
```

To run a live A/B comparison:

1. Start the API and index the bundled documents. Live comparisons need the
   configured embedding provider and an index containing the test documents.
2. In the evaluation app, select **Call RAG API endpoints** and upload
   `evaluation\sample_results.csv`. It contains six shared questions and
   expected answers, including questions for the two test endorsements.
3. Set both endpoint URLs to `http://localhost:8001/api/v1/evaluate`. Configure
   different chat models, prompts, or Top-K values for A and B. Keep embedding
   model and retriever aligned with the corpus index; alternative embedding
   indexes and retrievers are not implemented.
4. Run the evaluation to see both systems' answers and retrieved passages,
   per-question and aggregate metrics, the end-to-end workflow, and the
   automatically selected result. Save the run to retain it in local history.

The example CSV answers are illustrative and do not call a model. Live model
generation requires a running API and configured provider credentials. The
automatic selection is a reference-metric comparison, not a guarantee of
semantic correctness or suitability for an insurance decision. Retrieval
metrics require relevant-document labels. When labels are complete for both
systems, the composite score weights generation at 60% and retrieval at 40%;
without retrieval labels, it uses the generation score. Incomplete runs and ties
do not produce a winner. Saved local runs are stored in
`evaluation/results/runs.json` when explicitly saved.

## Main API

- `GET /health`, `GET /ready`, `GET /api/v1/policies/dashboard/stats`
- `GET /api/v1/policies` with `category`, `status`, `carrier`, `search`, `page`,
  and `page_size` filters
- `POST /api/v1/policies/upload` multipart `file` and optional `name`, `category`,
  `carrier`, `effective_date`, and `expires_date`
- `GET /api/v1/policies/{id}` and `GET /api/v1/policies/{id}/file`
- `DELETE /api/v1/policies/{id}` archives the record; it does not remove the
  source file or the audit trail
- `GET` or `POST /api/v1/search`; POST accepts
  `{"query":"...","top_k":5,"filters":{"category":"Health"}}`
- `POST /api/v1/answer` accepts the search body and returns an answer, source
  passages, and an `abstained` indicator
- `POST /api/v1/evaluate` runs one evaluation endpoint call. It accepts
  `{"question":"...","relevant_doc_ids":[],"config":{"top_k":5,"model":"gpt-4o-mini","embedding_model":"text-embedding-3-small","retriever":"pgvector cosine","prompt":"..."}}`

The evaluator endpoint can change chat model, prompt instructions, and Top-K.
The diagram indexes one embedding model and uses exact pgvector cosine search;
different embedding models require re-embedding the corpus and are rejected
until that index exists. Alternative retrievers are likewise not implemented.
The evaluation UI's saved local runs remain under `evaluation/results/`.

## Workflow orchestration

The root-level `orchestration/` package provides a small sequential workflow
runner that passes a shared context between steps. Use it to compose future
application workflows without coupling their orchestration to the API or
evaluation UI. Step exceptions propagate to the caller.

The proposed claim workflow is available as a shareable
[SVG diagram](./orchestration/claim-workflow.svg). It is a design only: claim
processing, customer information lookup, and LangGraph integration are not
implemented in this application.

## Tests

```powershell
.\venv\python.exe -m unittest discover -s backend\tests -v
.\venv\python.exe -m unittest discover -s evaluation\tests -v
```

No authentication is included in the supplied architecture. Keep the API and
database on trusted local/development networks; add authentication, authorization,
audit controls, backups, and deployment secrets management before exposing the
service to users or the public internet. Scanned-image OCR, hybrid search,
reranking, background ingestion queues, and server-side evaluation history are
not part of this implementation.
