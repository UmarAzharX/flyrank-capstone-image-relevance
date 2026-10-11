"""Exercise create-request validation through isolated HTTP routes."""

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Image, Post, Tenant
from app.routes.images import router as image_router
from app.routes.posts import router as post_router


class CreateInputTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions.begin() as db:
            db.add(Tenant(name="FlyRank Demo"))
        app = FastAPI()
        app.include_router(image_router)
        app.include_router(post_router)

        def test_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = test_db
        self.client = TestClient(app)
        self.image = {"external_id": "fixture_image", "filename": "fox.jpg", "source": "fixture",
                      "source_page_url": "https://example.com/photo"}
        self.post = {"external_id": "fixture_post", "title": "Red fox", "content": "A fox in snow."}

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def assert_empty(self):
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count(Image.id))), 0)
            self.assertEqual(db.scalar(select(func.count(Post.id))), 0)

    def reject(self, endpoint, payload):
        self.assertEqual(self.client.post(endpoint, json=payload).status_code, 422)
        self.assert_empty()

    def test_blank_required_text_never_persists(self):
        for path, base, fields in (
            ("/images", self.image, ("external_id", "filename", "source")),
            ("/posts", self.post, ("external_id", "title", "content")),
        ):
            for field in fields:
                for blank in ("", " ", "\t\r\n"):
                    with self.subTest(path=path, field=field, blank=repr(blank)):
                        self.reject(path, {**base, field: blank})

    def test_oversized_text_never_persists(self):
        for path, base, limits in (
            ("/images", self.image, {"external_id": 100, "filename": 255, "source": 50}),
            ("/posts", self.post, {"external_id": 100, "title": 255, "content": 100000}),
        ):
            for field, limit in limits.items():
                with self.subTest(path=path, field=field):
                    self.reject(path, {**base, field: "x" * (limit + 1)})

    def test_wrong_types_never_persist(self):
        for path, base, fields in (
            ("/images", self.image, ("external_id", "filename", "source")),
            ("/posts", self.post, ("external_id", "title", "content")),
        ):
            for field in fields:
                for value in (1, False, None, ["text"]):
                    with self.subTest(path=path, field=field, value=value):
                        self.reject(path, {**base, field: value})

    def test_unexpected_fields_cannot_select_tenant_or_state(self):
        for path, base in (("/images", self.image), ("/posts", self.post)):
            for field in ("tenant_id", "processing_status", "unexpected"):
                with self.subTest(path=path, field=field):
                    self.reject(path, {**base, field: 2})

    def test_invalid_source_urls_never_persist(self):
        for url in ("not a URL", "file:///C:/private.jpg", "ftp://example.com/photo"):
            with self.subTest(url=url):
                self.reject("/images", {**self.image, "source_page_url": url})

    def test_paths_and_invalid_windows_filenames_never_persist(self):
        for filename in ("../fox.jpg", "sub/fox.jpg", r"sub\fox.jpg", r"C:\fox.jpg",
                         "CON.jpg", "nul.png", "COM1.jpeg", "LPT9.png", "fox.jpg ",
                         "fox.jpg.", "fox?.png", "fox\x00.jpg"):
            with self.subTest(filename=filename):
                self.reject("/images", {**self.image, "filename": filename})

    def test_unsupported_file_formats_never_persist(self):
        for filename in ("fox", "fox.gif", "fox.svg", "fox.txt"):
            with self.subTest(filename=filename):
                self.reject("/images", {**self.image, "filename": filename})

    def test_missing_fields_never_persist(self):
        for path, base in (("/images", self.image), ("/posts", self.post)):
            for field in base:
                with self.subTest(path=path, field=field):
                    self.reject(path, {key: value for key, value in base.items() if key != field})

    def test_valid_maximum_lengths_persist(self):
        image = {**self.image, "external_id": "i" * 100, "filename": "f" * 251 + ".jpg", "source": "s" * 50}
        post = {**self.post, "external_id": "p" * 100, "title": "t" * 255, "content": "c" * 100000}
        self.assertEqual(self.client.post("/images", json=image).status_code, 201)
        response = self.client.post("/posts", json=post)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["content"], post["content"])

    def test_valid_post_text_is_preserved(self):
        title, content = "  Red fox  ", "First line.\n\nSecond line with café.\n"
        response = self.client.post("/posts", json={**self.post, "title": title, "content": content})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["title"], title)
        self.assertEqual(response.json()["content"], content)

    def test_valid_image_and_duplicate_conflict(self):
        payload = {**self.image, "filename": "Fox.PNG"}
        self.assertEqual(self.client.post("/images", json=payload).status_code, 201)
        self.assertEqual(self.client.post("/images", json=payload).status_code, 409)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count(Image.id))), 1)

    def test_limits_are_visible_in_openapi(self):
        schemas = self.client.get("/openapi.json").json()["components"]["schemas"]
        for name, limits in (("ImageCreate", {"external_id": 100, "filename": 255, "source": 50}),
                             ("PostCreate", {"external_id": 100, "title": 255, "content": 100000})):
            self.assertFalse(schemas[name]["additionalProperties"])
            for field, maximum in limits.items():
                self.assertEqual(schemas[name]["properties"][field]["maxLength"], maximum)
                self.assertEqual(schemas[name]["properties"][field]["minLength"], 1)


if __name__ == "__main__":
    unittest.main()

