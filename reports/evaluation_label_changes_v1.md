# Targeted evaluation label corrections, version 1

Date: 2026-10-10

Original dataset: `data/eval_posts.json`
Original dataset SHA-256: `34365f95413e0d0f829908c708a228e325ca2600d5102d8ad6736000fe810a79`
Original report: `reports/evaluation_baseline.json` (5/10 = 50% across all posts)

Revised dataset: `data/eval_posts_audited_v1.json`
Revised dataset SHA-256: `e4d71ffe2d32d367b2d1e12b5850e246caecf8b11b27d3d92d8e78390969a939`

## Relevance rule for these corrections

A reference image must support the article's named subject and requested setting. A generic animal portrait is insufficient evidence of snow. Breed labels require source evidence in addition to appearance; a URL slug alone is insufficient. These are illustrative article images, not proof of every biological statement in the article.

| Post | Original reference | Revised reference | Evidence |
|---|---|---|---|
| post_001 | fox_001 | fox_002 | The inspected local fox_001 photo is a close-up portrait with no visible snow. The inspected fox_002 photo visibly shows a red fox in snow, consistent with its source description. |
| post_005 | dog_001 | dog_010 | The source description identifies dog_001 as an Alaskan Malamute, conflicting with its Husky URL slug and the article's Siberian Husky subject. The inspected dog_010 photo shows three dogs in snow; its source description identifies Siberian Huskies. |

Sources checked:

- fox_002: https://www.pexels.com/photo/red-fox-walking-in-snow-20853949/
- dog_001: https://www.pexels.com/photo/white-and-gray-siberian-husky-6748158/
- dog_010: https://www.pexels.com/photo/dogs-on-snow-during-winter-11764467/

Source descriptions are attribution evidence, not an independent biological breed identification. Local photos were inspected as well. This is an AI-assisted, targeted audit after the original predictions were already observed. The proposed labels require the project owner's review before adoption; they are not blind, independently collected ground truth or an unseen test set.

## What changed and what did not

Only the two expected_image_id fields listed above differ. All 10 post IDs, titles and content are identical to the original dataset. All other expected image IDs remain unchanged. This revised file is separate from the seed dataset; do not reseed posts or regenerate embeddings for these label-only changes.

The engine, guards, vectors, image metadata and stored suggestions were unchanged during verification. The original baseline is retained. Running the same engine against the proposed labels produced 7/10 exact matches (70%) with 7/10 coverage (70%). All 10 predictions were identical to the original baseline. The higher agreement comes from changed reference labels, not an engine improvement. The conditional exact-match rate among returned suggestions is 7/7 = 100%; it is supplementary, not the headline score.

Post_004, post_006 and post_008 still abstain. Their original reference labels have not been changed to remove misses. Summer evidence, home-context policy, and grizzly metadata specificity remain unresolved limitations. The other eight references have not received a full independent blind audit under a finalized relevance policy.

## Reproduction after copying the prepared files

```powershell
.\.venv\Scripts\python.exe -B -m unittest scripts.check_evaluation_metrics scripts.check_evaluation_datasets
.\.venv\Scripts\python.exe -B -m scripts.evaluate_matching --dataset data/eval_posts_audited_v1.json --output reports/evaluation_audited_v1.json
```

The evaluator records the exact dataset path and content hash in the report. Original-label evaluation remains available through the default dataset; use a new output filename because existing reports are never overwritten. No Gemini requests are sent by evaluation. During the proposed checkpoint verification, 9 offline tests passed and the live AI call ledger remained at 113 records.

Similarity cutoff tuning has not started in this checkpoint. Any later tuning on these posts must be described as development-set tuning.
