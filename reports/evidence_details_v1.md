# Detailed Evidence Record

This file records observed results for the FlyRank capstone requirements. Live evidence comes from the user's terminal outputs, API responses, and saved reports. Offline evidence uses temporary SQLite databases and simulated AI responses. Test results do not replace a live acceptance check.

## Current evidence summary

| Area | Evidence | Remaining check |
| --- | --- | --- |
| Vision processing | Successful validated metadata; vision Job 1 completed at 100% | Fresh audit of all saved corpus metadata |
| Low confidence | Simulated confidence 0.60 saved for review and excluded from suggestions | A real low-confidence corpus example |
| Stored embeddings | 50 image and ten evaluation-post embeddings saved | Fresh installation and model regeneration |
| Semantic matching | Live fox ranking and scientific-name probe | Broader independent evaluation |
| Mismatch guard | Live wolf rejection plus controlled forced-candidate test | Final replay of the designated acceptance cases |
| No confident match | Live API reasons and controlled API tests | Final replay on the submission database |
| Review API | Live rejection saved; history and isolation tests passed | Final live history inspection |
| Costs and budget | Live ledger outputs; retry attribution and budget tests | Full ledger audit for current production paths |
| Migrations and setup | Two migrations match models on temporary SQLite | Fresh PostgreSQL setup and image acquisition |
| Documentation | README, guides, AI usage log, and evaluator manifest | Final file and acceptance review |

## 1. Structured vision output is validated

**Live excerpt: single-image vision test**

```text
Gemini request succeeded; metadata passed validation.
```

The returned metadata contained a subject, category, attribute list, caption, and confidence of 0.99. `app/vision.py` validates the response with `VisionMetadata.model_validate_json` before returning accepted metadata.

**Offline schema check, 2026-10-11**

```text
PASS: valid vision metadata accepted.
PASS: wrong field types rejected with ValidationError.
PASS: empty caption rejected with ValidationError.
PASS: confidence above one rejected with ValidationError.
```

These checks used local payloads. They establish schema rejection behavior; they do not constitute a fresh audit of every saved corpus row.

## 2. Low-confidence classifications are flagged

Test: `scripts.check_low_confidence_pipeline.LowConfidencePipelineTests.test_high_similarity_cannot_automatically_select_low_confidence_image`.

**Offline output, 2026-10-11**

```text
Controlled fixture: confidence=0.60 | low_confidence=True | status=needs_review | cosine=1.0 | automatic_suggestions=0
Test evidence only: isolated SQLite, simulated vision response, no Gemini requests.
```

The test runs the image-processing, ranking, and suggestion services against isolated data. It confirms that a high similarity score cannot override low vision confidence. The original 50 live image results were above threshold. **The requested live low-confidence corpus example is still pending.**

## 3. Vision processing runs through a background batch with retries

The user started a vision batch through the API, observed a 202 queued response, and later recorded completion in the server terminal.

**Live completion excerpt**

```text
Image handled: deer_010
Status: completed
Corpus progress: 100%
Corpus processing completed.
Job status: completed
Corpus progress: 100%
```

The shared retry checks cover temporary 503 failures, immediate stopping on HTTP 400, and stopping after the attempt limit. The user's retry command reported:

```text
Ran 3 tests in 0.005s

OK
```

The live success demonstrates background dispatch and completion. The retry behavior is tested with simulated errors. Jobs run within the API process; automatic restart recovery is not implemented.

## 4. Vision and embedding costs are recorded per call

**Live vision-job excerpt**

```text
Selected image: fox_007
Call slot reserved: 9
Cost record updated: 9
Cost USD: 0.00 (free tier)
Image handled: fox_007
```

**Live image-embedding excerpt**

```text
Call slot reserved: 54
Cost USD: 0.00 (free tier)
Embedding saved and read back from PostgreSQL.
```

The scientific-name probe also reserved ledger record 114 and recorded free-tier cost. Embedding usage was unavailable in those live SDK responses; the ledger records that limitation rather than assuming measured zero tokens.

The offline test `scripts.check_embedding_worker.EmbeddingWorkerTests.test_transient_retry_is_persisted_and_each_call_attributed` passed on 2026-10-11. It checks the actual reservation/completion services with a simulated 503 followed by success, verifying job and owner attribution for each attempt.

Budget checks passed:

