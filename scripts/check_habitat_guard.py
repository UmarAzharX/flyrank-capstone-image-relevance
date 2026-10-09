import unittest

from app.context_guard import evaluate_habitat_context


def check(title, caption, attributes=None):
    return evaluate_habitat_context(
        post_title=title,
        post_content="",
        image_caption=caption,
        image_attributes=attributes or [],
    )


class HabitatGuardTests(unittest.TestCase):
    def test_supported_contexts_pass(self):
        cases = [
            ("Wolves in woodland", "A wolf outdoors.", ["forest"]),
            ("Deer in a meadow", "A deer in green grass.", []),
            ("Dogs at home", "A dog in a living room.", []),
            ("Foxes near roads", "A fox on asphalt.", []),
            ("Close-up deer features", "A close portrait of a deer.", []),
        ]
        for title, caption, attributes in cases:
            with self.subTest(title=title):
                self.assertEqual(
                    check(title, caption, attributes).decision,
                    "pass",
                )

    def test_missing_context_requires_review(self):
        self.assertEqual(
            check("Wolves in forests", "A wolf portrait.").decision,
            "review",
        )

    def test_all_requested_contexts_need_evidence(self):
        self.assertEqual(
            check(
                "Deer in woodland and meadows",
                "A deer in a forest.",
            ).decision,
            "review",
        )

    def test_outdoor_image_rejected_for_indoor_post(self):
        self.assertEqual(
            check("Dogs at home", "A dog outdoors.").decision,
            "reject",
        )

    def test_mixed_indoor_outdoor_evidence_requires_review(self):
        self.assertEqual(
            check(
                "Dogs at home",
                "A dog indoors with an outdoor scene.",
            ).decision,
            "review",
        )

    def test_negated_context_requires_review(self):
        self.assertEqual(
            check(
                "Wolves in forests",
                "A wolf without a forest background.",
            ).decision,
            "review",
        )

    def test_unsupported_context_is_not_applicable(self):
        self.assertEqual(
            check(
                "Deer beside a river",
                "A deer beside water.",
            ).decision,
            "not_applicable",
        )


if __name__ == "__main__":
    unittest.main()
