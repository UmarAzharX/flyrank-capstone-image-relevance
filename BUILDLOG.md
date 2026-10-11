# Build Log

This log records how AI assistance was used during development, where its suggestions required correction, and the decisions I made while building the capstone.

## Phase 1 — Design

### AI assistance

AI was used to analyze the FlyRank capstone brief, extract the mandatory requirements, and help structure the initial system design.

It helped with:

- identifying the required image-understanding, semantic-matching, mismatch-guard, background-job, review, evaluation, and cost-tracking requirements
- comparing the allowed technology choices
- proposing an initial Python/FastAPI/PostgreSQL architecture
- drafting the design document and implementation plan
- identifying requirements that were easy to overlook, including idempotency, tenant isolation, failure visibility, the budget guard, and evidence collection

### Corrections and decisions

The first design draft became much more detailed than the brief's requested one-page design document. I kept the detailed material as `docs/IMPLEMENTATION_PLAN.md` and replaced `DESIGN.md` with a concise evaluator-facing design.

The initial wording of the mismatch guard also treated category mismatch too broadly. Since a red fox and a wolf can both belong to the `animal` category, the design was corrected so that subject compatibility is explicitly checked for cases such as fox versus wolf.

A small `app/` scaffold and empty `tests/` directory were created prematurely while editing the design. They were removed because implementation should begin only after the Phase 1 design work is complete.

### Current decisions

- Python + FastAPI
- Pydantic for API and AI-output validation
- PostgreSQL with SQLAlchemy and Alembic
- Docker / Docker Compose for the database environment
- Gemini Flash for image understanding
- Gemini embeddings for semantic matching
- cosine similarity for ranking
- a separate mismatch guard for acceptance/rejection
- no dedicated vector database for the initial small corpus

### Dataset audit correction

After the manifest was populated, an audit showed that only 3 of the 50 referenced image files actually existed locally. The remaining 47 images were then downloaded from their recorded Pexels source pages. A final audit confirmed 50 manifest entries, 50 local images, no missing or unexpected files, no duplicate IDs or filenames, valid JPEG signatures, and 10 images in each of the five planned categories.

## Phase 2 — Image understanding

### AI assistance

AI helped configure the existing google-genai client, validate structured vision responses, save metadata, build bounded background jobs, add retries, and record per-call costs. Changes were prepared as guided checkpoints and checked through terminal commands and Swagger.

### Corrections and decisions

- Early requests returned HTTP 503. The request failed without accepting metadata. Later requests succeeded; bounded retries were then added for temporary failures.
- Automatic function calling was disabled for the structured image request because it was unnecessary for this workflow and produced a warning.
- Existing metadata is reused so repeating processing does not send another vision request.
- Confidence below 0.80 sets the review flag. This behavior was later tested with a simulated response. The original live corpus did not provide a below-threshold result, which remains an acceptance gap.
- The API key stays in app/.env. Error output withholds raw exceptions that might contain secrets.
- Port conflicts and connection-refused responses were addressed by keeping one API server running and restarting it when needed.

### Recorded result

The 50-image vision batch reached 100% completion. Costs were visible under the declared free-tier setup. Early exploratory requests before ledger integration are not treated as proof of complete historical cost accounting.

## Phase 3 — Embeddings and matching

### AI assistance

AI helped build image and post embedding text, validate normalized 768-dimensional vectors, store and reuse embeddings, rank all corpus candidates, apply mismatch checks, and save explained suggestions.

### Corrections and decisions

- Similarity ranking alone allowed a husky image to appear among wolf results. A separate subject guard rejected that pairing.
- Broad subject families were insufficient for specific requests. Dog-breed rules distinguish husky from malamute, and a grizzly request requires subtype evidence beyond generic brown-bear metadata.
- Required context such as snow, summer, indoors, and close-up views must be supported by metadata. Missing evidence leads to review rather than an automatic suggestion.
- All candidates are checked before selecting the requested number of suggestions. A small result set is valid when only a few images pass.
- Repeating suggestion generation reuses eligible saved rows. Human decisions are kept separately from the automated guard result.

### Recorded result

All 50 corpus image embeddings and ten evaluation-post embeddings were stored. Eleven suggestions were saved across seven evaluation posts. Three posts received no confident match because the guard lacked the required evidence.

## Phase 4 — Review, evaluation, and hardening

### AI assistance

AI helped add validated review endpoints and history, evaluation reports, a cutoff study, readable no-match reasons, scientific-name aliases, tenant-scoped reads, retry and budget checks, and embedding background jobs.

### Corrections and decisions

