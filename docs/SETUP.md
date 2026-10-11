# Setup Guide

[Back to README](../README.md) | [API guide](API.md)

## Installation and demo preparation

Run commands from the repository root. The verified development environment uses Python **3.14.6**, PostgreSQL **16** through Docker Compose, and the dependency versions in `requirements-tested.txt`. Docker must be running. A Gemini API key with access to the configured models is needed for live generation. The application assumes a free-tier project when recording provider cost.

### 1. Install and configure

On a fresh checkout:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -c requirements-tested.txt
```

Create `app/.env` from the root `.env.example` **only if it does not already exist**. Existing users should keep their current file. Settings load `app/.env`; a root `.env` is not the settings file.

Set `DATABASE_URL` for the database configured in `docker-compose.yml`, and add `GEMINI_API_KEY` locally. The example contains a database-password placeholder and a blank key. Do not commit the completed file. Models are constants in the vision and embedding modules, not environment options.

The application settings are `APP_NAME`, `ENVIRONMENT`, `DATABASE_URL`, `GEMINI_API_KEY`, `AI_BUDGET_USD`, `AI_MAX_CALLS`, `VISION_CONFIDENCE_THRESHOLD`, and `SIMILARITY_THRESHOLD`. Defaults are a 200-call cap, USD 0 budget, confidence 0.80, and similarity 0.70. Call limits cover both vision and embeddings for a tenant, including attempts that fail after reservation.

### 2. Start the database, migrate, and seed image records

```powershell
docker compose up -d db
.\.venv\Scripts\python.exe -B -m alembic upgrade head
.\.venv\Scripts\python.exe -B -m scripts.seed
```

Wait for PostgreSQL to accept connections before migration. The migration head is `47b9c01c769a`. The seed command creates the `FlyRank Demo` tenant and inserts missing image records from `data/images.json`; repeating it skips existing records. It does not download images, generate metadata, or seed posts.

### 3. Download or verify the image corpus

The manifest has 51 JPEG entries: the original 50 animal images across five groups, plus one original defocused animal-painting photo for a confidence check. Together they represent 50 distinct Pexels photos. `fox_003` and `fox_007` use the same photograph at different sizes. Source links, download URLs, and checksums are recorded in `data/images.json`. Photos are excluded from Git and follow the [Pexels license](https://www.pexels.com/license/); the repository's MIT license applies to the code.

On a fresh checkout, download the missing files:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.download_images
```

For the existing development corpus, check the files without downloading:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.download_images --verify-only
```

Both commands verify checksums and preserve existing files. An unknown file stops the operation before any downloads. Interrupted transfers leave no partial image; completed downloads are reused on the next run. An upstream file change fails verification rather than silently changing the corpus. Unlisted probe files are left alone. The script uses Python's standard library and sends no Gemini requests or database writes.

The verified downloader reproduced all 50 entries in a separate folder, then reused all 50 without network requests. Thirty-three downloads matched the original bytes; five more matched the decoded pixels exactly. The remaining twelve had small JPEG encoding differences. Both original and verified-download checksums are retained. Keep original files with their stored metadata and embeddings. Fresh AI processing can produce different results.

Three early fox source links were corrected after comparison with the saved photos. For an existing database, preview and save only those source-link corrections:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.sync_image_sources
.\.venv\Scripts\python.exe -B -m scripts.sync_image_sources --apply
```

The helper checks local file hashes, the demo tenant, and the old links before saving. It changes only the three source-page fields and leaves photos, metadata, vectors, suggestions, and costs intact. Repeating it makes no further changes. Fresh databases seeded from the corrected manifest already have the correct links.

### 4. Run the API

Keep this terminal open:

```powershell
.\.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for Swagger and `http://127.0.0.1:8000/health` for the process health response. Health does not check database or Gemini readiness. Use another terminal for scripts. If port 8000 is occupied, use the existing server or stop it before restarting. Restart after code changes; this command does not use auto-reload.

### 5. Generate missing vision metadata

In the second terminal:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.create_vision_job
```

Note the job ID printed by the script. In Swagger, execute `POST /jobs/{job_id}/run-batch` with that ID, `max_steps=50`, and `pause_seconds=15`. Poll `GET /jobs/{job_id}` until completed or failed, and inspect `GET /jobs/{job_id}/costs`. A 202 response means queued, not finished. Existing metadata is reused. If a bounded batch returns to pending, dispatch it again to finish remaining images. If the creation script reports no pending images, skip this step.

Low-confidence metadata is stored with `low_confidence=true` and image status `needs_review`, rather than `tagged`. Stored low-confidence evidence is excluded from automatic suggestions.

### 6. Seed and embed the evaluation posts; finish image embeddings

```powershell
.\.venv\Scripts\python.exe -B -m scripts.run_post_embedding_batch --max-steps 10 --pause-seconds 15
.\.venv\Scripts\python.exe -B -m scripts.create_embedding_job
```

The post batch creates the ten source posts from `data/eval_posts.json`, rejects changed text for an existing external ID, and reuses stored embeddings. The embedding job then scopes all manifest images and ten evaluation posts. In Swagger, execute `POST /jobs/{job_id}/run-embeddings` using its printed ID, `max_steps=60`, and `pause_seconds=15`. Poll its status and costs. A completed job returned by the creation script needs no new dispatch. A pending job at 100% still needs dispatch to confirm cached work and finish; it should create no new AI calls.

These live processing steps can consume free-tier quota. The two job types retry temporary HTTP 429/500/502/503/504 failures, normally up to three attempts with 2- and 4-second waits. Budget blocks and non-retryable failures stop processing. Bounded batches return to pending when their step limit is reached. `POST /jobs/{job_id}/resume` changes a failed job to pending; dispatch it again after addressing the cause. Retry history and previous call records are retained.

### 7. Generate suggestions and review them

Find numeric post IDs with `GET /posts`; these IDs can differ between databases. `post_003` is an external ID used by scripts, not the numeric HTTP path ID.

Use `POST /posts/{post_id}/suggestions?top_k=5` in Swagger. It uses stored vectors and sends no Gemini request. Repeating it reuses eligible stored suggestions. Responses include scores, guard explanations, and either `matched` or `no_confident_match` with reasons.

For a returned suggestion ID, execute `POST /suggestions/{suggestion_id}/reviews` with:

```json
{"decision": "accept", "review_note": "Image fits the post."}
```

Use `decision: "reject"` for rejection. Each submission appends history; `GET /suggestions/{suggestion_id}/reviews` returns previous decisions. Human review does not overwrite the automated guard explanation.

## Tests and evaluation

The repeatable offline command is:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.run_checks
```

