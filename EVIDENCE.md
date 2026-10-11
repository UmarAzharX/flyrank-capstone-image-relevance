# Capstone Evidence

Each section gives one proof for a capstone requirement. **Live** results came from the user's terminal, API responses, or saved reports. **Offline** results use isolated test databases and simulated AI responses. Full explanations and longer excerpts are in the [detailed evidence record](reports/evidence_details_v1.md).

## 1. Validated vision output

**Live:** the single-image test returned `Gemini request succeeded; metadata passed validation.`

**Offline schema checks, 2026-10-11:**

```text
PASS: wrong field types rejected with ValidationError.
PASS: empty caption rejected with ValidationError.
PASS: confidence above one rejected with ValidationError.
```

[Vision processing](app/vision.py) validates responses before returning accepted metadata. The [saved-data audit](reports/saved_data_audit_20261010T225227_115832Z.json) confirmed valid metadata for all 50 corpus images.

## 2. Low-confidence results are flagged

**Offline:** `test_high_similarity_cannot_automatically_select_low_confidence_image` in [the pipeline checks](scripts/check_low_confidence_pipeline.py) passed.

```text
Controlled fixture: confidence=0.60 | low_confidence=True | status=needs_review | cosine=1.0 | automatic_suggestions=0
```

This used a simulated response. All 50 live corpus results were above threshold. The separate live candidate `confidence_probe_001` (image ID 52) returned confidence 0.95 and was correctly saved as `tagged` with `low_confidence=False`; cost entry 115 recorded the request. The second unedited candidate `confidence_probe_fog_001` (image ID 53) also returned confidence 0.95. It was saved as `tagged` with `low_confidence=False`, and cost entry 117 recorded the request. The user passed nine isolated registration checks. Both live candidate results were preserved. These were single-image runs outside the original corpus. **The added corpus image now demonstrates this behavior through completed background job 3; see the live result below.**

## 3. Background vision processing and retries

**Live:** the API accepted a background batch, followed by this server output:

```text
Image handled: deer_010
Status: completed
Corpus progress: 100%
Corpus processing completed.
```

**Offline:** [retry checks](scripts/check_retries.py) passed three tests covering temporary errors, immediate stopping on HTTP 400, and the attempt limit. Automatic restart recovery is not implemented. Seven isolated [manual-recovery checks](scripts/check_interrupted_job_recovery.py) passed using simulated queued/running states. They verified preservation of completed work, progress, retries and costs, plus resumption through the existing API. Operators must stop all workers before applying the recovery command. No real server termination or Gemini requests were used in these checks.

## 4. Per-call costs and budget limits

**Live vision-job excerpt:**

```text
Selected image: fox_007
Call slot reserved: 9
Cost record updated: 9
Cost USD: 0.00 (free tier)
```

**Offline:** `test_transient_retry_is_persisted_and_each_call_attributed`, `test_budget_block_prevents_sdk_and_cost_record`, and `test_retry_cannot_bypass_call_cap` in [the worker checks](scripts/check_embedding_worker.py) passed.

The [saved-data audit](reports/saved_data_audit_20261010T225227_115832Z.json) checked 114 cost entries with no structural errors. Four early entries have unknown or legacy outcomes; two corpus images lack a recognized vision-response record. These are historical evidence gaps. The [read-only inspection](reports/legacy_ledger_review_20261011T001830_277513Z.json) confirmed that calls 1–4 have unknown outcomes; `fox_002` and `fox_003` have metadata but only legacy vision-call records. Reported usage does not establish those call outcomes. The original records were preserved. Token usage was unavailable for 62 entries. USD 0 assumes the declared free tier.

## 5. Stored embeddings and ranked suggestions

**Live saved-vector excerpt:**

```text
Embedding saved and read back from PostgreSQL.
Configuration: gemini-embedding-2:768:retrieval:text-v1
Dimensions: 768
Vector length: 1.000000
```

The saved-data audit confirmed 50 valid normalized image embeddings and ten evaluation-post embeddings. One separate probe embedding was excluded from these totals.

**Live ranking replay, 2026-10-11:** all six checks passed across 50 candidates for `post_001`.

| Candidate | Raw rank | Cosine score | Guard |
| --- | ---: | ---: | --- |
| Fox: `fox_002` | 1 | 0.784288 | pass |
| Best wolf: `wolf_003` | 13 | 0.682346 | reject |
| Best dog: `dog_010` | 14 | 0.682018 | reject |