- The first evaluation scored 5/10 exact matches. An AI-assisted audit after seeing predictions corrected two expected-image labels: post_001 to fox_002 for snow, and post_005 to dog_010 for husky. The audited score became 7/10. This was a label correction, not a change to the matching engine. The original dataset and report were preserved.
- All-post accuracy and coverage are both 70%. The 100% exact-match rate among returned results is reported separately. Abstentions count as misses in the headline metric.
- The cutoff study used ten reference pairs and ten curated wrong-subject pairs. The configured cutoff is 0.70. Subject and context guards remain necessary because a wrong subject can score above that cutoff. This development study does not establish a universal threshold.
- The scientific-name probe used Vulpes vulpes without an English animal alias in its embedding input. A live run ranked fox first and rejected wolves. The probe stays outside the ten-post evaluation.
- Deprecated datetime.utcnow callbacks were replaced with timezone-aware UTC timestamps. The existing Starlette HTTP-client warning remains visible; dependencies were not upgraded merely to silence it.
- Low-confidence persistence and exclusion were tested with a simulated confidence of 0.60. This proves behavior, but does not replace the brief's live low-confidence image example.
- Image and review reads were checked for tenant isolation. The API still selects one fixed demo tenant and has no authentication.
- Post embedding processing gained bounded retries. Embedding jobs gained progress, safe failure reasons, job-linked call records, and failed-job resumption. Live Job 2 completed using cached vectors and recorded zero new calls.
- Standard unittest discovery could not import the namespace-style scripts directory. A dedicated offline runner provides one explicit command. The combined suite passed 212 tests.

## Documentation checkpoint — 2026-10-11

AI prepared the README, setup/API guides, environment example, dependency constraints, evidence file, and evaluator manifest. The user reviewed the README and requested separate limitations and future-improvement sections. The first documentation draft was too long. Detailed instructions moved into guides, and the main README was rewritten in simple professional English without ellipses.

The evidence file separates live observations from simulated tests. It records unfinished checks rather than claiming the capstone is fully complete. Eleven focused offline evidence checks passed. Both Alembic migrations applied to a temporary SQLite database with zero model differences. At that checkpoint, fresh PostgreSQL setup had not been verified; the later database check below completed it.

## Saved-data audit checkpoint — 2026-10-11

AI prepared a read-only audit and 14 isolated tests. The user passed all 14 tests and ran the audit against PostgreSQL. The report `reports/saved_data_audit_20261010T225227_115832Z.json` confirmed valid metadata for 50 images, 50 normalized image embeddings, ten evaluation-post embeddings, and structurally valid cost entries for all 114 recorded calls. One separate probe embedding was excluded from corpus totals. Both jobs were completed at 100%.

The audit found zero errors and five review items: four unknown or legacy call outcomes and a missing recognized vision-response record for each of two corpus images, reported as one aggregate review item. Token usage was unavailable for 62 entries. The audit did not modify database records or send Gemini requests. No historical call outcomes were inferred or rewritten. All 50 corpus confidence values were above the configured threshold, so the real low-confidence example remains pending.

## Acceptance and source verification — 2026-10-11

AI helped replay the fox ranking, inspect the legacy ledger, validate API inputs, and prepare a safe corpus downloader. The measured fox ranking passed all six checks. Review history retained acceptance followed by rejection. Thirteen live invalid create requests returned HTTP 422 without adding records. The legacy call outcomes were inspected and preserved as unknown; missing historical evidence remains documented.

The user confirmed Pexels as the photo source. File comparisons recovered the correct source pages for `fox_001`, `fox_002`, and `fox_003`. The last shares a photograph with `fox_007`, so the 50 corpus entries represent 49 distinct photos. Current photo files, AI results, and evaluation labels were preserved.

The downloader successfully downloaded and verified all 50 entries into a separate folder. A second run reused all files. Thirty-three downloads matched the original bytes, five more matched the decoded pixels, and twelve had small JPEG encoding differences. The manifest records original and download checksums separately. The staged offline suite passed 246 tests, including 18 downloader checks and four source-correction checks. The live API later confirmed all three corrected source links.

## Fresh PostgreSQL database setup — 2026-10-11

AI prepared a repeatable check using a separate temporary PostgreSQL 16 container on a random localhost port. The live run applied migrations twice, seeded records twice, and passed all 21 schema, constraint, and API checks. The schema matched the SQLAlchemy models with zero differences. The second seed created zero images and skipped all 50 existing records. No Gemini client was created or cost records saved.

The temporary container was removed after verification. Child processes used a separate database address, a blank Gemini key, and a zero-call limit. Existing data and `app/.env` were preserved. Four offline safety tests covered settings isolation, successful cleanup, cleanup after failure, and refusing removal when container ownership does not match. This check reused installed dependencies and did not reinstall the project environment.

## Interruption and repository review — 2026-10-11

The user passed all 250 offline tests in 4.816 seconds. AI then prepared a manual recovery command for jobs stranded in queued or running states. The command requires confirmation that all API and CLI workers are stopped. It marks the selected demo job failed, preserves progress, retry counts, costs and cached work, and allows the existing resume endpoint to return it to pending. Pending and completed jobs are protected. Seven isolated tests passed using simulated interruptions; no real server termination or Gemini request was used.

