import unittest

from app.mismatch_guard import MismatchGuardResult
from app.ranking import RankedImage
from app.selection import select_eligible_candidates


def candidate(external_id, score, decision):
    image = RankedImage(
        image_id=int(external_id.rsplit("_", 1)[1]),
        external_id=external_id,
        subject="wolf",
        caption="A wolf in snow.",
        attributes=["snow"],
        confidence=0.99,
        similarity_score=score,
    )
    return image, MismatchGuardResult(decision, "Test explanation.")


class SelectionTests(unittest.TestCase):
    def test_filtering_happens_before_limit(self):
        candidates = [
            candidate("img_001", 0.95, "reject"),
            candidate("img_002", 0.90, "review"),
            candidate("img_003", 0.85, "reject"),
            candidate("img_004", 0.70, "pass"),
        ]
        selected = select_eligible_candidates(candidates, limit=1)
        self.assertEqual(
            [image.external_id for image, _ in selected],
            ["img_004"],
        )

    def test_no_eligible_candidates_returns_empty(self):
        candidates = [
            candidate("img_001", 0.95, "reject"),
            candidate("img_002", 0.90, "review"),
        ]
        self.assertEqual(
            select_eligible_candidates(candidates, limit=5),
            [],
        )

    def test_score_order_and_deterministic_ties(self):
        candidates = [
            candidate("img_003", 0.80, "pass"),
            candidate("img_002", 0.90, "pass"),
            candidate("img_001", 0.90, "pass"),
        ]
        selected = select_eligible_candidates(candidates, limit=2)
        self.assertEqual(
            [image.external_id for image, _ in selected],
            ["img_001", "img_002"],
        )

    def test_invalid_limits_are_rejected(self):
        for limit in (0, -1, True, None):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    select_eligible_candidates([], limit=limit)


if __name__ == "__main__":
    unittest.main()
