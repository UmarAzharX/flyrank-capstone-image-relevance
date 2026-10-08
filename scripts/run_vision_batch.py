import argparse

from app.vision_batch import run_vision_batch


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a bounded number of vision worker steps."
    )
    parser.add_argument("job_id", type=int)
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--pause-seconds", type=int, default=15)
    args = parser.parse_args()

    try:
        succeeded = run_vision_batch(
            args.job_id,
            max_steps=args.max_steps,
            pause_seconds=args.pause_seconds,
        )
    except Exception as exc:
        raise SystemExit(
            f"Batch stopped: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None

    if not succeeded:
        raise SystemExit(1)


if __name__ == "__main__":
    main()