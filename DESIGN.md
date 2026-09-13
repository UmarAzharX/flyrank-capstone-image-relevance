# FlyRank AI Image Relevance Capstone — Design

## Problem

Content systems often need to pair articles with relevant images, but filenames and keyword matching are unreliable because they do not necessarily describe what an image contains. Semantic similarity alone is also unsafe: the highest-ranked candidate can still be wrong, such as a wolf image ranking highly for an article about red foxes.

The system therefore needs to understand image content, rank images semantically against article text, and reject recommendations when the evidence is not strong enough.

## Goal

Build a backend service that:

- processes images with a vision model
- validates structured image metadata before trusting it
- generates and stores image and post embeddings
- ranks images using semantic similarity
- applies a mismatch guard using confidence, subject compatibility, and a tuned similarity threshold
- returns either an explainable recommendation or `no confident match`
- supports background AI processing, retries, progress tracking, cost tracking, and human review

## Non-goal

This project is not intended to become a large-scale image search platform, a full CMS, or a polished frontend application. The capstone will use a small reproducible image corpus and one vision model plus one embedding model, with emphasis on reliability, evaluation, and safe rejection.

## Stack

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- PostgreSQL via Docker / Docker Compose
- Gemini Flash for image understanding
- Gemini Embeddings for semantic representations
- Cosine similarity for ranking
- GitHub public repository

## Data Model

Core persisted entities:

```text
Tenant
├── Images
│   ├── Image Metadata
│   └── Image Embedding
├── Posts
│   ├── Post Embedding
│   └── Suggestions
│       └── Reviews
├── Processing Jobs
└── AI Call Cost Records
```
