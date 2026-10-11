import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts import evaluate_matching as evaluator


class EvaluationDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "data").mkdir()
        self.root_patch = patch.object(evaluator, "PROJECT_ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.post = {"id": "post_1", "title": "Fox in snow", "content": "A red fox in winter.", "expected_image_id": "fox_a"}
        (self.root / "data/images.json").write_text(json.dumps([{"id": "fox_a"}, {"id": "fox_b"}]), encoding="utf-8")
        self.write_dataset("original.json", "fox_a")
        self.write_dataset("revised.json", "fox_b")

    def write_dataset(self, filename, expected):
        row = dict(self.post, expected_image_id=expected)
        (self.root / "data" / filename).write_text(json.dumps([row]), encoding="utf-8")

    def evaluate_fixture(self, filename):
        db = MagicMock()
        db.scalar.return_value = 1
        db.scalars.return_value.all.return_value = [SimpleNamespace(external_id="post_1", title=self.post["title"], content=self.post["content"])]
        session = MagicMock()
        session.__enter__.return_value = db
        candidates = [
            SimpleNamespace(image_id=2, external_id="fox_b", subject="fox", caption="Fox in snow", attributes=["snow"], confidence=0.99, similarity_score=0.85),
            SimpleNamespace(image_id=1, external_id="fox_a", subject="fox", caption="Fox in snow", attributes=["snow"], confidence=0.99, similarity_score=0.75),
        ]
        with patch.object(evaluator, "SessionLocal", return_value=session), patch.object(evaluator, "rank_images_for_post", return_value=candidates) as ranking, patch.object(evaluator, "evaluate_mismatch", return_value=SimpleNamespace(decision="pass", explanation="Fixture: eligible.")):
            report = evaluator.evaluate("data/" + filename)
            # Gold image IDs never enter the ranking function.
            ranking.assert_called_once_with(tenant_id=1, external_id="post_1", corpus_ids={"fox_a", "fox_b"}, top_k=2)
        return report

    def test_relabel_changes_score_but_not_prediction(self):
        original = self.evaluate_fixture("original.json")
        revised = self.evaluate_fixture("revised.json")
        self.assertEqual(original["results"][0]["predicted_image_id"], "fox_b")
        self.assertEqual(revised["results"][0]["predicted_image_id"], "fox_b")
        self.assertEqual(original["metrics"]["top1_exact_match_all_posts"], 0)
        self.assertEqual(revised["metrics"]["top1_exact_match_all_posts"], 1)
        self.assertNotEqual(original["dataset_sha256"], revised["dataset_sha256"])

    def test_report_records_exact_source_and_hash(self):
        report = self.evaluate_fixture("original.json")
        self.assertEqual(report["dataset_path"], "data/original.json")
        self.assertEqual(report["dataset_sha256"], hashlib.sha256((self.root / "data/original.json").read_bytes()).hexdigest())

    def test_dataset_cannot_escape_data_directory(self):
        for value in ["../outside.json", "data/../../outside.json", "reports/not_data.json", "data/not_json.txt", str(self.root.parent / "outside.json")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                evaluator.resolve_dataset_path(value)

    def test_changed_post_text_cannot_use_stale_embeddings(self):
        row = dict(self.post, title="Changed title")
        (self.root / "data/original.json").write_text(json.dumps([row]), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Stored post text differs"):
            self.evaluate_fixture("original.json")


if __name__ == "__main__":
    unittest.main()
