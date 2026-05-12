import unittest

from app.memory import text_embedding, vector_literal


class MemoryVectorTests(unittest.TestCase):
    def test_embedding_is_stable_and_normalized(self):
        first = text_embedding("bad feature flag checkout failure")
        second = text_embedding("bad feature flag checkout failure")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 1536)
        self.assertAlmostEqual(sum(value * value for value in first), 1.0, places=4)

    def test_vector_literal_uses_pgvector_format(self):
        self.assertEqual(vector_literal([0.1, -0.2, 0.0]), "[0.1,-0.2,0.0]")


if __name__ == "__main__":
    unittest.main()
