import unittest

from app.mismatch_guard import evaluate_mismatch
from app.subject_guard import evaluate_subject_match


def check(title, subject, content=""):
    return evaluate_subject_match(
        post_title=title, post_content=content, image_subject=subject
    )


class BearSubtypeGuardTests(unittest.TestCase):
    def test_generic_bear_label_needs_review_for_grizzly(self):
        for subject in ("Brown bear", "Bear"):
            with self.subTest(subject=subject):
                self.assertEqual(
                    check("Grizzly bears in snow", subject).decision,
                    "review",
                )

    def test_confirmed_grizzly_passes(self):
        self.assertEqual(
            check("GRIZZLIES in snow", "Grizzly bear").decision,
            "pass",
        )

    def test_requirement_in_content_is_checked(self):
        self.assertEqual(
            check(
                "Bears in snow",
                "Brown bear",
                "Grizzlies in snowy regions.",
            ).decision,
            "review",
        )

    def test_general_bear_post_keeps_matching(self):
        self.assertEqual(
            check("Bears in a forest", "Brown bear").decision,
            "pass",
        )

    def test_different_animal_is_still_rejected(self):
        self.assertEqual(
            check("Grizzly bears", "Wolf").decision,
            "reject",
        )

    def test_snow_and_high_confidence_do_not_confirm_subtype(self):
        result = evaluate_mismatch(
            post_title="Grizzly Bears in a Snowy Habitat",
            post_content="Grizzly bears in cold snowy surroundings.",
            image_subject="Brown bear",
            image_caption="A brown bear in snow.",
            image_attributes=["winter"],
            image_confidence=0.99,
            confidence_threshold=0.8,
            similarity_score=0.9,
            similarity_threshold=0.7,
        )
        self.assertEqual(result.decision, "review")


if __name__ == "__main__":
    unittest.main()
