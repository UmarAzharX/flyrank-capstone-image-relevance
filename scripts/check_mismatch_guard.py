import unittest

from app.mismatch_guard import evaluate_mismatch


def check(subject, caption, title="Wolves in winter"):
    return evaluate_mismatch(
        post_title=title,
        post_content="",
        image_subject=subject,
        image_caption=caption,
        image_attributes=[],
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
                "A dog in a living room.",
                title="Dogs at home",
            ).decision,
            "review",
        )


if __name__ == "__main__":
    unittest.main()
