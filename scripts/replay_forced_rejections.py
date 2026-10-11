"""Replay the designated forced candidates using saved live image metadata."""

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.mismatch_guard import evaluate_mismatch
from app.models import Image, Tenant
from app.subject_guard import evaluate_subject_match


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cases(cases):
    results = []
    with SessionLocal() as db:
        tenant_id = db.scalar(select(Tenant.id).where(Tenant.name == "FlyRank Demo"))
        if tenant_id is None:
            raise LookupError("Demo tenant not found.")
        for case in cases:
            image = db.scalar(select(Image).where(
                Image.tenant_id == tenant_id,
                Image.external_id == case["forced_candidate_image_id"],
            ))
            if image is None or image.image_metadata is None:
                raise LookupError("Forced candidate metadata not found.")
            metadata = image.image_metadata
            subject = evaluate_subject_match(post_title=case["post_title"],
                                             post_content=case["post_content"],
                                             image_subject=metadata.subject)
            guard = evaluate_mismatch(
                post_title=case["post_title"], post_content=case["post_content"],
                image_subject=metadata.subject, image_caption=metadata.caption,
                image_attributes=metadata.attributes, image_confidence=metadata.confidence,
                confidence_threshold=settings.vision_confidence_threshold,
                # Forced stress input, explicitly not a measured cosine score.
                similarity_score=1.0, similarity_threshold=settings.similarity_threshold,
            )
            passed = (subject.decision == "reject" and guard.decision == case["expected_decision"]
                      and case["expected_reason_contains"].lower() in subject.explanation.lower())
            results.append({"case_id": case["id"], "post_title": case["post_title"],
                            "post_content": case["post_content"], "image_external_id": image.external_id,
                            "image_id": image.id, "saved_subject": metadata.subject,
                            "saved_confidence": metadata.confidence,
                            "subject_decision": subject.decision, "guard_decision": guard.decision,
                            "explanation": guard.explanation,
                            "forced_similarity_score": 1.0, "passed": passed})
    return results


def main():
    try:
        source = (PROJECT_ROOT / "data/guard_cases.json").read_text(encoding="utf-8-sig")
        cases = [case for case in json.loads(source) if case["id"] in {"guard_001", "guard_002"}]
        if {case["id"] for case in cases} != {"guard_001", "guard_002"} or len(cases) != 2:
            raise ValueError("Both designated forced cases are required.")
        results = run_cases(cases)
        report = {"generated_at": datetime.now(timezone.utc).isoformat(),
                  "scope": "Designated fox/wolf and fox/dog guard fixtures with saved live image metadata.",
                  "similarity_input": "Forced 1.0 stress input; not a measured cosine score.",
                  "database_writes": 0, "gemini_requests_sent": 0,
                  "cases": results, "passed": all(row["passed"] for row in results)}
        reports = PROJECT_ROOT / "reports"
        reports.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        output = reports / f"forced_rejections_{stamp}.json"
        with output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, allow_nan=False)
            handle.write("\n")
    except Exception as exc:
        raise SystemExit(f"Replay failed: {type(exc).__name__}. Error details withheld to protect secrets.") from None
    for row in results:
        print(f"{'PASS' if row['passed'] else 'FAIL'}: {row['case_id']} | "
              f"candidate={row['image_external_id']} | subject={row['saved_subject']} | guard={row['guard_decision']}")
        print("Explanation:", row["explanation"])
    print("Similarity was forced to 1.0 for this guard test; it was not measured.")
    print("No database writes or Gemini requests. Evaluation data was not changed.")
    print("Report saved:", output)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
