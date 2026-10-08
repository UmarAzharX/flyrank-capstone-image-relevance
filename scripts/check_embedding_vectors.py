import math
import unittest

from app.embedding_vectors import (
    EMBEDDING_DIMENSIONS,
    validate_and_normalize_vector,
)


class EmbeddingVectorChecks(unittest.TestCase):
    def test_valid_vector_is_normalized(self):
        values = [3.0, 4.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2)

        result = validate_and_normalize_vector(values)

        self.assertEqual(len(result), EMBEDDING_DIMENSIONS)
        self.assertAlmostEqual(result[0], 0.6)
        self.assertAlmostEqual(result[1], 0.8)
        self.assertAlmostEqual(math.hypot(*result), 1.0)

    def test_wrong_dimension_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_and_normalize_vector([1.0, 2.0])

    def test_zero_vector_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_and_normalize_vector(
                [0.0] * EMBEDDING_DIMENSIONS
            )

    def test_invalid_values_are_rejected(self):
        for invalid in (True, "0.5", None, float("nan"), float("inf")):
            with self.subTest(value=invalid):
                values = [1.0] * EMBEDDING_DIMENSIONS
                values[0] = invalid

                with self.assertRaises(ValueError):
                    validate_and_normalize_vector(values)


if __name__ == "__main__":
    unittest.main()
