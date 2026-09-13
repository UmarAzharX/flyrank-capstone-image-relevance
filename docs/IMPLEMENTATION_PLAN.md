# FlyRank AI Image Relevance Capstone — Design Document

## 1. Problem

Content platforms often need to select relevant images for articles, but filenames and keyword matching are unreliable because they do not necessarily describe what an image actually contains. Semantic similarity alone is also insufficient: the highest-ranked candidate can still be incorrect, such as a wolf image being suggested for an article about red foxes.

The system therefore needs to understand image content, compare that meaning with article content, and reject recommendations when the available evidence is not strong enough to justify a match.

## 2. Goal

Build a backend service that processes an image library with a vision model, stores validated structured metadata and embeddings, and ranks images against article content using semantic similarity.

Before returning a recommendation, the system will apply a mismatch guard that considers image metadata, model confidence, and a similarity threshold. A suitable image should be returned with an explanation of why it was selected, while weak or incompatible candidates should be rejected with a human-readable reason.

The system should also support background AI processing, retries, progress and cost tracking, a simple human review workflow, and evaluation using a small labeled dataset with top-1 precision.

## 3. Non-goal

This project is not intended to become a large-scale image search platform or a full content-management system.

The capstone will use a deliberately small image corpus and focus on reliable AI-assisted matching, rejection behavior, evaluation, and backend engineering. A polished public frontend, large-scale distributed search infrastructure, and support for multiple vision or embedding models are outside the core scope.

## 4. Tech Stack

The project will use the following stack:

| Area | Technology | Purpose |
| --- | --- | --- |
| Language | Python | Backend application and evaluation scripts |
| Web framework | FastAPI | HTTP API and request validation |
| Schema validation | Pydantic | Validation of API input and AI-generated structured metadata |
| ORM | SQLAlchemy | Application-level database access |
| Database migrations | Alembic | Version-controlled PostgreSQL schema changes |
| Database | PostgreSQL | Persistent storage for images, posts, metadata, embeddings, suggestions, reviews, jobs, and AI-call records |
| Database environment | Docker / Docker Compose | Reproducible local PostgreSQL setup |
| Vision model | Gemini Flash | Image understanding and structured metadata generation |
| Embedding model | Gemini Embeddings | Semantic representations of image descriptions and article content |
| Similarity metric | Cosine similarity | Ranking image embeddings against post embeddings |
| API documentation | FastAPI OpenAPI / Swagger UI | Inspecting and testing endpoints during development |
| Version control | Git and GitHub | Public capstone repository and development history |

The project will remain compatible with the capstone's $0 requirement. API credentials will be loaded from environment variables and will never be committed to the repository.

At the intended corpus size, PostgreSQL will store embedding vectors directly. A dedicated vector extension such as pgvector is not required for the initial implementation because the dataset is small enough for straightforward similarity calculations.

## 5. High-Level Architecture

The application will use a layered backend architecture so that HTTP handling, business logic, persistence, and external AI integrations remain separate.

```text
			    Client / Evaluator
				    |
				    v
			    FastAPI HTTP Layer
				    |
		  +---------------+---------------+
		  |                               |
		  v                               v
	   Matching Service                Review / Job Service
		  |                               |
		  +---------------+---------------+
				    |
			    Domain / Logic Layer
				    |
	   +---------------------+----------------------+
	   |                     |                      |
	   v                     v                      v
   Vision Pipeline       Matching Engine        Mismatch Guard
	   |                     |                      |
	   v                     v                      |
   Gemini Vision          Gemini Embeddings            |
	   |                     |                      |
	   +---------------------+----------------------+
				    |
				    v
			      PostgreSQL
				    ^
				    |
			   Background Worker
		      vision + embedding jobs
		      retries + progress
		      cost tracking
```

## 6. Image Metadata Schema

The vision model will produce structured metadata for each processed image. The application will validate every response before storing or using it.

The initial metadata shape is:

```json
{
	"subject": "red fox",
	"category": "animal",
	"attributes": ["orange fur", "wild", "forest"],
	"caption": "A red fox standing in a forest",
	"confidence": 0.94
}
```

## 7. Data Model

PostgreSQL will provide persistent storage. Database changes will be managed through Alembic migrations rather than manual schema edits.

The initial domain model contains the following entities.

### Tenant

Represents an isolated logical owner of posts and images.

Key fields:

- `id`
- `name`
- timestamps

The capstone will seed a single demonstration tenant, but tenant identifiers will be carried through relevant records and queries so that data remains logically isolated.

