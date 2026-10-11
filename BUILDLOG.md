# Build Log

This log records how AI assistance was used during development, where its suggestions required correction, and the decisions I made while building the capstone.

## Phase 1 â€” Design

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

## Phase 2 â€” Image understanding

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

## Phase 3 â€” Embeddings and matching

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

## Phase 4 â€” Review, evaluation, and hardening

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

## Documentation checkpoint â€” 2026-10-11

AI prepared the README, setup/API guides, environment example, dependency constraints, evidence file, and evaluator manifest. The user reviewed the README and requested separate limitations and future-improvement sections. The first documentation draft was too long. Detailed instructions moved into guides, and the main README was rewritten in simple professional English without ellipses.

The evidence file separates live observations from simulated tests. It records unfinished checks rather than claiming the capstone is fully complete. Eleven focused offline evidence checks passed. Both Alembic migrations applied to a temporary SQLite database with zero model differences. At that checkpoint, fresh PostgreSQL setup had not been verified; the later database check below completed it.

## Saved-data audit checkpoint â€” 2026-10-11

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

## Remaining work

- Demonstrate a real low-confidence image without changing the reported confidence or evaluation labels.
- Commit the reviewed files and confirm public repository visibility and publication.

The current implementation uses a fixed demo tenant and in-process jobs. Production authentication, durable job recovery, cache invalidation, and broader independent evaluation remain limitations or future work. No publication or repository-history changes are claimed by this log.
