"""Offline checks for safe corpus acquisition. No network or Gemini calls."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock

from scripts.download_images import acquire, load_manifest

JPEG = b"\xff\xd8\xfffixture-jpeg"
URL = "https://images.pexels.com/photos/123/pexels-photo-123.jpeg?auto=compress&cs=tinysrgb&w=1600"


def fixture(data=JPEG):
    digest = hashlib.sha256(data).hexdigest()
    return {"id": "fox_001", "filename": "fox_001.jpg", "source": "pexels",
            "source_page_url": "https://www.pexels.com/photo/fox-123/", "download_url": URL,
            "download_sha256": digest, "download_size_bytes": len(data),
            "original_sha256": digest, "original_size_bytes": len(data)}


class Response(io.BytesIO):
    def __init__(self, data=JPEG, *, url=URL, content_type="image/jpeg"):
        super().__init__(data)
        self.url = url
        self.headers = Message()
        self.headers['Content-Type'] = content_type

    def geturl(self):
        return self.url


class ImageDownloadChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "images"
        self.manifest = self.root / "images.json"
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def load(self, rows):
        self.manifest.write_text(json.dumps(rows))
        return load_manifest(self.manifest)

    def run_acquire(self, rows=None, *, response=None, verify_only=False):
        opener = Mock(return_value=response or Response())
        result = acquire(self.load(rows or [fixture()]), self.folder, opener=opener, verify_only=verify_only)
        return result, opener

    def assert_no_download_file(self):
        self.assertFalse((self.folder / "fox_001.jpg").exists())
        self.assertEqual(list(self.folder.glob("*.part")), [])

    def test_download_then_rerun_reuses_without_network(self):
        rows, first = self.run_acquire()
        first.assert_called_once()
        self.assertEqual(rows[0]['status'], 'downloaded')
        self.assertEqual((self.folder / 'fox_001.jpg').read_bytes(), JPEG)
        rows, second = self.run_acquire()
        second.assert_not_called()
        self.assertEqual(rows[0]['status'], 'verified_existing')

    def test_original_variant_stays_unchanged(self):
        row = fixture()
        original = b'original-version'
        row.update(original_sha256=hashlib.sha256(original).hexdigest(), original_size_bytes=len(original))
        self.folder.mkdir()
        target = self.folder / row['filename']
        target.write_bytes(original)
        before = target.stat().st_mtime_ns
        results, opener = self.run_acquire([row])
        opener.assert_not_called()
        self.assertEqual(results[0]['variant'], 'original')
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(target.stat().st_mtime_ns, before)

    def test_extra_probe_file_is_preserved(self):
        self.folder.mkdir()
        extra = self.folder / 'confidence_probe_001.jpg'
        extra.write_bytes(b'extra-probe')
        self.run_acquire()
        self.assertEqual(extra.read_bytes(), b'extra-probe')

    def test_unknown_existing_file_stops_before_any_download(self):
        self.folder.mkdir()
        (self.folder / 'fox_001.jpg').write_bytes(b'unknown')
        missing = {**fixture(), 'id': 'fox_002', 'filename': 'fox_002.jpg'}
        opener = Mock()
        with self.assertRaises(ValueError):
            acquire(self.load([missing, fixture()]), self.folder, opener=opener)
        opener.assert_not_called()
        self.assertEqual((self.folder / 'fox_001.jpg').read_bytes(), b'unknown')
        self.assertFalse((self.folder / 'fox_002.jpg').exists())

    def test_bad_checksum_leaves_no_file_or_partial(self):
        with self.assertRaises(ValueError):
            self.run_acquire(response=Response(b'\xff\xd8\xffwrong-content'))
        self.assert_no_download_file()

    def test_truncated_download_leaves_no_file_or_partial(self):
        with self.assertRaises(ValueError):
            self.run_acquire(response=Response(JPEG[:-1]))
        self.assert_no_download_file()

    def test_oversized_download_stops_at_recorded_limit(self):
        with self.assertRaises(ValueError):
            self.run_acquire(response=Response(JPEG + b'large'))
        self.assert_no_download_file()

    def test_interrupted_download_cleans_partial(self):
        response = Response()
        response.read = Mock(side_effect=[JPEG[:5], OSError('connection interrupted')])
        with self.assertRaises(OSError):
            self.run_acquire(response=response)
        self.assert_no_download_file()

    def test_concurrent_destination_is_not_overwritten(self):
        response = Response()
        read = response.read
        def race(size):
            (self.folder / 'fox_001.jpg').write_bytes(b'other-writer')
            return read(size)
        response.read = race
        with self.assertRaises(FileExistsError):
            self.run_acquire(response=response)
        self.assertEqual((self.folder / 'fox_001.jpg').read_bytes(), b'other-writer')
        self.assertEqual(list(self.folder.glob('*.part')), [])

    def test_redirect_to_other_host_or_photo_is_rejected(self):
        for url in ('https://example.com/image.jpg', URL.replace('/123/', '/124/').replace('-123.', '-124.')):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.run_acquire(response=Response(url=url))
            self.assert_no_download_file()

    def test_non_image_response_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_acquire(response=Response(content_type='text/html'))
        self.assert_no_download_file()

    def test_non_jpeg_bytes_are_rejected_even_with_matching_checksum(self):
        data = b'not-a-jpeg'
        with self.assertRaises(ValueError):
            self.run_acquire([fixture(data)], response=Response(data))
        self.assert_no_download_file()

    def test_verify_only_missing_file_sends_no_request_and_creates_no_folder(self):
        opener = Mock()
        with self.assertRaises(ValueError):
            acquire(self.load([fixture()]), self.folder, verify_only=True, opener=opener)
        opener.assert_not_called()
        self.assertFalse(self.folder.exists())

    def test_verify_only_known_file_sends_no_request(self):
        self.folder.mkdir()
        (self.folder / 'fox_001.jpg').write_bytes(JPEG)
        result, opener = self.run_acquire(verify_only=True)
        opener.assert_not_called()
        self.assertEqual(len(result), 1)

    def test_unsafe_filenames_are_rejected(self):
        for name in ('../fox.jpg', 'C:\\fox.jpg', 'sub/fox.jpg', '..\\fox.jpg', 'CON.jpg', 'fox.jpg ', 'fox.exe', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.load([{**fixture(), 'filename': name}])

    def test_invalid_sources_and_mismatched_photo_ids_are_rejected(self):
        for changes in ({'download_url': URL.replace('https:', 'http:')},
                        {'download_url': URL.replace('images.pexels.com', 'images.pexels.com.evil.test')},
                        {'download_url': URL.replace('images.pexels.com', 'user@images.pexels.com')},
                        {'source_page_url': 'https://www.pexels.com/photo/fox-999/'},
                        {'source': 'unknown'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.load([{**fixture(), **changes}])

    def test_duplicates_are_rejected_but_same_photo_at_different_sizes_is_allowed(self):
        for second in ({**fixture(), 'filename': 'different.jpg'}, {**fixture(), 'id': 'different', 'filename': 'FOX_001.JPG'}):
            with self.assertRaises(ValueError):
                self.load([fixture(), second])
        self.assertEqual(len(self.load([fixture(), {**fixture(), 'id': 'fox_002', 'filename': 'fox_002.jpg'}])), 2)

    def test_invalid_checksums_and_sizes_are_rejected(self):
        for changes in ({'download_sha256': 'bad'}, {'original_sha256': None},
                        {'download_size_bytes': True}, {'original_size_bytes': 0}, {'download_size_bytes': 100_000_000}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.load([{**fixture(), **changes}])


if __name__ == '__main__':
    unittest.main()
