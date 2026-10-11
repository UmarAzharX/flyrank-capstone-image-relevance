import unittest

from scripts.evaluate_matching import summarize_results


def result(post_id, expected, predicted):
    return {"post_id": post_id, "expected_image_id": expected, "predicted_image_id": predicted}


class EvaluationMetricTests(unittest.TestCase):
    def test_abstentions_remain_in_full_dataset_denominator(self):
        metrics = summarize_results([
            result("post_1", "image_1", "image_1"),
            result("post_2", "image_2", "image_3"),
            result("post_3", "image_4", None),
        ])
        self.assertEqual(metrics["correct_exact_matches"], 1)
        self.assertAlmostEqual(metrics["top1_exact_match_all_posts"], 1 / 3)
        self.assertEqual(metrics["top1_exact_match_returned_posts"], 0.5)
        self.assertAlmostEqual(metrics["coverage"], 2 / 3)

    def test_all_abstentions_are_not_reported_as_perfect_precision(self):
        metrics = summarize_results([result("post_1", "image_1", None)])
        self.assertEqual(metrics["top1_exact_match_all_posts"], 0.0)
        self.assertIsNone(metrics["top1_exact_match_returned_posts"])
        self.assertEqual(metrics["coverage"], 0.0)

    def test_duplicate_posts_cannot_inflate_score(self):
        with self.assertRaises(ValueError):
            summarize_results([result("same", "image_1", "image_1"), result("same", "image_1", "image_1")])

    def test_empty_dataset_is_invalid(self):
        with self.assertRaises(ValueError):
            summarize_results([])

    def test_missing_expected_label_is_not_a_correct_abstention(self):
        with self.assertRaises(ValueError):
            summarize_results([result("post_1", None, None)])


if __name__ == "__main__":
    unittest.main()
