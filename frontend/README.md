# Coverwise policy intelligence

A Next.js App Router frontend for an insurance policy library and retrieval-augmented policy assistant. The UI uses the live API; it does not contain mock policy or answer data.

## Requirements

- Node.js 18.17+ and npm
- The policy API running separately

## Setup

From this directory:

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev
```

The app is available at `http://localhost:8002`. Set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` to the API base URL (default `http://localhost:8001/api/v1`) before starting Next.js. The API must allow browser requests from the frontend origin (CORS).

## API integration

- `GET /policies` with optional `category`, `status` (`active`, `archived`, `expired`, or `upcoming`), `carrier`, and `search` query parameters; paginated responses with an `items` array are decoded
- `POST /policies/upload` as multipart form data (`file` plus optional policy metadata)
- `POST /policies/ingest-sources` to index bundled source documents; the UI reports ingested, skipped, and failed counts, warning on skipped files and showing skipped/failed filenames when provided
- `GET /policies/{id}`, `GET /policies/{id}/file`, and `DELETE /policies/{id}` (archives the policy)
- `POST /search` for matching passages and similarity scores
- `POST /answer` for an answer with cited source passages

The dashboard summarizes the returned policy list. The library filters and search are passed through to `GET /policies`; assistant category, carrier, and policy selections are sent in the JSON `filters` object. Upload accepts PDF and DOCX documents.

Policy details show the policy version and link to its original file. The archive action uses `DELETE /policies/{id}`; the backend retains the policy as archived.

The client accepts the policy list as a JSON array, an `{ items, total, page, page_size }` paginated response, or the older object with a `policies` array. Category choices are collected from the returned policies, including seeded categories.
