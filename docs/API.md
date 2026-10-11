# API Guide

[Back to README](../README.md) | [Setup guide](SETUP.md)

Use Swagger at `http://127.0.0.1:8000/docs`. Paths use numeric database IDs; find posts with `GET /posts` and use the job IDs printed by the creation scripts. External IDs such as `post_003` are used by CLI tools.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Process health |
| GET / POST | `/images` | List / create image records |
| GET | `/images/{image_id}` | Inspect image record |
| GET / POST | `/posts` | List / create posts |
| GET | `/posts/{post_id}` | Inspect post |
| POST | `/posts/{post_id}/suggestions` | Generate or reuse eligible suggestions |
| GET | `/jobs/{job_id}` | Job state, progress, retries, failure |
| GET | `/jobs/{job_id}/costs` | Costs and reported usage for that job |
| POST | `/jobs/{job_id}/run-one` | Queue one vision step |
| POST | `/jobs/{job_id}/run-batch` | Queue bounded vision processing |
| POST | `/jobs/{job_id}/run-embeddings` | Queue bounded embedding processing |
| POST | `/jobs/{job_id}/resume` | Return failed job to pending |
| POST / GET | `/suggestions/{suggestion_id}/reviews` | Append / inspect review history |

## Create-request validation

Image and post creation return HTTP 422 for blank required text, incorrect field types, or unexpected fields. Length limits are 100 characters for external IDs, 255 for image filenames and post titles, 50 for image sources, and 100,000 for post content. The content limit is an application limit.

Image filenames must be plain JPG, JPEG, or PNG names. Paths, invalid Windows filename characters, and reserved device names are rejected. A source page must be an HTTP or HTTPS URL. Validation does not download a file or confirm that it exists locally. Valid post text is preserved without trimming.

## Matching and review

Only candidates with guard decision `pass` can be suggested. `review` means insufficient evidence; `reject` means an identified mismatch. The guard checks every corpus candidate before applying `top_k`. Matching responses include scores, explanations, and either `matched` or `no_confident_match` with reasons.

For `POST /suggestions/{suggestion_id}/reviews`, submit:

```json
{"decision": "accept", "review_note": "Image fits the post."}
```

Use `decision: "reject"` for rejection. Every submission adds a history row. `GET /suggestions/{suggestion_id}/reviews` returns the history; human decisions preserve automated explanations.

## Background jobs

The [setup guide](SETUP.md) gives vision and embedding dispatch parameters. A 202 response confirms queuing, not completion. Poll `GET /jobs/{job_id}` and inspect `/costs`. Only pending jobs can be queued; attempts to dispatch other states return 409. Vision endpoints accept vision jobs, and `/run-embeddings` accepts embedding jobs.

`POST /jobs/{job_id}/resume` returns a failed job to pending without deleting prior costs or retry history. Dispatch it again after fixing the failure cause. Completed cached work creates no new calls. A cached embedding job may start pending at 100% and require dispatch to mark completion.

Retries cover HTTP 429/500/502/503/504, normally with three attempts and waits of 2 and 4 seconds. Budget limits and non-retryable failures stop processing. A bounded batch returns to pending when its step limit is reached.

## Costs and persistence

- Each application vision/embedding attempt reserves a tenant-attributed ledger entry before the request. Results or failures update that entry. Embedding calls identify their owner; job-driven calls additionally identify the job. Standalone historical embedding calls are not retroactively attached to a later cached job. A job using only cached vectors correctly reports zero calls.
- Cost is recorded as USD 0 under the declared free-tier assumption. This is not paid-tier pricing or billing verification. Embedding usage was unavailable in live SDK responses; the ledger records that uncertainty. A reported token total of zero can mean missing usage, rather than zero computation. Call count remains tracked.
- Tenant IDs scope reads and processing. Unique constraints cover image/post external IDs per tenant and embedding owner/profile per tenant. Migrations include foreign keys and lookup indexes. Post locking serializes suggestion reuse; suggestion pairs have no database unique constraint. Vector owners use an owner type/ID pair rather than an owner foreign key.

## Operational limitations

- **Small development evaluation:** the corpus contains 50 image entries (49 distinct photographs) and ten labeled posts. The audited top-1 result is 70%, with 70% coverage. Labels were corrected after inspecting predictions, and the same development data informed the cutoff study. These results do not establish performance on unseen datasets or other subject domains.
- **Conservative, limited guard rules:** subject aliases, dog/bear subtypes, context terms, and negation checks cover a small set of English expressions. Missing evidence leads to review rather than an automatic suggestion. The guard does not fully verify actions such as walking versus standing. The three recorded abstentions concern unconfirmed summer, indoor/home context, and grizzly subtype.
- **Confidence is not calibrated:** vision confidence is the model's own estimate; neither it nor cosine similarity is a correctness probability. A simulated confidence-0.60 fixture proves flagging and exclusion even with cosine 1.0. All 50 current live corpus classifications were above threshold, so the brief's live low-confidence corpus example remains outstanding.
- **Jobs depend on the API process:** FastAPI background tasks are not a durable queue. Stopping the server can strand queued/running work. Automatic restart recovery is not implemented. The [manual recovery command](SETUP.md#interrupted-worker-recovery) marks a stranded job failed after all workers are stopped; the resume endpoint then returns it to pending.
- **Demo tenant and no authentication:** HTTP routes use the fixed `FlyRank Demo` tenant. There is no authenticated tenant switching. Offline isolation tests cover cross-tenant reads, but production authorization and concurrent PostgreSQL behavior have not been established.
- **Cached inputs must remain unchanged:** embeddings have no content hash for automatic invalidation after direct database edits. The post batch rejects conflicting source text, but changed inputs require deliberate cache maintenance.
- **Limited scale and database safeguards:** vectors are JSON arrays ranked in application memory. Suggestion pairs have no database unique constraint, and vector owners use a type/ID pair rather than an owner foreign key. Existing service locks and reuse checks have not been validated under a production concurrency workload.
- **Free-tier accounting assumption:** cost entries record USD 0 under the declared free-tier setup. Paid-tier pricing is not implemented. Live embedding usage was unavailable, so recorded token totals are incomplete; call counts remain tracked. Model availability, quota, and output changes can affect fresh runs.
- **Reproduction limits:** source photos are excluded from Git. The verified downloader supplies missing files, and a fresh PostgreSQL 16 container passed migrations, repeated seeding, constraints, and API checks. Installed dependencies were reused. Some downloaded JPEGs differ slightly from the originals, and fresh AI results can change.

