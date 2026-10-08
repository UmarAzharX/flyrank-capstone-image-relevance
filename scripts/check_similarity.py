import unittest

from app.embedding_vectors import EMBEDDING_DIMENSIONS
from app.similarity import cosine_similarity


def vector(x: float, y: float = 0.0) -> list[float]:
    return [x, y] + [0.0] * (EMBEDDING_DIMENSIONS - 2)


class SimilarityTests(unittest.TestCase):
    def test_identical_direction(self):
        self.assertAlmostEqual(
            cosine_similarity(vector(1), vector(1)), 1.0
        )

    def test_perpendicular_directions(self):
        self.assertAlmostEqual(
            cosine_similarity(vector(1), vector(0, 1)), 0.0
        )

    def test_opposite_directions(self):
        self.assertAlmostEqual(
            cosine_similarity(vector(1), vector(-1)), -1.0
        )

    def test_lengths_do_not_change_similarity(self):
        self.assertAlmostEqual(
            cosine_similarity(vector(30, 40), vector(2)), 0.6
        )

    def test_invalid_vectors_are_rejected(self):
        invalid_vectors = [
            [1.0],
            vector(0),
            vector(float("nan")),
            vector(float("inf")),
            vector(True),
        ]
        for invalid in invalid_vectors:
            with self.subTest(invalid=invalid[:2]):
                with self.assertRaises(ValueError):
                    cosine_similarity(vector(1), invalid)


if __name__ == "__main__":
    unittest.main()
