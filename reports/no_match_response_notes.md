# Explicit no-confident-match responses

Date: 2026-10-10

The existing `POST /posts/{post_id}/suggestions` response now adds three fields:

- `match_status`: `matched` or `no_confident_match`.
- `candidates_checked`: the full number of ranked candidates examined before selection.
- `no_match_reasons`: empty for successful matches; a summary plus the nearest three candidates' actual guard explanations for abstentions.

Existing post ID, created/reused counts and suggestion fields are retained. A completed matching run with no eligible candidate returns HTTP 200, status `no_confident_match`, zero counts and an empty suggestion list. Missing descriptions or embeddings remain HTTP 409 readiness errors. Missing or other-tenant posts remain HTTP 404. Invalid matching post IDs and result limits return HTTP 422. Internal error details are withheld.

Reasons come from the same guard evaluations used for selection, not from a second ranking run or invented fallback explanations. The nearest-three list is bounded and preserves ranked order. It is a diagnostic sample, not a claim that every image failed for an identical reason. Explanations can include subject mismatch, missing required context, low or invalid vision confidence, and insufficient or invalid cosine similarity.

The processing service returns its diagnostics along with persisted suggestion IDs. The original `save_post_suggestions` tuple interface remains available as a wrapper so existing callers continue working. The CLI script uses the richer result and prints the same abstention reasons. This checkpoint sends no AI request and changes no database schema. Completed matching with no eligible candidates creates no new suggestion records.

Verification: 87 offline tests passed, including 12 new no-match/API cases, 53 cutoff/selection/evaluation checks and 22 review checks. These tests used isolated in-memory SQLite databases and FastAPI TestClient. The fixtures verify no AI ledger entries and no suggestions on abstention, exact stored suggestion reuse, configured cutoff behavior, safe errors, input validation and tenant isolation. No new live database verification was attempted for this checkpoint.

The installed live check should use the existing post_004 (summer wolf). With current metadata and policies it should return no confident match, including lack of summer confirmation among its closest candidates' reasons. A post_003 request should remain matched to wolf_003. Numeric API IDs can be confirmed using GET /posts; the previously observed ID for post_004 was 5 and post_003 was 3.

Existing historical suggestion rows are not invalidated by this checkpoint. Current API responses contain only the current run's selected IDs. Review history is preserved; handling historical eligibility after future metadata or policy changes remains a hardening task.