The fox scored about 0.102 above each incorrect subject. Both were rejected by the subject and full guards. The [saved replay](reports/fox_ranking_20261011T001530_148580Z.json) uses measured scores from stored vectors, with no database writes or Gemini requests. This is one development query; cosine scores are not probabilities.

Live embedding Job 2 completed at 100% with zero new calls because all scoped vectors already existed. New-call behavior through this worker is covered by simulated tests.

## 6. Equivalent concepts match

**Live:** the `Vulpes vulpes` query ranked `fox_001` first at 0.830011, above the best wolf at 0.737913.

```text
PASS: raw_top_1_is_fox
PASS: eligible_top_1_is_fox
PASS: fox_scores_above_best_wolf
PASS: all_wolves_rejected_by_subject
```

The [saved probe report](reports/equivalent_concepts_v1_20261010T192454_022937Z.json) covers one development query outside the ten-post evaluation.

## 7. Incorrect candidates are rejected

**Live saved-metadata replay:** the designated cases forced `wolf_001` and `dog_001` as candidates for fox posts.

```text
PASS: guard_001 | candidate=wolf_001 | subject=wolf | guard=reject
PASS: guard_002 | candidate=dog_001 | subject=Alaskan Malamute | guard=reject
```

Both explanations identified the fox-versus-wolf/dog subject mismatch. The similarity input was deliberately forced to 1.0 as a guard stress test; it was not a measured cosine score. The [saved report](reports/forced_rejections_20261011T000138_308569Z.json) records both results. No database writes or Gemini requests were made.

## 8. Rejections explain the mismatch

**Live guarded ranking for `post_003`:**

```text
dog_010 | score=0.715927 | guard=reject
Explanation: Subject mismatch: post describes wolf; image describes dog.
```

[Guard checks](scripts/check_mismatch_guard.py) also cover subject, context, and confidence decisions. Broad animal-category agreement alone does not authorize a match.

## 9. No confident match includes reasons

**Live API replay:** `POST /posts/13/suggestions?top_k=5` for the designated whale fixture returned:

```text
match_status: no_confident_match
suggestions: []
created_count: 0 | reused_count: 0 | candidates_checked: 50
Nearest scores: deer_004=0.625698 | bear_010=0.624173 | dog_010=0.619907
```

All three nearest scores were below the configured 0.70 cutoff. The response also explained that the subject was outside the guard's supported set. This is safe abstention, not a claim that the guard recognizes whales. The [captured API evidence](reports/whale_no_match_api_20261011.json) preserves the user-pasted response. This separate probe used embedding cost entry 116 and did not change the ten-post evaluation.

**Offline:** `test_abstention_is_200_with_real_guard_reasons_and_no_writes` in [the API checks](scripts/check_no_match_api.py) passed.

## 10. Persistence, migrations, and tenant isolation

**Offline migration check, 2026-10-11:** both migrations applied to temporary SQLite.

```text
Migration/model differences: 0
```

[Tenant-read checks](scripts/check_tenant_read_api.py) passed in the full suite. The focused review-isolation test passed as well. Migrations include foreign keys, indexes, and tenant-scoped image/post and embedding uniqueness. A fresh PostgreSQL 16 container passed migrations, repeated seeding, schema comparison, constraints, and API checks on 2026-10-11. The [saved setup report](reports/fresh_postgres_live_20261011.json) records four preparation steps and 21 checks with zero schema differences. The temporary container was removed, and no Gemini requests were sent. Installed dependencies were reused; production concurrency remains unverified. API access uses a fixed demo tenant without authentication.

## 11. Validated API and review history

**Live:** `POST /suggestions/1/reviews` returned HTTP 201 and saved rejection review ID 2. Repeating suggestion generation reported:

```text
Created suggestions: 0
Reused suggestions: 1
```

**Live history replay, 2026-10-11:** `GET /suggestions/1/reviews` returned both records in order: review 1 accepted the image; review 2 later rejected it. Both notes and timestamps were preserved. The [captured history](reports/review_history_api_20261011.json) records the user-pasted result.