A read-only Git review found the correct remote name, no tracked `app/.env`, and no recognized secret patterns in the scanned current files or historical blobs. Many recent submission files were uncommitted. Public visibility and publication were not established. Three harmless extra blank lines at the ends of Python files were removed in the checkpoint. The API guide was corrected to reflect the completed downloads and fresh PostgreSQL check.

## Final local review and confidence candidates — 2026-10-11

The user ran the fog candidate through the existing vision pipeline. Image 53 returned subject deer, confidence 0.95, status tagged, and low_confidence=False; call 117 was recorded. The earlier fox candidate also returned 0.95. AI's choice of a foggy photo did not produce a low-confidence result. Neither score was altered, and the original corpus and evaluation were preserved. The required live low-confidence batch example remains pending.

All nine isolated registration checks passed in the user's environment. The latest installed-project regression run passed 257 tests in 4.700 seconds. Git reported no whitespace errors. A refreshed read-only repository scan found no recognized secret patterns and confirmed that app/.env remains ignored and untracked. This limited scan does not prove every possible secret is absent. Public visibility was not established because the network check was declined. The user chose to handle committing and pushing through GitHub Desktop. No commit or push has been performed by this review.

## Published repository review and queued vision jobs — 2026-10-11

The user committed and pushed the Phase 4 submission through GitHub Desktop. GitHub's unauthenticated API confirmed the repository is public and main points to commit 65d97de7737746bfe1af8981ff6754633abfcb0e. Local HEAD and origin/main matched, with a clean working tree. Historical public visibility from day one was not established.

AI reviewed an archive of the committed files. All 257 tests passed there with installed dependencies reused, a blank key, and a zero-call limit. No required files or local Markdown file targets were missing; all Python files parsed and all 16 manifest endpoints matched OpenAPI. Another 27 isolated checks passed separately. This did not verify installation into a completely new virtual environment.

The review found that vision-job creation omitted queued_batch from active states. The new regression test failed against the old command because it created a second job. AI added that state and six isolated checks covering reuse, preservation of stored state, tenant/job-type scope, completed jobs, corpus scope, and missing tenants. The full staged suite passed 263 tests in 14.422 seconds. No live database changes or Gemini calls were made. PostgreSQL concurrency was not tested. This follow-up is prepared for the user to copy, check, commit, and push.

The evidence checklist now records the original submission's completed publication. The genuine low-confidence corpus batch example remains unfinished; both separate live candidates kept their reported confidence of 0.95.

## Remaining work

- Demonstrate a real low-confidence image without changing the reported confidence or evaluation labels.
- Install, check, commit, and push the queued-job follow-up; the original submission is already published and verified public.

The current implementation uses a fixed demo tenant and in-process jobs. Production authentication, durable job recovery, cache invalidation, and broader independent evaluation remain limitations or future work. The published original submission is verified above; publication of this follow-up remains pending.


## 2026-10-11: Prepare a confidence candidate in the corpus

Added an original, unedited Pexels photo of a defocused animal painting as the 51st manifest entry. Preserved the original 50 entries and evaluation labels. Replaced the fresh PostgreSQL checker's fixed image count with the manifest count; all 265 offline tests passed. The user confirmed pushing the earlier queued-job fix. Live batch confidence, the new embedding, and evaluation against 51 entries are still pending.


## 2026-10-11: Live low-confidence corpus batch completed

The user passed 265 offline tests in 12.320s, seeded one new image while reusing 50, and dispatched normal background vision job 3. The job completed at 100% with zero retries. A read-only query confirmed image 54 (`confidence_motion_001`), subject abstract blur, confidence 0.40, low_confidence=True, and status needs_review. The original image and reported score were not altered. Earlier pending-confidence notes describe the status before this result. The new embedding, evaluation against 51 entries, and publication remain pending.


## 2026-10-11: Expanded corpus evaluation completed

The user saved embedding 63 for the low-confidence image, recorded under cost entry 119. The vector has 768 dimensions and unit length; token usage was unavailable. Evaluation against all 51 manifest entries returned 7/10 exact matches, 70% coverage, and 100% exact matches among returned suggestions. The manifest hash in `evaluation_51_images_20261011_081338_7401606.json` matches the installed manifest. Original gold labels were unchanged. Final saved-data and fresh PostgreSQL verification, followed by publication, remain pending.


## 2026-10-11: Final local verification passed

The saved-data audit confirmed 51 valid corpus descriptions and embeddings, ten evaluation-post embeddings, and one real low-confidence image. It found zero errors and the same five documented historical ledger review items. Fresh PostgreSQL verification passed 21 checks for the expanded corpus, migrations and seeding were repeatable, and the temporary container was removed. Reports: `saved_data_audit_20261011T031628_067132Z.json` and `fresh_postgres_20261011T031706_391760Z.json`. No Gemini requests were sent by either check. The final updates are ready to commit and push.