### Image

Represents an image available to the matching system.

Key fields:

- `id`
- `tenant_id`
- source or local path
- source URL
- processing status
- timestamps

### Image Metadata

Stores the schema-validated output produced by the vision model.

Key fields:

- `id`
- `image_id`
- `subject`
- `category`
- `attributes`
- `caption`
- `confidence`
- low-confidence flag
- timestamps

Each image should have one current validated metadata record for the initial implementation.

### Embedding

Stores semantic vectors generated for images or posts.

Key fields:

- `id`
- `tenant_id`
- owner type
- owner ID
- model identifier
- vector
- timestamps

Image embeddings will be derived from the validated image description. Post embeddings will be derived from article content.

### Post

Represents an article that requires a suitable image.

Key fields:

- `id`
- `tenant_id`
- `title`
- `content`
- timestamps

### Suggestion

Stores a candidate image recommendation for a post together with the information needed to explain the decision.

Key fields:

- `id`
- `tenant_id`
- `post_id`
- `image_id`
- similarity score
- guard decision
- explanation
- timestamps

A suggestion may represent either an accepted candidate or a rejected candidate evaluated by the mismatch guard.

### Review

Records a human decision about a suggestion.

Key fields:

- `id`
- `suggestion_id`
- decision (`approved` or `rejected`)
- optional review note
- timestamps

### Processing Job

Tracks asynchronous image-processing or embedding work.

Key fields:

- `id`
- `tenant_id`
- job type
- status
- progress
- retry count
- failure reason
- timestamps

Jobs will support retries while preserving idempotent behavior.

### AI Call Cost

Records every vision and embedding call.

Key fields:

- `id`
- `tenant_id`
- provider
- model
- operation type
- related job or entity
- usage information
- calculated cost
- timestamps

Calls made within a free tier will still receive an attributed cost record so that the project's usage remains observable.

### Relationships

The main relationships are:

```text
Tenant
├── Posts
├── Images
├── Jobs
└── AI Call Costs

Image
├── Image Metadata
└── Image Embedding

Post
├── Post Embedding
└── Suggestions

Post + Image
	↓
Suggestion
	↓
Review
```

## 8. API Surface

The HTTP API will remain intentionally small and focused on the capstone's required workflows.

### Health

`GET /health`

Returns a simple service-health response so that the application can be checked after startup.

### Images

`POST /images`

Registers an image in the system before AI processing.

`GET /images/{image_id}`

Returns the image record together with its current processing status and validated metadata when available.

### Processing Jobs

`POST /jobs/images/process`

Starts background processing for unprocessed or explicitly selected images.

The endpoint should return quickly with a job identifier rather than waiting for vision and embedding calls to finish.

Example behavior:

```text
request
	↓
202 Accepted
	↓
job_id
```

## 9. Image Processing Pipeline

Image understanding will run through a background-processing pipeline rather than directly inside an ordinary HTTP request.

The pipeline is:

```text
Image registered
	|
	v
Processing job created
	|
	v
Background worker claims image
	|
	v
Vision model called
	|
	v
Structured response received
	|
	v
Pydantic schema validation
	|
	+---------------------------+
	|                           |
	| valid                     | invalid
	v                           v
Confidence check              Retry attempt
	|                           |
	|                           +--> if retries exhausted:
	|                                mark failed / inspect
	|
	+---------------------------+
	|
	v
Store validated metadata
	|
	v
Generate image embedding
	|
	v
Store embedding
	|
	v
Write AI-call cost records
	|
	v
Mark image processing complete
```

## 10. Semantic Matching Strategy

The matching system will compare article content and image descriptions in a shared semantic embedding space.

### Image Representation

Each successfully processed image will have a validated caption and structured metadata. The initial embedding input will be based primarily on the validated image caption, with selected metadata included where useful.

Example:

```text
A red fox standing in a forest. Subject: red fox. Category: animal. Attributes: orange fur, wild, forest.
```

## 11. Mismatch Guard

The mismatch guard is the safety layer between semantic ranking and the final recommendation.

Its purpose is to prevent the system from returning a wrong image simply because that image happened to be the highest-ranked available candidate.

The guard will evaluate each leading candidate using three main signals:

1. vision-model confidence
2. subject/category compatibility
3. semantic similarity score

A candidate must satisfy the configured acceptance rules before it can be returned as a confident match.

### Decision Flow

