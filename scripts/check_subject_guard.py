import unittest

from app.subject_guard import evaluate_subject_match


def check(title: str, image_subject: str):
    return evaluate_subject_match(
        post_title=title,
        post_content="",
        image_subject=image_subject,
    )


class SubjectGuardTests(unittest.TestCase):
    def test_matching_subject_with_case_and_plural(self):
        result = check("WOLVES in winter", "Gray wolf")
        self.assertEqual(result.decision, "pass")

    def test_husky_rejected_for_wolf_post(self):
        result = check("Wolves in winter", "Siberian Huskies")
        self.assertEqual(result.decision, "reject")
        self.assertIn("post describes wolf", result.explanation)
        self.assertIn("image describes dog", result.explanation)

    def test_dog_breeds_are_recognized(self):
        for subject in (
            "Siberian Husky",
            "Alaskan Malamute",
            "German Shepherd",
        ):
            with self.subTest(subject=subject):
                self.assertEqual(
                    check("Dogs outdoors", subject).decision,
                    "pass",
                )

    def test_unknown_subject_requires_review(self):
        for title, subject in (
            ("Nature photography", "Red fox"),
            ("Wolves in winter", "Unknown animal"),
        ):
            with self.subTest(title=title, subject=subject):
                self.assertEqual(
                    check(title, subject).decision,
                    "review",
                )

    def test_multiple_subjects_require_review(self):
        for title, subject in (
            ("Wolves and dogs", "Wolf"),
            ("Wolves outdoors", "Wolf and dog"),
        ):
            with self.subTest(title=title, subject=subject):
                self.assertEqual(
                    check(title, subject).decision,
                    "review",
                )

    def test_antelope_is_distinct_from_deer(self):
        self.assertEqual(
            check("Deer in a meadow", "Antelope").decision,
            "reject",
        )

    def test_partial_word_does_not_match(self):
        self.assertEqual(
            check("Foxglove flowers", "Red fox").decision,
            "review",
        )


if __name__ == "__main__":
    unittest.main()
