import unittest
from pathlib import Path

from query_normalizer import (
    build_metric_terms,
    choose_normalized_query,
    generate_query_candidates,
    load_oral_aliases,
)


class QueryNormalizerRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        aliases = load_oral_aliases(str(Path(__file__).with_name("rural_oral_aliases.json")))
        cls.terms = build_metric_terms(aliases)

    def normalize(self, text):
        candidates = generate_query_candidates(text, self.terms)
        return choose_normalized_query(text, candidates)

    def test_guizhou_oral_alias(self):
        normalized, evidence = self.normalize("\u6d0b\u828b")
        self.assertEqual(normalized, "\u9a6c\u94c3\u85af")
        self.assertIsNotNone(evidence)

    def test_shape_confusion(self):
        normalized, evidence = self.normalize("\u9a6c\u73b2\u85af")
        self.assertEqual(normalized, "\u9a6c\u94c3\u85af")
        self.assertIsNotNone(evidence)

    def test_single_character_is_not_expanded(self):
        normalized, evidence = self.normalize("\u9a6c")
        self.assertEqual(normalized, "\u9a6c")
        self.assertIsNone(evidence)

    def test_low_confidence_alias_is_not_auto_rewritten(self):
        normalized, evidence = self.normalize("\u8352\u74dc")
        self.assertEqual(normalized, "\u8352\u74dc")
        self.assertIsNone(evidence)


if __name__ == "__main__":
    unittest.main()
