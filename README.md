# FlyRank AI Image Relevance Capstone

A FastAPI backend that uses Gemini to describe images and match them to articles. It checks each match and explains why an image is suggested or refused. PostgreSQL stores the results, processing jobs, AI call costs, and human review history.

## Results

The development dataset contains **50 image records across five animal groups** (49 distinct photographs) and **10 labeled posts**.

| Metric | Recorded result |
| --- | ---: |
| First suggestion matches the labeled image, across all posts | **7/10 (70%)** |
| Coverage: posts receiving a suggestion | **7/10 (70%)** |
| Exact-image match among returned suggestions | **7/7 (100%)** |
| Offline tests | **257 passed** |

The top-1 accuracy is **70%**. Posts with no suggestion count as incorrect results. The original labels produced 50% accuracy. An AI-assisted review after inspecting predictions corrected two labels, raising the measured result to 70%. Post text and embeddings stayed unchanged. The increase reflects corrected labels. Performance on new data remains untested. See the [evaluation guide](docs/SETUP.md#tests-and-evaluation) and [recorded report](reports/evaluation_with_cutoff_v1.json).

## Architecture

```text
Local images --> Vision job --> Checked tags, caption, confidence
                                         |
                                         v
                                  Image embeddings
                                         |
Posts --> Post embeddings --------------> Similarity ranking
                                         |
                      Subject, context, confidence, similarity checks
                                         |
                            Suggestions OR no confident match
                                         |
                           Human review: accept / reject / history

PostgreSQL stores metadata, vectors, suggestions, reviews, jobs, and costs.
FastAPI validates requests and starts background tasks.
```

The project uses Python, FastAPI, Pydantic, SQLAlchemy, Alembic, and PostgreSQL 16. Vision uses `gemini-3.5-flash-lite`. Embeddings use `gemini-embedding-2`.

An embedding represents an image description or article as a list of numbers. The system stores 768 normalized values for each embedding and compares them using cosine similarity. It then checks the subject, context, and confidence before suggesting a match. See [DESIGN.md](DESIGN.md) for the design.

## Quick start (Windows PowerShell)

The tested environment uses Python **3.14.6**. Run commands from the project folder with Docker running.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -c requirements-tested.txt
```

For a new installation, copy `.env.example` to **`app/.env`**. Set `DATABASE_URL` for your local database and add your free-tier `GEMINI_API_KEY`. Keep this file out of Git. If `app/.env` already exists, keep it. Default limits are 200 AI calls, a USD 0 budget, a vision-confidence threshold of 0.80, and a similarity cutoff of 0.70.

```powershell
docker compose up -d db
```

Once PostgreSQL accepts connections, create the database tables, add image records, and start the API:

```powershell
.\.venv\Scripts\python.exe -B -m alembic upgrade head
.\.venv\Scripts\python.exe -B -m scripts.seed
.\.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [Swagger](http://127.0.0.1:8000/docs) to explore the API. The seed command adds image records. Download missing photos with `python -B -m scripts.download_images` using the project environment. Existing verified files are preserved. Follow the [setup guide](docs/SETUP.md) to process images, add posts, and generate embeddings. Photos are excluded from Git; source links and file checksums are recorded in `data/images.json`.

Use `POST /posts/{post_id}/suggestions` to find matches. Use `POST /suggestions/{suggestion_id}/reviews` to accept or reject a suggestion. Matching uses saved embeddings without new Gemini calls. The [API guide](docs/API.md) lists the endpoints, job controls, and review examples.

## Tests and evaluation

```powershell
.\.venv\Scripts\python.exe -B -m scripts.run_checks
```

All **257 offline tests passed**. They use separate SQLite test databases and simulated AI responses, with no Gemini requests. After saving the image descriptions and embeddings, run the labeled evaluation:

```powershell
$evaluationStamp = Get-Date -Format "yyyyMMdd_HHmmss_fffffff"
.\.venv\Scripts\python.exe -B -m scripts.evaluate_matching --dataset data/eval_posts_audited_v1.json --output "reports/evaluation_audited_$evaluationStamp.json"
```

Each run uses a new filename to preserve earlier reports. New AI responses can change the recorded result. The [evaluation guide](docs/SETUP.md#tests-and-evaluation) explains label corrections, the similarity cutoff, and the separate `Vulpes vulpes` test.

## Submission status

The main pipeline and offline tests are working. [EVIDENCE.md](EVIDENCE.md), [BUILDLOG.md](BUILDLOG.md), and [capstone.yaml](capstone.yaml) record the results, development decisions, and evaluator commands. Final acceptance checks and a real low-confidence image example remain pending. Repeatable image downloads and fresh PostgreSQL database setup passed verification. The code uses the [MIT license](LICENSE). Source photographs have separate licensing terms.

## Limitations

- **Limited evaluation:** ten development posts provide only a small accuracy sample. English matching rules can refuse suggestions when evidence is missing and do not fully check actions. Confidence and similarity scores do not measure the probability of a correct match.
- **Interrupted jobs:** restarting the server can leave background jobs unfinished. A manual recovery command is available after all workers are stopped. Automatic recovery is not implemented.
- **Demo access and scale:** API routes use one fixed tenant without authentication. Embeddings are compared in memory. Simultaneous requests have not been verified against live PostgreSQL.
- **Stored data and cost gaps:** changed inputs do not automatically refresh embeddings. Costs assume free-tier billing. The provider did not report token usage for live embedding calls.
- **Reproducibility and live confidence:** some newly downloaded JPEGs have small encoding differences from the originals; historical AI results are not guaranteed to repeat. Low-confidence handling passed simulated tests, but all 50 corpus results and both separate live candidates were above the confidence threshold. See the [API guide](docs/API.md#operational-limitations) for details.

## Future Improvements

- Add a persistent job queue, automatic recovery, and clear failure alerts.
- Authenticate users and tenant access, and strengthen checks against duplicate or invalid database records.
- Expand the image collection and independently labeled evaluation set. Improve checks for animal subtypes, context, and actions.
- Track input and prompt changes to refresh old embeddings. Improve search performance as the image collection grows.
- Add automated fresh-install checks, improve usage reporting, and add a simple review interface.
