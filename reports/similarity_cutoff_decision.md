# Initial development cutoff decision

Date: 2026-10-10

Chosen initial setting: `SIMILARITY_THRESHOLD=0.70`.

The default in `app/config.py` is 0.70. An explicit setting in `app/.env` can override it. The configured range is 0 to 1 with non-finite values rejected. This is a cosine-similarity threshold, not a probability or the separate vision-confidence threshold of 0.80.

## Evidence

`reports/similarity_cutoff_study_v1.json` compares 10 reference pairs from `data/eval_posts_audited_v1.json` with 10 documented wrong-subject pairs. At 0.70 all 10 reference pairs and all 11 current guard-pass alternatives survive. Nine of the ten selected wrong-subject pairs fall below the threshold. The remaining wrong-subject pair, dog_010 for the wolf post_003 (0.715927), is rejected by the subject guard. Guarded top-1 exact agreement and coverage are both 7/10 = 70% in the simulation.

At 0.75 all ten selected negatives fall below the threshold, but the road-scene alternative fox_008 for post_002 (0.744186) is removed. At 0.80 both top-1 agreement and coverage fall to 3/10. The initial 0.70 decision prioritizes retaining the existing alternatives while combining the cutoff with the other checks.

This is development-set tuning with few posts and repeated negative images. It is not an independent test or a proven deployment optimum. Difficult same-subject context negatives and additional posts would strengthen calibration. The original 50% label baseline and the audited 70% pre-cutoff baseline remain separate, preserved reports.

## Behavior

- Score strictly below the cutoff: reject with an explicit cosine/cutoff explanation.
- Score equal to or above cutoff: this individual check passes; subject, context and vision confidence must also permit selection.
- Missing, Boolean, non-finite or out-of-range cosine score: review; never automatically suggest it.
- Invalid threshold supplied directly to the guard: configuration error.
- Explicit subject/context mismatches still reject even when cosine similarity is high or unavailable.

The combined guard requires both score and cutoff explicitly. All current production callers were updated: suggestion saving (also used by the API), ranking preview, and evaluation. Existing guard fixtures now supply explicit high similarity to keep their tests focused on subject/context/confidence behavior.

The diagnostic cutoff-study script intentionally sets the base similarity threshold to -1.0, then applies each candidate cutoff itself. This keeps its comparison independent of the live cutoff and prevents double-filtering. That diagnostic setting is recorded in future study reports and is never used by production matching.

No schema migration or Gemini request is required. Existing stored explanations receive the additional cutoff explanation when their suggestions are regenerated/reused. This checkpoint does not yet add an API-level no-confident-match reason summary or invalidate historical suggestions after later policy changes; those remain separate follow-ups.

## Verification

88 offline checks passed in the prepared version. They cover score boundaries, invalid values, combined guard precedence, configurable cutoffs, persistence of only eligible candidates, repeated-save reuse, existing guard behavior, selection and evaluation metrics. Persistence tests use an isolated in-memory SQLite database, not the live PostgreSQL database.

The attempted live read-only verification failed to connect with OperationalError, both inside and outside the sandbox. No successful live post-install result is claimed here. Verify the installed version locally with the preview and evaluation commands, saving a new report:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.preview_guarded_ranking post_003 --top-k 5 --eligible-only
.\.venv\Scripts\python.exe -B -m scripts.evaluate_matching --dataset data/eval_posts_audited_v1.json --output reports/evaluation_with_cutoff_v1.json
```

Expected with the current data and cutoff 0.70: wolf_003 remains the passing wolf suggestion, its explanation includes the cutoff, and full-dataset top-1 exact agreement remains 7/10. Treat that as an expectation until the local run succeeds. Restart an already-running API server after installing the files so it loads the new configuration and function signature.
