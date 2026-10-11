import unittest

from app.mismatch_guard import evaluate_mismatch


def check(
    subject,
    caption,
    title="Wolves in winter",
    confidence=0.99,
    threshold=0.8,
):
    return evaluate_mismatch(
        post_title=title,
        post_content="",
        image_subject=subject,
        image_caption=caption,
        image_attributes=[],
        image_confidence=confidence,
        confidence_threshold=threshold,
        similarity_score=0.9,
        similarity_threshold=0.7,
    )


class MismatchGuardTests(unittest.TestCase):
    def test_matching_subject_and_context_pass(self):
        self.assertEqual(
            check("Wolf", "A wolf in snow.").decision,
            "pass",
        )

    def test_snow_does_not_override_subject_mismatch(self):
        self.assertEqual(
            check("Siberian Huskies", "Dogs in snow.").decision,
            "reject",
        )

    def test_subject_rejection_beats_context_review(self):
        self.assertEqual(
            check("Dog", "An outdoor portrait.").decision,
            "reject",
        )

    def test_matching_subject_with_missing_context_needs_review(self):
        self.assertEqual(
            check("Wolf", "A wolf in green grass.").decision,
            "review",
        )

    def test_season_rejection_beats_unknown_subject(self):
        self.assertEqual(
            check("Unknown animal", "A summer meadow.").decision,
            "reject",
        )

    def test_uncovered_context_needs_review(self):
        self.assertEqual(
            check(
                "Dog",
                "A dog beside water.",
                title="Dogs beside rivers",
            ).decision,
            "review",
        )

    def test_home_context_can_pass(self):
        self.assertEqual(
            check(
                "Dog",
                "A dog in a living room.",
                title="Dogs at home",
            ).decision,
            "pass",
        )

    def test_low_confidence_prevents_pass(self):
        self.assertEqual(
            check(
                "Wolf", "A wolf in snow.", confidence=0.65
            ).decision,
            "review",
        )

    def test_low_confidence_preserves_explicit_rejection(self):
        self.assertEqual(
            check(
                "Dog", "A dog in snow.", confidence=0.65
            ).decision,
            "reject",
        )

    def test_configured_threshold_reaches_combined_guard(self):
        self.assertEqual(
            check(
                "Wolf",
                "A wolf in snow.",
                confidence=0.9,
                threshold=0.95,
            ).decision,
            "review",
        )

    def test_missing_confidence_prevents_pass(self):
        self.assertEqual(
            check(
                "Wolf", "A wolf in snow.", confidence=None
            ).decision,
            "review",
        )


if __name__ == "__main__":
    unittest.main()