```text
PASS: zero call cap blocked processing before Gemini.
PASS: no cost record was created.
PASS: standalone vision test blocked before Gemini.
PASS: zero call cap blocked embedding reservation.
PASS: no cost record was created.
```

The selected offline checks also confirmed that retries cannot bypass the call cap. Cost is recorded under the declared free-tier assumption; paid-tier pricing is not implemented. Early exploratory requests before ledger integration are not proof of complete historical accounting. A final ledger audit remains pending.

## 5. Image and post embeddings are stored; posts return ranked suggestions

**Live saved-vector excerpt**

```text
Embedding saved and read back from PostgreSQL.
Embedding ID: 1
Configuration: gemini-embedding-2:768:retrieval:text-v1
Dimensions: 768
Vector length: 1.000000
```

The corpus batch reached 50 stored image embeddings. The post batch reached:

```text
Post embeddings: 10/10
```

**Live ranking excerpt for `post_001`**

```text
Corpus candidates: 50
Ranking by cosine similarity:
1. fox_002 | score=0.784288 | subject=red fox
```

The saved report also records `post_001` selecting `fox_002` after guard checks. Vector tests validate dimensions, finite values, nonzero length, and normalization. Stored embeddings are reused on repeat processing.

## 6. Equivalent concepts match semantically

Live report: [equivalent_concepts_v1_20261010T192454_022937Z.json](../reports/equivalent_concepts_v1_20261010T192454_022937Z.json).

The query used `Vulpes vulpes` without an English animal alias in the embedding input. The first raw result was `fox_001` at 0.830011. The best wolf was `wolf_005`, rank 11, at 0.737913.

**Live output**

```text
PASS: raw_top_1_is_fox
PASS: eligible_top_1_is_fox
PASS: fox_scores_above_best_wolf
PASS: all_wolves_rejected_by_subject
```

This is one separate development query. It does not change the ten-post evaluation score or establish general semantic accuracy.

## 7. The mismatch guard rejects incorrect candidates

**Live scientific-name probe excerpt**

```text
11. wolf_005 | score=0.737913 | subject=wolf | guard=reject
Explanation: Subject mismatch: post describes fox; image describes wolf.
```

This wolf scored above the configured similarity cutoff of 0.70 and was still rejected. The subject check identifies fox versus wolf even when both belong to the broad animal category.

The controlled test `scripts.check_equivalent_concept_probe.EquivalentConceptProbeTests.test_high_scoring_wolf_still_rejected_with_subject_reason` passed on 2026-10-11. A final replay of the designated `wolf_001` forced-candidate case in `data/guard_cases.json` remains part of the live acceptance review.

## 8. Rejections include readable explanations

**Live guarded ranking for `post_003`**

```text
dog_010 | score=0.715927 | guard=reject
Explanation: Subject mismatch: post describes wolf; image describes dog.
```

Saved suggestions include the score, guard decision, and explanation. Guard tests cover subject, subtype, context, confidence, and similarity reasons. Passing the broad animal category alone does not authorize a suggestion.

## 9. No confident match returns reasons

The user verified `post_004` through its numeric database ID, which was 5 in that installation. The API returned HTTP 200 with no eligible suggestion and reasons.

**Live reason excerpts**

```text
None of the 50 candidates passed all subject, context, vision-confidence and similarity checks.
Image metadata does not confirm summer.
```

Test: `scripts.check_no_match_api.NoMatchApiTests.test_abstention_is_200_with_real_guard_reasons_and_no_writes`, passed on 2026-10-11. Additional tests check low similarity, low confidence, bounded reasons, and the distinction between a normal no-match result and missing preparation data.

The whale case in `data/guard_cases.json` still needs its final live replay. The current live no-match proof concerns missing required context.

## 10. Persistence, migrations, indexes, and tenant isolation

Migrations: `48011014a97f` creates core tables; `47b9c01c769a` adds embeddings, jobs, costs, suggestions, and reviews. They include foreign keys, lookup indexes, and unique constraints for tenant-scoped image/post IDs and embedding owner/profile combinations.

**Isolated migration check, 2026-10-11**

```text
Running upgrade  -> 48011014a97f, create core tables
Running upgrade 48011014a97f -> 47b9c01c769a, add persistence models
Migration/model differences: 0
```

