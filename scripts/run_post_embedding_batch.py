import argparse
import json
from pathlib import Path

from google.genai import errors

from app.budget import AIUsageLimitError
from app.post_embedding_batch import run_post_embedding_batch


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="Embed remaining evaluation posts with bounded retries.")
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--pause-seconds", type=int, default=15)
    args = parser.parse_args()
    if not 1 <= args.max_steps <= 10:
        parser.error("--max-steps must be between 1 and 10.")
    if not 0 <= args.pause_seconds <= 60:
        parser.error("--pause-seconds must be between 0 and 60.")
    try:
        sources = json.loads((PROJECT_ROOT / "data" / "eval_posts.json").read_text(encoding="utf-8"))
        run_post_embedding_batch(sources=sources, max_steps=args.max_steps,
                                 pause_seconds=args.pause_seconds)
    except KeyboardInterrupt:
        raise SystemExit("Batch interrupted. Rerun to continue.") from None
    except AIUsageLimitError as exc:
        raise SystemExit(f"Post embedding batch blocked: {exc}") from None
    except errors.APIError as exc:
        raise SystemExit(f"Post embedding batch stopped: HTTP {exc.code}.") from None
    except Exception as exc:
        raise SystemExit(f"Post batch failed: {type(exc).__name__}. Error details withheld to protect secrets.") from None


if __name__ == "__main__":
    main()
