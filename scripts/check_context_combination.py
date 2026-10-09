import unittest

from app.context_guard import evaluate_context_match


class CombinedContextTests(unittest.TestCase):
    def test_context_policy_cases(self):
        cases = [
            ("home", "Dogs at home", "A dog indoors.", [], "pass"),
            (
                "winter woodland",
                "Wolves in winter forests",
                "A wolf in a snowy forest.",
                [],
                "pass",
            ),
            (
                "missing woodland",
                "Wolves in winter forests",
                "A wolf in snow.",
                [],
                "review",
            ),
            (
                "unconfirmed summer",
                "Wolves in summer grass",
                "A wolf in green grass.",
                [],
                "review",
            ),
            (
                "confirmed summer",
                "Wolves in summer grass",
                "A wolf in summer grassland.",
                [],
                "pass",
            ),
            (
                "autumn",
                "Bears in autumn forests",
                "A bear in woodland.",
                ["autumn foliage"],
                "pass",
            ),
            (
                "season conflict",
                "Wolves in summer grass",
                "A wolf in winter grassland.",
                [],
                "reject",
            ),
            (
                "cold evidence",
                "Dogs in cold climates",
                "Dogs in snow.",
                [],
                "pass",
            ),
            (
                "missing cold evidence",
                "Dogs in cold climates",
                "A dog with thick fur.",
                [],
                "review",
            ),
            (
                "unknown context",
                "Deer beside rivers",
                "A deer beside water.",
                [],
                "not_applicable",
            ),
            (
                "mixed seasons",
                "Wolves in summer and winter",
                "A wolf in snow.",
                [],
                "review",
            ),
            (
                "negated season",
                "Wolves in summer",
                "A wolf in a scene that is not summer.",
                [],
                "review",
            ),
        ]

        for name, title, caption, attributes, expected in cases:
            with self.subTest(case=name):
                result = evaluate_context_match(
                    post_title=title,
                    post_content="",
                    image_caption=caption,
                    image_attributes=attributes,
                )
                self.assertEqual(result.decision, expected)


if __name__ == "__main__":
    unittest.main()