This check ran against a temporary SQLite file. It did not migrate or inspect the live PostgreSQL database. Fresh PostgreSQL setup verification remains pending.

The tenant-read tests are included in the passing 212-test suite. The selected check `scripts.check_review_api.ReviewApiTests.test_other_tenant_is_hidden_on_both_routes` also passed on 2026-10-11. Routes use the fixed demo tenant without authentication. Suggestion pairs have no database unique constraint; embedding owner IDs have no owner foreign key. Production concurrency is unverified.

## 11. Validated API and review workflow

The user submitted a rejection to `POST /suggestions/1/reviews` and received HTTP 201 with review ID 2 and the saved note.

**Live server excerpt**

```text
POST /suggestions/1/reviews HTTP/1.1" 201 Created
```

The selected tests `scripts.check_review_api.ReviewApiTests.test_history_preserves_order_and_previous_decisions` and `scripts.check_no_match_api.NoMatchApiTests.test_invalid_limits_are_422` passed on 2026-10-11. Review tests also cover invalid decisions, missing suggestions, safe error responses, and preservation of the automated guard result.

Repeat suggestion generation was verified live:

```text
Created suggestions: 0
Reused suggestions: 1
Suggestion ID: 1 | image=wolf_003 | score=0.763176 | guard=pass
```

The selected offline suggestion-reuse test passed as well. These results establish the tested boundaries; a full audit of every API input boundary is still pending.

## 12. A labeled evaluation measures top-1 accuracy

Current report: [evaluation_with_cutoff_v1.json](../reports/evaluation_with_cutoff_v1.json).

**Recorded metrics**

```json
{
  "post_count": 10,
  "returned_count": 7,
  "abstained_count": 3,
  "correct_exact_matches": 7,
  "top1_exact_match_all_posts": 0.7,
  "top1_exact_match_returned_posts": 1.0,
  "coverage": 0.7
}
```

The README reports 70% top-1 accuracy and 70% coverage. The original-label report scored 50%. Two label corrections after inspecting predictions raised agreement to 70%; post text and embeddings were unchanged. The label audit and similarity cutoff study used development data. This is not an independent evaluation of unseen data.

Dataset SHA-256: `e4d71ffe2d32d367b2d1e12b5850e246caecf8b11b27d3d92d8e78390969a939`.

## 13. README, architecture, and required submission files

- [README.md](../README.md): system overview, architecture diagram, setup/seed/run commands, measured accuracy, limitations, and future improvements.
- [docs/SETUP.md](../docs/SETUP.md): detailed preparation and evaluation instructions.
- [docs/API.md](../docs/API.md): endpoints, review examples, job controls, and operating limits.
- [BUILDLOG.md](../BUILDLOG.md): AI assistance, corrections, and implementation decisions.
- [capstone.yaml](../capstone.yaml): evaluator commands and endpoint list.
- [.env.example](../.env.example): safe placeholders for every application setting.
- [LICENSE](../LICENSE): MIT license for the code.

The active `app/.env` is ignored by Git and was not present in the tracked-file check on 2026-10-11. This was a current-file check, not a full repository-history secret scan. Repository naming, visibility, and final publication have not been verified in this checkpoint.

## Supporting regression evidence

**User's full offline run**

```text
Ran 212 tests in 3.648s

OK
```

**Focused evidence checks on 2026-10-11**

```text
Ran 11 tests in 0.469s

OK
```

The focused checks cover low confidence, forced mismatch, no match, suggestion reuse, invalid limits, review history, tenant isolation, retry cost attribution, budget blocks, retry call caps, and cached-job completion. The existing Starlette HTTP-client deprecation warning remains visible and did not fail these tests.

The latest live embedding Job 2 returned `completed`, progress 100, retry count 0, and no failure reason. Its cost response reported zero calls. All scoped embeddings already existed, so this confirms cached background completion. Calls that create new embeddings through this worker are covered by simulated SDK tests, not by that cached live run.

## Open acceptance work

1. Audit all saved corpus metadata, vectors, and the current cost ledger without changing them.
2. Demonstrate a real low-confidence image and retain its original provider response.
3. Replay the designated fox/wolf, whale/no-match, and review-history cases on the submission database.
4. Make image acquisition repeatable and verify setup on fresh PostgreSQL.
5. Check all API input boundaries, restart recovery expectations, repository status, and the final submission pack.