**Offline:** `test_history_preserves_order_and_previous_decisions` in [review checks](scripts/check_review_api.py) and `test_invalid_limits_are_422` in [matching API checks](scripts/check_no_match_api.py) passed. [Create-request checks](scripts/check_api_inputs.py) passed 12 isolated HTTP tests covering blank and oversized text, field types, unexpected fields, unsafe filenames, URL validation, valid boundaries, and duplicate conflicts. Invalid requests returned HTTP 422 with no records saved. **Live replay, 2026-10-11:** all 13 [create-request probes](reports/live_api_validation_20261011T003049_873118Z.json) returned HTTP 422 with the expected field errors after the server restart. Image and post record IDs were unchanged. Each probe also omitted a required field to prevent saving a record if an older validator were loaded. No Gemini requests were sent.

## 12. Measured top-1 accuracy

**Saved live report:** [evaluation_with_cutoff_v1.json](reports/evaluation_with_cutoff_v1.json).

| Metric | Result |
| --- | ---: |
| Correct first image across all posts | **7/10 (70%)** |
| Posts receiving a suggestion | **7/10 (70%)** |
| Correct first image among returned results | **7/7 (100%)** |

The README reports the same values. Three posts received no match and count as misses. Two label corrections after inspecting predictions raised agreement from 50% to 70%; post text and embeddings stayed unchanged. The dataset and cutoff study are development data.

## 13. Submission documentation and safe configuration

The [README](README.md) includes an architecture diagram, setup/seed/run commands, results, limitations, and future improvements. [BUILDLOG.md](BUILDLOG.md), [capstone.yaml](capstone.yaml), [.env.example](.env.example), [setup guide](docs/SETUP.md), [API guide](docs/API.md), and [license](LICENSE) complete the prepared file set.

**Live download verification, 2026-10-11:** the [verified source report](reports/corpus_sources_verified_20261011.json) records 50 successful downloads into a separate folder, followed by a repeat run with zero downloads. The original corpus passed all 50 checksum checks without changes. Three fox source-page links were corrected; `fox_003` and `fox_007` share one photo, leaving 49 distinct photographs. Original and fresh-download hashes are recorded separately because 17 files differ in bytes. Four isolated source-sync tests passed. Live `GET /images` confirmed that all three corrected source links are present in the existing database.

The manifest's 16 endpoint definitions matched OpenAPI. On 2026-10-11, `app/.env` was ignored and absent from the tracked-file check. The [read-only repository review](reports/repository_review_20261011.json) found the required remote name, an ignored and untracked `app/.env`, and no recognized secret patterns among scanned current files and historical blobs. This limited pattern scan does not prove every possible secret is absent. That pre-publication review did not establish remote visibility or publication. The later verification below confirmed the published repository.

## Combined test evidence

**User's offline run:**

```text
Ran 212 tests in 3.648s

OK
```

**Assistant's staged regression run, 2026-10-11:** all 224 offline tests passed, including the 12 new create-request checks. The suite used isolated SQLite and simulated AI responses; no Gemini requests were sent.

**Focused evidence checks, 2026-10-11:**

```text
Ran 11 tests in 0.469s

OK
```

**Download checkpoint staged run, 2026-10-11:** all 246 offline tests passed, including 18 download-safety checks and four source-link correction checks. No live database writes or Gemini requests were made.

Run `.\.venv\Scripts\python.exe -B -m scripts.run_checks` to repeat the full offline suite. The existing Starlette warning was visible and did not fail the tests. These results do not establish live provider reliability or PostgreSQL concurrency.

**Latest installed-project check, 2026-10-11:** all 246 tests passed in the user's repository. The fresh-setup checkpoint adds four isolated orchestration checks for child settings and safe cleanup. All 250 staged tests passed.

**User's latest offline run:** 250 tests passed in 4.816s. The interruption checkpoint adds seven isolated recovery checks; its complete staged suite passed 257 tests.

## Saved-data audit

**Live PostgreSQL report:** [saved_data_audit_20261010T225227_115832Z.json](reports/saved_data_audit_20261010T225227_115832Z.json).

The read-only audit found **0 errors and 5 review items**. All 50 metadata records, 50 image embeddings, ten evaluation-post embeddings, and 114 cost entries passed their structural checks. Both jobs were completed at 100%. The review items cover four unknown or legacy call outcomes and missing recognized vision-response records for two corpus images. No Gemini requests were sent or database records changed.

At the time of this original audit, all 50 corpus confidence values were between 0.95 and 0.99. The later added image returned 0.40, as recorded below. The user also passed all 14 isolated audit tests. These tests were run separately from the recorded 212-test suite.

