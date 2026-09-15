# Build Log

This log records how AI assistance was used during development, where its suggestions required correction, and the decisions I made while building the capstone.

## Phase 1 — Design

### AI assistance

AI was used to analyze the FlyRank capstone brief, extract the mandatory requirements, and help structure the initial system design.

It helped with:

- identifying the required image-understanding, semantic-matching, mismatch-guard, background-job, review, evaluation, and cost-tracking requirements
- comparing the allowed technology choices
- proposing an initial Python/FastAPI/PostgreSQL architecture
- drafting the design document and implementation plan
- identifying requirements that were easy to overlook, including idempotency, tenant isolation, failure visibility, the budget guard, and evidence collection

### Corrections and decisions

The first design draft became much more detailed than the brief's requested one-page design document. I kept the detailed material as `docs/IMPLEMENTATION_PLAN.md` and replaced `DESIGN.md` with a concise evaluator-facing design.

The initial wording of the mismatch guard also treated category mismatch too broadly. Since a red fox and a wolf can both belong to the `animal` category, the design was corrected so that subject compatibility is explicitly checked for cases such as fox versus wolf.

A small `app/` scaffold and empty `tests/` directory were created prematurely while editing the design. They were removed because implementation should begin only after the Phase 1 design work is complete.

### Current decisions

- Python + FastAPI
- Pydantic for API and AI-output validation
- PostgreSQL with SQLAlchemy and Alembic
- Docker / Docker Compose for the database environment
- Gemini Flash for image understanding
- Gemini embeddings for semantic matching
- cosine similarity for ranking
- a separate mismatch guard for acceptance/rejection
- no dedicated vector database for the initial small corpus

### Dataset audit correction

After the manifest was populated, an audit showed that only 3 of the 50 referenced image files actually existed locally. The remaining 47 images were then downloaded from their recorded Pexels source pages. A final audit confirmed 50 manifest entries, 50 local images, no missing or unexpected files, no duplicate IDs or filenames, valid JPEG signatures, and 10 images in each of the five planned categories.