# Dataset Plan

## Purpose

The image corpus is designed to test semantic image matching and, more importantly, whether the mismatch guard can distinguish visually and semantically related subjects.

The dataset will remain small enough to process using the capstone's free-tier AI stack and to inspect manually.

## Image Corpus

Target size: 50 images.

| Category | Target Images |
| --- | ---: |
| Red fox | 10 |
| Wolf | 10 |
| Dog | 10 |
| Bear | 10 |
| Deer | 10 |
| **Total** | **50** |

The categories intentionally include related animals such as red foxes, wolves, and dogs so that the matching engine cannot succeed through broad category detection alone.

## Image Sources

Images will be collected from licensed-free sources recommended by the capstone brief, such as Unsplash and Pexels.

For each image, the dataset manifest will record:

- internal image ID
- expected subject/category
- source provider
- source page or image URL
- local filename when applicable

The project will not depend on undocumented local files.

## Selection Strategy

The corpus should contain a mixture of:

- clear single-subject images
- different backgrounds and environments
- different poses and viewing angles
- some visually similar fox/wolf/dog examples
- at least one naturally ambiguous image suitable for demonstrating low-confidence handling

Images should not all be near-identical examples of the same subject.

## Evaluation Dataset

The matching evaluation set will contain at least 10 labeled posts.

Each evaluated post will identify one expected correct image so that top-1 precision can be measured.

The initial target is 10–15 labeled matching cases covering the five image categories.

No-match scenarios will be maintained separately from the top-1 labeled set so that the system's rejection behavior can be tested without confusing the top-1 precision metric.

## Negative / Guard Cases

Separate guard-test cases will include:

- fox article with a wolf forced as the candidate
- fox article with a generic dog candidate
- article for which the corpus contains no suitable image
- low-confidence image classification

These cases are intended to verify rejection behavior rather than ordinary top-1 retrieval accuracy.

## Repository Strategy

A small manifest will be committed to the repository.

If storing all source images would make the repository unnecessarily large, the project will use a reproducible download or seed workflow instead of committing a large dataset directly.
