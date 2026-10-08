import argparse

from app.vision_worker import run_vision_job_once


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Handle at most one image from a vision job."
    )
    parser.add_argument("job_id", type=int)
    args = parser.parse_args()

    try:
        succeeded = run_vision_job_once(args.job_id)
    except Exception as exc:
        raise SystemExit(
            f"Worker could not start or finish: {type(exc).__name__}."
        ) from None

    if not succeeded:
        raise SystemExit(1)


if __name__ == "__main__":
    main()