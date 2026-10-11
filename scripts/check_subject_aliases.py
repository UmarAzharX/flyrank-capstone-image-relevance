import unittest

from app.mismatch_guard import evaluate_mismatch
from app.subject_guard import evaluate_subject_match


def check(title, image_subject, content=""):
    return evaluate_subject_match(
        post_title=title, post_content=content, image_subject=image_subject
    )


class SubjectAliasTests(unittest.TestCase):
    def test_scientific_post_matches_common_image_name(self):
        result = check("Vulpes vulpes in snow", "Red fox")
        self.assertEqual(result.decision, "pass")
        self.assertIn("both describe fox", result.explanation)

    def test_common_post_matches_scientific_image_name(self):
        self.assertEqual(check("Red foxes", "Vulpes vulpes").decision, "pass")

    def test_scientific_names_on_both_sides(self):
        self.assertEqual(check("Vulpes vulpes", "Vulpes vulpes").decision, "pass")

    def test_case_and_whitespace(self):
        for name in ("VULPES VULPES", "Vulpes   vulpes", "Vulpes\tvulpes"):
            with self.subTest(name=name):
                self.assertEqual(check(name, "Red fox").decision, "pass")

    def test_alias_in_post_content(self):
        self.assertEqual(
            check("Wildlife portrait", "Red fox", "A portrait of Vulpes vulpes.").decision,
            "pass",
        )

    def test_wrong_subjects_remain_rejected(self):
        for subject in ("Gray wolf", "Siberian Husky"):
            with self.subTest(subject=subject):
                result = check("Vulpes vulpes", subject)
                self.assertEqual(result.decision, "reject")
                self.assertIn("post describes fox", result.explanation)

    def test_multiple_subjects_still_require_review(self):
        for title, subject in (
            ("Vulpes vulpes and wolves", "Red fox"),
            ("Red fox", "Vulpes vulpes and dog"),
        ):
            with self.subTest(title=title, subject=subject):
                self.assertEqual(check(title, subject).decision, "review")

    def test_partial_or_different_scientific_names_require_review(self):
        for name in ("Vulpes", "Vulpes lagopus", "Vulpes vulpesx", "xVulpes vulpes"):
            with self.subTest(name=name):
                self.assertEqual(check(name, "Red fox").decision, "review")
                self.assertEqual(check("Red fox", name).decision, "review")

    def test_alias_does_not_bypass_other_matching_checks(self):
        options = dict(
            post_title="Vulpes vulpes in snow",
            post_content="",
            image_subject="Red fox",
            image_caption="A red fox standing in snow.",
            image_attributes=["snow"],
            image_confidence=0.99,
            confidence_threshold=0.80,
            similarity_score=0.80,
            similarity_threshold=0.70,
        )
        self.assertEqual(evaluate_mismatch(**options).decision, "pass")
        for changes, expected in (
            ({"image_confidence": 0.50}, "review"),
            ({"similarity_score": 0.60}, "reject"),
            ({"image_caption": "A red fox portrait.", "image_attributes": []}, "review"),
            ({"image_subject": "Gray wolf"}, "reject"),
        ):
            with self.subTest(changes=changes):
                self.assertEqual(evaluate_mismatch(**(options | changes)).decision, expected)


if __name__ == "__main__":
    unittest.main()