```text
Ranked candidate
	|
	v
Is image classification confidence acceptable?
	|
   no +-----> REJECT
	|       reason: low confidence
     yes
	|
	v
Is the detected subject/category compatible with the post?
	|
   no +-----> REJECT
	|       reason: subject/category mismatch
     yes
	|
	v
Is semantic similarity above the tuned threshold?
	|
   no +-----> REJECT
	|       reason: similarity below threshold
     yes
	|
	v
ACCEPT
```

## 12. Background Jobs and Retries

Slow AI operations will run outside the normal HTTP request path.

The application will use a background worker pattern for bulk vision processing and embedding generation. API endpoints that start processing will return a job identifier quickly while the actual work continues asynchronously.

### Job Lifecycle

A processing job may move through states such as:

```text
pending
	↓
running
	↓
completed
```

## 13. Cost Tracking and Budget Guard

Every vision and embedding call will produce an attributed AI-call record.

The purpose of cost tracking is to make AI usage observable even when the configured provider is operating within a free tier.

Each record should include enough information to identify:

- provider
- model
- operation type
- related image, post, or job
- usage information when available
- estimated or actual cost
- timestamp

Calls that cost $0 under the free tier will still be recorded.

### Budget Guard

The application will include a configurable AI-usage budget guard.

Before initiating eligible AI calls, the system will check the configured budget or usage limit.

If the configured limit has been reached, the operation should stop safely rather than continuing uncontrolled AI usage.

The exact budget representation will be finalized during implementation, but it will be configurable through environment-based application settings.

The budget guard exists to satisfy the production-reliability requirement while keeping the project compatible with the capstone's $0 constraint.

## 14. Evaluation Plan

The project will include a small labeled evaluation dataset to measure matching quality objectively.

The evaluation set will contain at least 10 posts. Each post will be manually associated with the image considered to be the correct top result.

Conceptually:

```text
post_01 -> image_07
post_02 -> image_14
post_03 -> image_22
...
```

## 15. Dataset Plan

The image corpus will remain deliberately small and reproducible.

The target is approximately 40–50 licensed-free images across at least 4 categories.

The initial planned categories are:

- red fox
- wolf
- dog
- bear
- deer

These categories are intentionally related enough to produce meaningful semantic and visual confusion, which is useful for testing the mismatch guard.

### Image Sources

Images will be collected from licensed-free sources such as Unsplash or Pexels.

The project will record source information for reproducibility and license awareness.

### Dataset Manifest

Rather than depending on undocumented local files, the corpus will use a manifest or equivalent reproducible record containing information such as:

```text
image_id
filename
source URL
source provider
expected category
```

## 16. Security and Secrets

API keys, tokens, passwords, and other secrets will never be stored directly in application source code or committed to Git.

Local secrets will be loaded from environment variables.

The repository will contain:

```text
.env.example
```

## 17. Key Design Decisions

### Python and FastAPI

Python with FastAPI was selected because it provides a simple backend structure and integrates cleanly with Pydantic validation, AI APIs, evaluation tooling, and PostgreSQL access.

### Pydantic for AI Output Validation

Vision-model output is treated as untrusted external data.

Pydantic will validate the structured response before the application stores or uses it.

This separates "the model returned something" from "the application accepts it as valid."

### PostgreSQL Without a Dedicated Vector Database

The corpus is intentionally small, so PostgreSQL can store embeddings without introducing a separate vector database.

Similarity calculations can be performed directly at this scale.

A dedicated vector extension such as pgvector may be reconsidered only if it becomes necessary.

### Ranking and Acceptance Are Separate

Semantic ranking determines which images are most related to a post.

The mismatch guard separately determines whether the highest-ranked candidate is safe enough to recommend.

This prevents the system from treating "best available" as equivalent to "correct."

### Explicit Rejection Is a Valid Result

The system is designed to return "no confident match" when available images do not meet the acceptance criteria.

Safe rejection is treated as successful behavior rather than an error.

### One Vision Model and One Embedding Model

The core implementation will use one vision model and one embedding model.

Model comparison is intentionally excluded from the initial scope because the capstone prioritizes reliability, evaluation, and explainability over breadth.

### Background AI Work Stays Off the Request Path

Bulk vision processing and embedding generation will run as background work with retries, progress tracking, and visible failures.

This keeps slow AI operations separate from normal API response handling.

### Evidence Will Be Collected During Development

`EVIDENCE.md` will be updated as requirements are implemented rather than written only at the end.

Each mandatory requirement should have concrete proof such as:

- test output
- curl transcript
- log output
- evaluation result

This keeps the final submission aligned with the capstone's machine-checkable and behavioral evaluation criteria.