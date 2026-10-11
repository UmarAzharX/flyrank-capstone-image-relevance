"""Isolated registration checks; no live database or AI requests."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Image, Tenant
from scripts import register_confidence_probe as command


class ConfidenceProbeRegistrationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "data/images").mkdir(parents=True)
        (self.root / "data/images.json").write_text(json.dumps([
            {"id": "fox_001", "filename": "fox_001.jpg"},
        ]), encoding="utf-8")
        self.photo = self.root / "data/images/uncertain_002.jpg"
        # Bytes test the format and hash gate; this fixture is not a real photo.
        self.photo.write_bytes(b"\xff\xd8\xffisolated-fixture")
        self.candidate = {
            "id": "confidence_probe_001", "filename": self.photo.name,
            "source": "pexels", "source_page_url": "https://www.pexels.com/photo/test-123/",
            "sha256": hashlib.sha256(self.photo.read_bytes()).hexdigest(),
        }
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name="FlyRank Demo"), Tenant(id=2, name="Other")])
        for name, value in (("PROJECT_ROOT", self.root), ("IMAGE_ROOT", self.photo.parent),
                            ("SessionLocal", self.sessions)):
            p = patch.object(command, name, value)
            p.start()
            self.addCleanup(p.stop)

    def count(self):
        with self.sessions() as db:
            return db.scalar(select(func.count()).select_from(Image))

    def test_registration_is_committed_and_repeat_reuses_record(self):
        image_id, created = command.register_candidate(self.candidate)
        self.assertTrue(created)
        self.assertEqual(command.register_candidate(self.candidate), (image_id, False))
        self.assertEqual(self.count(), 1)
        with self.sessions() as db:
            image = db.get(Image, image_id)
            self.assertEqual(image.tenant_id, 1)
            self.assertEqual(image.processing_status, "pending")
            self.assertIsNone(image.image_metadata)

    def test_changed_bytes_are_blocked_before_registration(self):
        self.photo.write_bytes(b"\xff\xd8\xffchanged")
        with self.assertRaises(ValueError):
            command.register_candidate(self.candidate)
        self.assertEqual(self.count(), 0)

    def test_non_jpeg_is_blocked_even_with_matching_hash(self):
        self.photo.write_bytes(b"not a JPEG")
        self.candidate["sha256"] = hashlib.sha256(self.photo.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            command.register_candidate(self.candidate)
        self.assertEqual(self.count(), 0)

    def test_existing_different_source_is_not_overwritten(self):
        image_id, _ = command.register_candidate(self.candidate)
        with self.sessions.begin() as db:
            db.get(Image, image_id).source = "different"
        with self.assertRaises(ValueError):
            command.register_candidate(self.candidate)
        with self.sessions() as db:
            self.assertEqual(db.get(Image, image_id).source, "different")

    def test_other_tenant_candidate_is_not_reused(self):
        with self.sessions.begin() as db:
            db.add(Image(tenant_id=2, external_id=self.candidate["id"], filename="other.jpg",
                         source="other", source_page_url="https://example.com"))
        image_id, created = command.register_candidate(self.candidate)
        self.assertTrue(created)
        with self.sessions() as db:
            self.assertEqual(db.get(Image, image_id).tenant_id, 1)
        self.assertEqual(self.count(), 2)

    def test_evaluation_corpus_collision_is_blocked(self):
        manifest = self.root / "data/images.json"
        manifest.write_text(json.dumps([self.candidate]), encoding="utf-8")
        original = manifest.read_bytes()
        with self.assertRaises(ValueError):
            command.register_candidate(self.candidate)
        self.assertEqual(manifest.read_bytes(), original)
        self.assertEqual(self.count(), 0)

    def test_fog_candidate_is_separate_and_repeat_preserves_original(self):
        original_id, _ = command.register_candidate(self.candidate)
        original_manifest = (self.root / "data/images.json").read_bytes()
        fog_photo = self.photo.with_name("uncertain_fog_001.jpg")
        fog_photo.write_bytes(b"\xff\xd8\xfffog-fixture")
        fog = dict(self.candidate, id="confidence_probe_fog_001", filename=fog_photo.name,
                   sha256=hashlib.sha256(fog_photo.read_bytes()).hexdigest())
        fog_id, created = command.register_candidate(fog)
        self.assertTrue(created)
        self.assertNotEqual(fog_id, original_id)
        self.assertEqual(command.register_candidate(fog), (fog_id, False))
        self.assertEqual(self.count(), 2)
        self.assertEqual((self.root / "data/images.json").read_bytes(), original_manifest)
        with self.sessions() as db:
            original = db.get(Image, original_id)
            self.assertEqual(original.filename, "uncertain_002.jpg")
            self.assertEqual(original.processing_status, "pending")
            self.assertIsNone(original.image_metadata)

    def test_unknown_candidate_is_blocked(self):
        self.candidate["id"] = "unapproved_candidate"
        with self.assertRaises(ValueError):
            command.register_candidate(self.candidate)
        self.assertEqual(self.count(), 0)

    def test_known_id_with_wrong_filename_is_blocked(self):
        self.candidate["id"] = "confidence_probe_fog_001"
        with self.assertRaises(ValueError):
            command.register_candidate(self.candidate)
        self.assertEqual(self.count(), 0)


if __name__ == "__main__":
    unittest.main()