Recorded staged outcome: all 265 tests passed. These tests use temporary files, isolated SQLite databases, and simulated provider responses. No Gemini requests are sent. The existing Starlette warning about `httpx` is visible and nonfatal in this verified environment; installing a new HTTP client has not been validated. The three live integration commands are deliberately excluded from this runner.

After stored metadata and embeddings are ready, evaluate without new Gemini requests:

```powershell
$evaluationStamp = Get-Date -Format "yyyyMMdd_HHmmss_fffffff"
.\.venv\Scripts\python.exe -B -m scripts.evaluate_matching --dataset data/eval_posts_audited_v1.json --output "reports/evaluation_audited_$evaluationStamp.json"
```

Outputs use new filenames because the evaluator refuses to overwrite reports. Gold labels are used for scoring only. On the recorded development database the result is 7/10 (70%). Re-generating vision metadata or embeddings can change rankings; a fresh model run is not guaranteed to reproduce the historical score exactly.

The cutoff study in `reports/similarity_cutoff_study_v1.json` compares ten reference pairs and ten curated wrong-subject pairs. At 0.70 all ten reference scores remain above the cutoff, but one wrong subject also remains above it. Subject and context checks are therefore necessary. Cosine similarity and model confidence are not calibrated correctness probabilities.

A separate live equivalent-concepts probe matched `Vulpes vulpes` to `fox_001` first (0.830011), above the best wolf (0.737913), and rejected every wolf by subject. Its report is `reports/equivalent_concepts_v1_20261010T192454_022937Z.json`. This is one additional development query, excluded from the ten-post evaluation.

## Fresh PostgreSQL setup check

With Docker Desktop running and the local `postgres:16` image available:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.verify_fresh_postgres
```

This creates a temporary PostgreSQL 16 container on a separate localhost port, applies both migrations twice, and seeds images twice. It checks the schema against the models, verifies every source record against the manifest count, and tests PostgreSQL uniqueness, foreign keys, API reads, request validation, and post creation. It removes only its own temporary container and saves a new report under `reports/`.

The installed project dependencies are reused. The check preserves the existing database, image files, and `app/.env`. Child processes receive the temporary database address, a blank Gemini key, and a zero-call limit. No AI processing is run. This verifies fresh database setup; reinstalling dependencies in a new environment remains a separate task.

The recorded run passed all four preparation steps and 21 database/API checks with zero schema differences. The report is [fresh_postgres_live_20261011.json](../reports/fresh_postgres_live_20261011.json). The temporary container was removed. Docker must allow Linux containers; the checker does not download an image or remove existing containers or volumes.

## Interrupted worker recovery

A stopped API or CLI worker can leave a job marked `queued`, `queued_batch`, or `running`. Automatic restart recovery is not implemented.

First stop the API server and every CLI vision or embedding worker. A paused or slow worker is still active; do not recover its job. Use the ID of the stranded job:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.recover_interrupted_job JOB_ID
.\.venv\Scripts\python.exe -B -m scripts.recover_interrupted_job JOB_ID --apply --confirm-workers-stopped
```

Replace `JOB_ID` with the numeric job ID. The first command previews the state. The second marks an eligible demo-tenant job as failed while preserving progress, retries, costs, and completed image or embedding work. It refuses pending or completed jobs and preserves existing failure details when repeated. The confirmation flag records the operator's assurance; the command cannot prove that every worker has stopped.

Restart the API, execute `POST /jobs/{job_id}/resume`, then dispatch the appropriate vision or embedding batch. Resumption preserves prior costs and retry counts and reuses stored completed work. A provider request interrupted before its result was saved can require another attempt; do not infer a historical request outcome from recovery.

Seven isolated tests passed for both worker types, preview behavior, stopped-worker confirmation, protected states, tenant isolation, repeat recovery, preserved data, and use of the existing resume endpoint. The tests used simulated stranded states, with no real API process termination or Gemini requests.


Latest recorded verification: the [51-entry PostgreSQL check](../reports/fresh_postgres_20261011T031706_391760Z.json) passed all 21 checks and removed its temporary container. The [saved-data audit](../reports/saved_data_audit_20261011T031628_067132Z.json) found zero errors and five documented historical review items.
