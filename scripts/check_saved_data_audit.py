"""Audit behavior checks on isolated SQLite, with no provider calls."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
import unittest

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.data_audit import audit_saved_data
from app.database import Base
from app.embedding_vectors import EMBEDDING_PROFILE
from app.models import AICallCost, Embedding, Image, ImageMetadata, Post, ProcessingJob, Tenant
from scripts import audit_saved_data as command


class SavedDataAuditTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.unit = [1.0] + [0.0] * 767
        self.images = [{"id": "fox", "filename": "fox.jpg"}]
        self.posts = [{"id": "post", "title": "Fox", "content": "A red fox."}]
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name="FlyRank Demo"), Tenant(id=2, name="Other")])
            db.flush()
            image = Image(id=1, tenant_id=1, external_id="fox", filename="fox.jpg",
                          source="test", source_page_url="https://example.com", processing_status="tagged")
            image.image_metadata = ImageMetadata(subject="red fox", category="animal", attributes=[],
                                                 caption="A red fox.", confidence=0.99, low_confidence=False)
            db.add_all([image, Image(id=2, tenant_id=2, external_id="fox", filename="other.jpg",
                                     source="test", source_page_url="https://example.com"),
                        Post(id=1, tenant_id=1, external_id="post", title="Fox", content="A red fox."),
                        Post(id=2, tenant_id=1, external_id="probe", title="Vulpes vulpes", content="Probe"),
                        ProcessingJob(id=1, tenant_id=1, job_type="vision", status="completed", progress=100),
                        ProcessingJob(id=2, tenant_id=1, job_type="embedding", status="completed", progress=100),
                        ProcessingJob(id=3, tenant_id=2, job_type="vision", status="completed", progress=100)])
            for owner, owner_id in [("image", 1), ("post", 1), ("post", 2)]:
                db.add(Embedding(tenant_id=1, owner_type=owner, owner_id=owner_id,
                                 model_name=EMBEDDING_PROFILE, vector=self.unit))
            for index, (operation, owner, owner_id) in enumerate([
                ("vision", "image", 1), ("embedding", "image", 1), ("embedding", "post", 1),
            ], 1):
                db.add(AICallCost(id=index, tenant_id=1, provider="google",
                                 model="gemini-3.5-flash-lite" if operation == "vision" else "gemini-embedding-2",
                                 operation_type=operation, related_entity_type=owner, related_entity_id=owner_id,
                                 related_job_id=1 if operation == "vision" else None,
                                 cost_usd=0.0, usage={"call_outcome": "response_received",
                                                      "usage_available": operation == "vision", "billing_tier": "free"}))

    def audit(self):
        with self.sessions() as db:
            report = audit_saved_data(db, image_sources=self.images, post_sources=self.posts,
                                      confidence_threshold=0.8, vision_model="gemini-3.5-flash-lite",
                                      max_calls=200, budget_usd=0.0)
            self.assertFalse(db.new or db.dirty or db.deleted)
            return report

    def codes(self, report, level="errors"):
        return {item["code"] for item in report[level]}

    def test_complete_snapshot_uses_only_selects_and_excludes_probe_from_totals(self):
        statements = []
        event.listen(self.engine, "before_cursor_execute", lambda conn, cur, sql, params, ctx, many: statements.append(sql))
        report = self.audit()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["images"]["schema_valid_metadata"], 1)
        self.assertEqual(report["embeddings"]["valid_evaluation_posts"], 1)
        self.assertEqual(report["embeddings"]["other_valid_current_profile"], 1)
        self.assertEqual(report["costs"]["standalone_records"], 2)
        self.assertEqual(report["gemini_requests_sent"], 0)
        self.assertFalse(report["live_low_confidence_example_present"])
        self.assertTrue(statements)
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql in statements))

    def test_invalid_metadata_is_reported(self):
        with self.sessions.begin() as db:
            db.scalar(select(ImageMetadata)).caption = ""
        self.assertIn("vision_metadata_invalid", self.codes(self.audit()))

    def test_confidence_flag_and_status_must_match_threshold(self):
        with self.sessions.begin() as db:
            db.scalar(select(ImageMetadata)).confidence = 0.6
        report = self.audit()
        self.assertIn("low_confidence_flag_differs", self.codes(report))
        self.assertIn("image_processing_status_differs", self.codes(report))

    def test_flagged_low_confidence_is_counted_without_changing_it(self):
        with self.sessions.begin() as db:
            metadata = db.scalar(select(ImageMetadata))
            metadata.confidence, metadata.low_confidence = 0.6, True
            db.get(Image, 1).processing_status = "needs_review"
        report = self.audit()
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["live_low_confidence_example_present"])
        self.assertEqual(report["images"]["low_confidence_count"], 1)

    def test_invalid_vector_is_detected_without_normalizing_stored_values(self):
        original = [2.0] + [0.0] * 767
        with self.sessions.begin() as db:
            db.scalar(select(Embedding).where(Embedding.owner_type == "image")).vector = original
        report = self.audit()
        self.assertIn("embedding_vector_invalid", self.codes(report))
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(Embedding).where(Embedding.owner_type == "image")).vector, original)

    def test_missing_required_vectors_fail_completion_check(self):
        with self.sessions.begin() as db:
            db.delete(db.scalar(select(Embedding).where(Embedding.owner_type == "post", Embedding.owner_id == 1)))
        self.assertIn("evaluation_embeddings_incomplete", self.codes(self.audit()))

    def test_cross_tenant_owner_and_job_links_are_rejected(self):
        with self.sessions.begin() as db:
            record = db.get(AICallCost, 1)
            record.related_entity_id, record.related_job_id = 2, 3
            db.scalar(select(Embedding).where(Embedding.owner_type == "image")).owner_id = 2
        codes = self.codes(self.audit())
        self.assertIn("ledger_owner_not_in_tenant", codes)
        self.assertIn("ledger_job_not_in_tenant_or_wrong_type", codes)
        self.assertIn("embedding_owner_not_in_tenant", codes)

    def test_unfinished_reservation_requires_review(self):
        with self.sessions.begin() as db:
            db.get(AICallCost, 3).usage = {"call_outcome": "reserved", "usage_available": False, "billing_tier": "free"}
        report = self.audit()
        self.assertEqual(report["status"], "review")
        self.assertIn("ledger_reservation_unfinished", self.codes(report, "warnings"))

    def test_unknown_legacy_outcome_is_not_claimed_as_success(self):
        with self.sessions.begin() as db:
            db.get(AICallCost, 3).usage = {"usage_available": False, "billing_tier": "free"}
        report = self.audit()
        self.assertIn("ledger_outcome_unknown_or_legacy", self.codes(report, "warnings"))
        self.assertEqual(report["costs"]["scoped_owners_without_embedding_response_record"], 1)

    def test_raw_usage_and_private_text_are_not_exported(self):
        with self.sessions.begin() as db:
            db.get(AICallCost, 3).usage = {"call_outcome": "response_received", "usage_available": False,
                                         "billing_tier": "free", "private": "PRIVATE_TEST_MARKER"}
        encoded = json.dumps(self.audit(), allow_nan=False)
        self.assertNotIn("PRIVATE_TEST_MARKER", encoded)
        self.assertNotIn("https://example.com", encoded)

    def test_changed_post_source_is_reported(self):
        self.posts[0]["title"] = "Changed"
        self.assertIn("evaluation_post_text_differs", self.codes(self.audit()))

    def test_other_tenant_costs_do_not_affect_demo_totals(self):
        with self.sessions.begin() as db:
            db.add(AICallCost(tenant_id=2, provider="other", model="other", operation_type="other",
                             usage={}, cost_usd=999))
        self.assertEqual(self.audit()["costs"]["record_count"], 3)

    def test_postgresql_wrapper_requests_readonly_repeatable_read(self):
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        connection = engine.connect.return_value.execution_options.return_value.__enter__.return_value
        with self.sessions() as db, patch.object(command, "Session") as session_factory:
            session_factory.return_value.__enter__.return_value = db
            report = command.audit_database(database_engine=engine, image_sources=self.images, post_sources=self.posts)
        engine.connect.return_value.execution_options.assert_called_once_with(
            isolation_level="REPEATABLE READ", postgresql_readonly=True,
        )
        session_factory.assert_called_once_with(bind=connection, autoflush=False)
        self.assertEqual(report["status"], "pass")

    def test_report_paths_reject_escape_and_existing_files(self):
        with TemporaryDirectory() as folder, patch.object(command, "PROJECT_ROOT", Path(folder)):
            reports = Path(folder)/"reports"
            reports.mkdir()
            existing = reports/"existing.json"
            existing.write_text("original", encoding="utf-8")
            for value in ["../escape.json", "data/report.json", "reports/report.txt"]:
                with self.assertRaises(ValueError):
                    command.output_path(value)
            with self.assertRaises(FileExistsError):
                command.output_path("reports/existing.json")
            self.assertEqual(existing.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
