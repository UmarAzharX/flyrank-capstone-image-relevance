import unittest

from app.mismatch_guard import evaluate_mismatch
from app.subject_guard import evaluate_subject_match


def check(title, subject, content=""):
    return evaluate_subject_match(
        post_title=title, post_content=content, image_subject=subject
    )


class DogBreedGuardTests(unittest.TestCase):
    def test_same_breed_passes(self):
        self.assertEqual(
            check("Siberian Huskies", "Siberian Husky").decision,
            "pass",
        )

    def test_different_breed_rejected(self):
        self.assertEqual(
            check("Siberian Huskies", "Alaskan Malamute").decision,
            "reject",
        )

    def test_unspecified_breed_needs_review(self):
        for subject in ("Sled dogs", "Dog"):
            with self.subTest(subject=subject):
                self.assertEqual(
                    check("Siberian Huskies", subject).decision,
                    "review",
                )

    def test_general_dog_post_allows_known_breed(self):
        self.assertEqual(
            check("Dogs outdoors", "Alaskan Malamute").decision,
            "pass",
        )

    def test_multiple_breeds_need_review(self):
        for title, subject in (
            ("Huskies and German Shepherds", "Husky"),
            ("Huskies", "Huskies and Malamutes"),
        ):
            with self.subTest(title=title, subject=subject):
                self.assertEqual(
                    check(title, subject).decision,
                    "review",
                )

    def test_breed_requirement_in_content_is_checked(self):
        self.assertEqual(
            check(
                "Dogs in winter",
                "Malamute",
                "Siberian huskies in snow",
            ).decision,
            "reject",
        )

    def test_cold_context_does_not_override_unknown_breed(self):
        result = evaluate_mismatch(
            post_title="Siberian Huskies Built for Cold Weather",
            post_content="Siberian huskies in cold climates.",
            image_subject="Sled dogs",
            image_caption="Sled dogs in snow.",
            image_attributes=[],
            image_confidence=0.99,
            confidence_threshold=0.8,
            similarity_score=0.9,
            similarity_threshold=0.7,
        )
        self.assertEqual(result.decision, "review")


if __name__ == "__main__":
    unittest.main()
