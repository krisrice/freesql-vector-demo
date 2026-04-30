# Table Install/Reinstall Web App Spec

## Goal

Turn the demo into a try/teach sample app where a user can run the full lab from the browser:

- search the existing vector index
- install the sample table and data when it is missing
- reinstall the sample table and data when they want a clean run
- inspect the generated query vector, row vectors, and similarity scores

The app should still work as a small local lab with one Python process serving both the API and the React UI.

## App Tabs

The web app should use three top-level tabs.

### Search

This is the primary tab and should preserve the current search experience.

Behavior:

- show the semantic search input, result limit selector, and search button
- show the indexed row count from `/api/health`
- run searches against `AUTOMOTIVE_PARTS`
- show part name, part number, category, description, price, and similarity or distance score
- refresh health after install or reinstall completes

If the table is not installed or has fewer than the minimum target rows, this tab should show an **Install Now** button near the status area. The button should start the install flow and keep the user in context while install progress is displayed.

### Install/Reinstall

This tab should perform setup and reset operations from the web app.

Controls:

- **Install Data**: create `AUTOMOTIVE_PARTS` if needed and seed data up to at least 1,000 rows
- **Reinstall Data**: confirm, drop, recreate, and reseed `AUTOMOTIVE_PARTS`

Behavior:

- show current install state: not installed, installing, installed, reinstalling, failed
- show embedding generation progress and row insert progress as separate counters, with a minimum target of 1,000 rows
- show the current step, such as connecting, creating table, generating embeddings, inserting rows, complete
- show elapsed install time so users can tell the model download/vectorizing work is still active
- disable install/reinstall controls while a job is active
- require confirmation before reinstalling because it deletes and recreates the sample table
- report final row count and any error message

The embedding model can take time to download and run. Progress should make vectorizing visible before database inserts happen so users do not think the app is hung.

### Details

This tab should teach what the search is doing.

It should use the same search controls as the Search tab, but expose vector details for the query and returned rows.

Behavior:

- generate and display the query embedding used for the search
- show each returned row with its generated embedding vector
- show the similarity or distance score for each returned row
- preserve the normal result fields: part name, part number, category, description, and price
- make vectors readable without overwhelming the page

Recommended vector display:

- show vector metadata: dimension count, vector type, and normalization/quantization note
- show the first 24 to 32 vector values inline
- provide an expand control to view the full vector
- label the score clearly as cosine distance or similarity, matching the SQL

## API Contract

### `GET /api/health`

Existing endpoint. It should continue returning model and table status.

Recommended response:

```json
{
  "ok": true,
  "model": "all-MiniLM-L6-v2",
  "embedding_dims": 384,
  "embedding_vector_type": "int8",
  "table_name": "AUTOMOTIVE_PARTS",
  "installed": true,
  "part_count": 1000,
  "target_count": 1000
}
```

If the table is missing, return a successful health payload with `installed: false` instead of treating the app as broken.

### `POST /api/admin/install`

Start an install or reinstall job.

Request:

```json
{
  "reset": false
}
```

Use `reset: true` for reinstall.

Recommended response:

```json
{
  "ok": true,
  "job_id": "install-20260430-132200",
  "status": "queued"
}
```

The endpoint should reject a new install if one is already running.

### `GET /api/admin/install-status`

Return install progress.

Recommended response:

```json
{
  "ok": true,
  "job_id": "install-20260430-132200",
  "status": "running",
  "step": "generating embeddings",
  "embeddings_generated": 320,
  "rows_inserted": 320,
  "target_count": 1000,
  "elapsed_seconds": 12.4,
  "message": "Generated embeddings for 320 of 1000 rows"
}
```

Final response:

```json
{
  "ok": true,
  "job_id": "install-20260430-132200",
  "status": "complete",
  "step": "complete",
  "embeddings_generated": 1000,
  "rows_inserted": 1000,
  "target_count": 1000,
  "part_count": 1000,
  "elapsed_seconds": 30.7
}
```

Failed response:

```json
{
  "ok": false,
  "job_id": "install-20260430-132200",
  "status": "failed",
  "step": "inserting rows",
  "error": "Oracle error message"
}
```

### `POST /api/search`

Existing search endpoint. Keep the default response compact for the Search tab.

Add an optional details mode:

```json
{
  "query": "quiet brake pads for front wheels",
  "limit": 5,
  "include_vectors": true
}
```

When `include_vectors` is true, return:

- the query vector
- each row vector
- score metadata

Recommended response shape:

```json
{
  "query": "quiet brake pads for front wheels",
  "score_type": "cosine_distance",
  "query_vector": [12, -4, 31],
  "results": [
    {
      "id": 1,
      "part_number": "BRK-PAD-CER-F",
      "name": "Ceramic Front Brake Pad Set",
      "category": "Brakes",
      "description": "Low dust ceramic brake pads for front axle service with quiet stopping performance.",
      "unit_price": 64.5,
      "distance": 0.1234,
      "embedding": [10, -6, 29]
    }
  ]
}
```

## Implementation Notes

- Reuse `initialize_database(reset=...)` for install and reinstall.
- Refactor seeding so progress can be updated during embedding generation and insert batches.
- Keep the table target at `INVENTORY_TARGET`, with a minimum of 1,000 rows.
- Run install/reinstall work in a background thread so the HTTP request can return immediately and the UI can poll status.
- Store install status in process memory for the local lab. A persistent job system is not required for this sample.
- Use one active install job at a time.
- Reinstall should call the existing drop/recreate path and then seed rows.
- Install status should distinguish `embeddings_generated` from `rows_inserted`; vectorizing progress should advance as soon as each embedding batch finishes.
- Search should handle missing-table errors by returning a clear install-needed response instead of a raw Oracle exception.

## Safety

This is a local lab feature. Reinstall intentionally drops and recreates `AUTOMOTIVE_PARTS`.

Do not expose the install/reinstall endpoints on a public deployment without authentication and authorization.

## Try/Teach Gaps To Include

For a sample app whose goal is to help users try and learn Oracle vector search, the following additions would make the experience stronger:

- a short explanation in the Details tab of why lower cosine distance means a closer semantic match
- a visible SQL panel showing the exact `vector_distance` query used for the current search
- example queries users can click to compare symptom-based, part-name, and vehicle-fit searches
- a dataset summary showing categories, row count, model name, vector dimensions, and vector type
- clear empty/error states for missing credentials, missing table, failed model download, and Oracle connection errors
- a reset-safe warning that explains only the demo table is affected
- optional timing metrics for embedding generation, insert time, and search latency
- a note that embeddings are generated locally with `all-MiniLM-L6-v2` and stored as `VECTOR(384, int8)`

## Acceptance Criteria

- Search tab works as it does today when data is installed.
- Search tab shows **Install Now** when the table is missing or below the minimum row target.
- Install/Reinstall tab can install at least 1,000 rows from the browser.
- Reinstall requires confirmation and rebuilds the table from scratch.
- Install progress shows current step, embeddings generated, rows inserted, and elapsed time.
- Details tab runs searches and shows query vector, returned row vectors, and scores.
- Health reports table status without failing when the table is missing.
- Missing table and install failures produce readable UI errors.
