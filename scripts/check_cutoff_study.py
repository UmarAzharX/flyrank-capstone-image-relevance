import unittest

from scripts.measure_similarity_cutoffs import pair_counts


def pair(image_id, relevant, score):
    return {"post_id": "post_1", "image_id": image_id, "relevant": relevant, "similarity_score": score}


class CutoffStudyTests(unittest.TestCase):
    def test_cutoff_equality_is_included(self):
        result = pair_counts([pair("good", True, 0.7), pair("bad", False, 0.69999)], 0.7)
        self.assertEqual(result["reference_pairs_above_cutoff"], 1)
        self.assertEqual(result["negative_pairs_above_cutoff"], 0)

    def test_high_wrong_subject_score_still_counts_as_negative(self):
        result = pair_counts([pair("good", True, 0.7), pair("bad", False, 0.9)], 0.8)
        self.assertEqual(result["reference_pairs_above_cutoff"], 0)
        self.assertEqual(result["negative_pairs_above_cutoff"], 1)
        self.assertEqual(result["reference_pair_count"], 1)

    def test_invalid_scores_and_labels_are_rejected(self):
        for invalid in [True, float("nan"), float("inf"), -1.01, 1.01, "0.7"]:
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                pair_counts([pair("good", True, invalid), pair("bad", False, 0.5)], 0.7)
        with self.assertRaises(ValueError):
            pair_counts([pair("good", 1, 0.8), pair("bad", False, 0.5)], 0.7)

    def test_duplicates_and_missing_classes_are_rejected(self):
        for rows in [[], [pair("good", True, 0.8)], [pair("bad", False, 0.5)], [pair("same", True, 0.8), pair("same", False, 0.5)]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                pair_counts(rows, 0.7)

    def test_invalid_cutoff_is_rejected(self):
        for cutoff in [True, float("nan"), float("inf"), -1.01, 1.01, "0.7"]:
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                pair_counts([pair("good", True, 0.8), pair("bad", False, 0.5)], cutoff)


if __name__ == "__main__":
    unittest.main()
