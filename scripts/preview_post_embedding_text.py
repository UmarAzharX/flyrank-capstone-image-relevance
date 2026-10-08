import argparse
import json
from pathlib import Path

from app.embedding_text import build_post_embedding_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview an evaluation post's embedding input."
    )
    parser.add_argument("external_id", nargs="?", default="post_001")
    args = parser.parse_args()

    posts = json.loads(
        (PROJECT_ROOT / "data" / "eval_posts.json").read_text(
            encoding="utf-8"
        )
    )
    matches = [
        post for post in posts if post["id"] == args.external_id
    ]
    if len(matches) != 1:
        raise SystemExit("Expected exactly one matching post.")

    post = matches[0]
    text = build_post_embedding_text(
        title=post["title"],
        content=post["content"],
    )

    print("Post:", args.external_id)
    print("Embedding input text:")
    print(text)


if __name__ == "__main__":
    main()