## Publication and queued-job correction — 2026-10-11

**Public repository verification:** GitHub's unauthenticated API confirmed `private=false`, `visibility=public`, and default branch `main`. The published commit `65d97de7737746bfe1af8981ff6754633abfcb0e` matched local HEAD and origin/main. The local working tree was clean. The [verification record](reports/public_repository_verification_20261011.json) records these observations. Current public visibility does not prove historical visibility from day one.

The committed checkout passed all 257 offline tests in 5.036s using installed dependencies, a blank Gemini key, and a zero-call limit. Required files were present, local Markdown file links resolved, all tracked Python files parsed, and all 16 manifest operations matched OpenAPI. This was not a new dependency installation or a live AI run.

**Queued vision job regression:** `test_queued_batch_and_other_active_states_reuse_job_without_changes` in [vision-job creation checks](scripts/check_vision_job_creation.py) failed before the fix because creating a job produced a second active job while the first was `queued_batch`. The creation check now treats `queued_batch` as active. Six isolated checks cover active states, preservation of progress/retries/costs and image state, repeat creation, tenant/job-type scope, completed jobs, corpus scope, and a missing tenant.

**Assistant's latest staged regression run:**

```text
Ran 263 tests in 14.422s

OK
```

The staged suite used isolated SQLite and simulated AI responses. No live database records were changed and no Gemini requests were sent. These checks do not establish PostgreSQL concurrency behavior. The user confirmed installing, checking, and pushing this follow-up. Its new remote commit has not been independently verified here.

## Remaining acceptance checks

1. Commit and push the final updates, then verify the published files. All current local checks are recorded below. Historical ledger gaps remain documented limitations.


## Added corpus confidence candidate — 2026-10-11

The manifest now includes `confidence_motion_001`, an original Pexels photograph of a defocused animal painting by Leiliane Assis. Its [source record](data/confidence_motion_candidate_v1.json) includes the download checksum and license link. The image was not edited. The original 50 manifest entries and evaluation labels were preserved.

The fresh PostgreSQL checker now uses the manifest count. Offline regression checks cover seeding and reusing 51 entries, rejecting empty or duplicate manifests before Docker, and retaining temporary-container isolation. All **265 offline tests passed in 16.091s**. No live database writes or Gemini requests were made during these checks. The later live PostgreSQL verification passed for all 51 entries, as recorded below.

**Live result supplied by the user:** background vision job 3 completed at 100%, with zero retries and no failure reason. A read-only PostgreSQL query returned image ID 54, subject `abstract blur`, confidence **0.40**, `low_confidence=True`, and status **`needs_review`**. This is below the unchanged configured threshold of 0.80. The confidence was not altered.

The [live evidence record](reports/live_low_confidence_batch_20261011.json) preserves the supplied job response and saved metadata. The assistant did not independently query the live database. No cost entry ID or token usage was supplied. The user's installed suite also passed **265 tests in 12.320s**. The user saved embedding 63 using call entry 119, with 768 dimensions and unit vector length. Token usage was unavailable. The [51-image evaluation](reports/evaluation_51_images_20261011_081338_7401606.json) reports 7/10 exact matches, 7/10 coverage, and 7/7 exact matches among returned results. The report's manifest hash matches the current manifest. Evaluation labels and matching thresholds were unchanged. Final saved-data and fresh PostgreSQL checks passed, as recorded below.


## Final verification — 2026-10-11

The [saved-data audit](reports/saved_data_audit_20261011T031628_067132Z.json) confirms 51/51 valid corpus metadata records, 51/51 valid corpus embeddings, ten valid evaluation-post embeddings, one low-confidence corpus image, and 119 structurally valid cost entries. All three jobs completed at 100%. It found **zero errors and five review items**: four legacy call outcomes and missing recognized historical vision-response records for two original corpus images. These gaps were preserved and disclosed. Token usage was unavailable for 64 calls.

The [fresh PostgreSQL verification](reports/fresh_postgres_20261011T031706_391760Z.json) passed all **21 checks** for the 51-entry manifest, plus migrations and seeding repeated successfully. The schema matched the models with zero differences. The temporary container was removed; the existing database and environment file were unchanged. No Gemini requests were sent. Installed dependencies were reused, so this does not demonstrate a fresh dependency installation.

These saved reports were read and checked against the current manifest. Publication of the final updates is the remaining delivery step.
