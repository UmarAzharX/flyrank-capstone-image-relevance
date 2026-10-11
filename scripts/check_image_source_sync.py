"""Check source-link corrections against an isolated SQLite database."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Image, ImageMetadata, Tenant
from scripts.sync_image_sources import CORRECTIONS, sync_sources


class ImageSourceSyncChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.engine = create_engine('sqlite:///:memory:')
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.rows = []
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name='FlyRank Demo'), Tenant(id=2, name='Other tenant')])
            db.flush()
            for i, (external_id, (old, new)) in enumerate(CORRECTIONS.items(), 1):
                data = f'original photo {i}'.encode()
                filename = f'{external_id}.jpg'
                (self.folder / filename).write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                self.rows.append(dict(id=external_id, filename=filename, source_page_url=new,
                                      original_sha256=digest, original_size_bytes=len(data),
                                      download_sha256=digest, download_size_bytes=len(data)))
                for tenant_id in (1, 2):
                    image = Image(tenant_id=tenant_id, external_id=external_id, filename=filename,
                                  source='pexels', source_page_url=old, processing_status='tagged')
                    db.add(image)
                    db.flush()
                    db.add(ImageMetadata(image_id=image.id, subject='Fox', category='Mammal',
                                         attributes=['red fur'], caption='Original caption', confidence=.98, low_confidence=False))

    def state(self):
        with self.sessions() as db:
            images = [dict((column.name, getattr(image, column.name)) for column in Image.__table__.columns)
                      for image in db.scalars(select(Image).order_by(Image.id))]
            metadata = [dict((column.name, getattr(row, column.name)) for column in ImageMetadata.__table__.columns)
                        for row in db.scalars(select(ImageMetadata).order_by(ImageMetadata.id))]
            return images, metadata

    def test_preview_does_not_change_records(self):
        before = self.state()
        with self.sessions.begin() as db:
            self.assertEqual(sync_sources(db, self.rows, self.folder), list(CORRECTIONS))
        self.assertEqual(self.state(), before)

    def test_apply_changes_only_source_links_in_demo_tenant_and_is_repeatable(self):
        images_before, metadata_before = self.state()
        files_before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        with self.sessions.begin() as db:
            self.assertEqual(len(sync_sources(db, self.rows, self.folder, apply=True)), 3)
        with self.sessions.begin() as db:
            self.assertEqual(sync_sources(db, self.rows, self.folder, apply=True), [])
        images_after, metadata_after = self.state()
        for before, after in zip(images_before, images_after):
            if before['tenant_id'] == 1:
                self.assertEqual(after['source_page_url'], CORRECTIONS[before['external_id']][1])
                after['source_page_url'] = before['source_page_url']
            self.assertEqual(after, before)
        self.assertEqual(metadata_after, metadata_before)
        self.assertEqual({p.name: p.read_bytes() for p in self.folder.iterdir()}, files_before)

    def test_unknown_local_file_rolls_back_all_corrections(self):
        before = self.state()
        (self.folder / 'fox_003.jpg').write_bytes(b'unrecognized replacement')
        with self.assertRaises(ValueError), self.sessions.begin() as db:
            sync_sources(db, self.rows, self.folder, apply=True)
        self.assertEqual(self.state(), before)

    def test_unexpected_database_link_rolls_back_all_corrections(self):
        with self.sessions.begin() as db:
            image = db.scalar(select(Image).where(Image.tenant_id == 1, Image.external_id == 'fox_003'))
            image.source_page_url = 'https://example.com/unexpected'
        before = self.state()
        with self.assertRaises(ValueError), self.sessions.begin() as db:
            sync_sources(db, self.rows, self.folder, apply=True)
        self.assertEqual(self.state(), before)


if __name__ == '__main__':
    unittest.main()
