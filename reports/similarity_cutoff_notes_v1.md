# Similarity cutoff study, version 1

Date: 2026-10-10

This is a development-set diagnostic before any live cutoff is added. It uses the 10 reference pairs in `data/eval_posts_audited_v1.json` and 10 explicitly documented wrong-subject pairs in `data/similarity_negative_pairs_v1.json`. Both files' exact content hashes are recorded in the generated report. The current normalized embedding profile is `gemini-embedding-2:768:retrieval:text-v1`.

Negative pairs were selected by subject mismatch before measuring their scores. The three negative-image photos were inspected locally and their primary source descriptions checked:

- [wolf_003: wolf in snow](https://www.pexels.com/photo/close-up-portrait-of-a-majestic-wolf-in-snow-36129725/)
- [dog_010: Siberian Huskies in snow](https://www.pexels.com/photo/dogs-on-snow-during-winter-11764467/)
- [fox_002: red fox in snow](https://www.pexels.com/photo/red-fox-walking-in-snow-20853949/)

The pairs include wolves for fox articles, Huskies for wolf articles, a wolf for a Husky article, Huskies for a German Shepherd article, and foxes for bear/deer articles. They are AI-assisted development annotations requiring project-owner review, not blind human labels. Many other images could correctly illustrate the same post: non-reference image IDs are NOT automatically negatives. There are repeated images and only 10 posts, so the 20 pair scores are not independent samples. This study does not establish general accuracy, confidence probabilities, or a globally optimal threshold. It does not cover difficult same-subject context mismatches or out-of-domain posts.

## Verified results

| Cutoff | Reference pairs above cutoff | Selected wrong-subject pairs above cutoff | Guarded top-1 exact matches | Coverage | Current guard-pass candidates retained |
|---|---|---|---|---|---|
| 0.50 | 10/10 | 10/10 | 7/10 | 7/10 | 11/11 |
| 0.60 | 10/10 | 10/10 | 7/10 | 7/10 | 11/11 |
| 0.65 | 10/10 | 7/10 | 7/10 | 7/10 | 11/11 |
| 0.70 | 10/10 | 1/10 | 7/10 | 7/10 | 11/11 |
| 0.75 | 10/10 | 0/10 | 7/10 | 7/10 | 10/11 |
| 0.80 | 4/10 | 0/10 | 3/10 | 3/10 | 3/11 |
| 0.85 | 1/10 | 0/10 | 1/10 | 1/10 | 1/11 |
| 0.90 | 0/10 | 0/10 | 0/10 | 0/10 | 0/11 |

Cutoff equality is included: score >= cutoff. Reported calculations use full precision, not rounded console scores. The last three columns simulate a cutoff combined with existing subject, context and vision-confidence guards across all 50 images per post. A high-scoring reference can still fail those other guards: the existing three abstentions remain.

At 0.70 the remaining above-cutoff negative is dog_010 for the wolf article post_003, with cosine score 0.715927. The existing subject guard rejects it. At 0.75 all 10 selected negatives fall below the cutoff, but an existing guard-pass road-scene suggestion, fox_008 for post_002 (0.744186), is also removed. A strict single-reference metric does not reveal that loss of an alternative suggestion.

0.70 is a plausible initial development cutoff if preserving existing eligible alternatives is the priority. 0.75 offers greater separation on these selected wrong-subject pairs but removes that alternative. Neither is a proven deployment optimum. Further same-subject/context negative labels and additional posts would make calibration stronger. Raising a cutoff to 0.80 demonstrably reduces both coverage and top-1 exact agreement here.

## Verification and reproduction

Five offline checks passed: equality at the boundary, a high-scoring negative, invalid/non-finite scores and labels, duplicate or missing classes, and invalid cutoffs. A read-only run against the stored vectors left the AI ledger unchanged at 113 records. No matching code, metadata, vectors, suggestions, or live configuration were changed.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.check_cutoff_study
.\.venv\Scripts\python.exe -B -m scripts.measure_similarity_cutoffs
```

The default output is `reports/similarity_cutoff_study_v1.json`. Existing reports are never overwritten; supply `--output reports/similarity_cutoff_study_v2.json` for a deliberate repeat. The next checkpoint will integrate a chosen cutoff consistently into matching, with boundary tests and explicit reasons for below-cutoff results.
