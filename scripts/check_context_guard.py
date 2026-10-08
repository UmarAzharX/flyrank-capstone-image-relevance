import unittest

from app.context_guard import evaluate_winter_context


def check(title, caption, attributes=None, content=""):
    return evaluate_winter_context(
        post_title=title,
        post_content=content,
        image_caption=caption,
        image_attributes=attributes or [],
    )


class ContextGuardTests(unittest.TestCase):
    def test_snow_supports_winter_context(self):
        result = check(
            "Wolves in winter",
            "A wolf outdoors.",
            ["snowy background"],
        )
        self.assertEqual(result.decision, "pass")

    def test_missing_evidence_requires_review(self):
        result = check(
            "Wolves in winter",
            "A wolf lying in tall green grass.",
        )
        self.assertEqual(result.decision, "review")

    def test_explicit_season_conflict_is_rejected(self):
        result = check(
            "Wolves in winter",
            "A wolf in a summer meadow.",
        )
        self.assertEqual(result.decision, "reject")

    def test_snow_requirement_in_content_is_checked(self):
        result = check(
            "Wolves in winter",
            "A winter portrait of a wolf.",
            content="Wolves move through snowy habitats.",
        )
        self.assertEqual(result.decision, "review")

    def test_negated_snow_is_not_positive_evidence(self):
        for caption in (
            "A wolf with no visible snow.",
            "A wolf in a snow-free landscape.",
        ):
            with self.subTest(caption=caption):
                self.assertEqual(
                    check("Wolves in snowy habitats", caption).decision,
                    "review",
                )

    def test_conflicting_image_seasons_require_review(self):
        result = check(
            "Wolves in winter",
            "A winter wolf portrait.",
            ["summer landscape"],
        )
        self.assertEqual(result.decision, "review")

    def test_mixed_post_seasons_require_review(self):
        result = check(
            "Wolves in winter and summer",
            "A wolf in snow.",
        )
        self.assertEqual(result.decision, "review")

    def test_other_contexts_are_not_evaluated(self):
        result = check(
            "Dogs at home",
            "A dog in a living room.",
        )
        self.assertEqual(result.decision, "not_applicable")


if __name__ == "__main__":
    unittest.main()
