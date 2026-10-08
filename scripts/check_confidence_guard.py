import unittest

from app.confidence_guard import evaluate_vision_confidence


def check(confidence, threshold=0.8):
    return evaluate_vision_confidence(
        confidence=confidence,
        threshold=threshold,
    )


class ConfidenceGuardTests(unittest.TestCase):
    def test_above_threshold_passes(self):
        self.assertEqual(check(0.99).decision, "pass")

    def test_exact_threshold_passes(self):
        self.assertEqual(check(0.8).decision, "pass")

    def test_below_threshold_requires_review(self):
        result = check(0.79)
        self.assertEqual(result.decision, "review")
        self.assertIn("0.790", result.explanation)
        self.assertIn("0.800", result.explanation)

    def test_configurable_threshold_is_used(self):
        self.assertEqual(
            check(0.9, threshold=0.95).decision,
            "review",
        )

    def test_missing_confidence_requires_review(self):
        self.assertEqual(check(None).decision, "review")

    def test_invalid_confidence_requires_review(self):
        for value in (
            True,
            "0.99",
            -0.1,
            1.1,
            float("nan"),
            float("inf"),
        ):
            with self.subTest(value=value):
                self.assertEqual(check(value).decision, "review")

    def test_invalid_threshold_is_rejected(self):
        for threshold in (
            True,
            None,
            -0.1,
            1.1,
            float("nan"),
            float("inf"),
        ):
            with self.subTest(threshold=threshold):
                with self.assertRaises(ValueError):
                    check(0.99, threshold=threshold)


if __name__ == "__main__":
    unittest.main()
