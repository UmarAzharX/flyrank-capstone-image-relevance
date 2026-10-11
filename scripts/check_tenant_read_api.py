import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Image, Post, Tenant
from app.routes import images, posts


class TenantReadApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name="FlyRank Demo"), Tenant(id=2, name="Other tenant")])
            db.flush()
            for tenant_id in (1, 2):
                db.add(Image(id=tenant_id, tenant_id=tenant_id, external_id="shared_image",
                             filename=f"tenant_{tenant_id}.jpg", source="test",
                             source_page_url=f"https://example.com/tenant/{tenant_id}"))
                db.add(Post(id=tenant_id, tenant_id=tenant_id, external_id="shared_post",
                            title=f"Tenant {tenant_id} post", content=f"Tenant {tenant_id} content"))
        app = FastAPI()
        app.include_router(images.router)
        app.include_router(posts.router)

        def test_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = test_db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_image_list_contains_only_demo_tenant_images(self):
        response = self.client.get("/images")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [1])
        self.assertNotIn("tenant_2", response.text)

    def test_own_image_lookup_preserves_response(self):
        response = self.client.get("/images/1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["filename"], "tenant_1.jpg")
        self.assertEqual(response.json()["external_id"], "shared_image")

    def test_other_tenant_image_is_hidden_like_missing_image(self):
        hidden = self.client.get("/images/2")
        missing = self.client.get("/images/999")
        self.assertEqual((hidden.status_code, missing.status_code), (404, 404))
        self.assertEqual(hidden.json(), missing.json())
        self.assertEqual(hidden.json(), {"detail": "Image not found"})

    def test_empty_image_list_does_not_fall_back_to_other_tenant(self):
        with self.sessions.begin() as db:
            db.delete(db.get(Image, 1))
        self.assertEqual(self.client.get("/images").json(), [])

    def test_other_tenant_external_id_does_not_block_creation(self):
        with self.sessions.begin() as db:
            db.add(Image(tenant_id=2, external_id="other_only", filename="private.jpg",
                         source="test", source_page_url="https://example.com/private"))
        response = self.client.post("/images", json={
            "external_id": "other_only", "filename": "new.jpg", "source": "test",
            "source_page_url": "https://example.com/new",
        })
        self.assertEqual(response.status_code, 201)
        with self.sessions() as db:
            self.assertEqual(db.get(Image, response.json()["id"]).tenant_id, 1)
            self.assertEqual(len(db.scalars(select(Image).where(Image.external_id == "other_only")).all()), 2)

    def test_duplicate_in_demo_tenant_still_returns_conflict(self):
        response = self.client.post("/images", json={
            "external_id": "shared_image", "filename": "new.jpg", "source": "test",
            "source_page_url": "https://example.com/new",
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual([row["id"] for row in self.client.get("/images").json()], [1])

    def test_missing_demo_tenant_does_not_expose_other_tenant(self):
        with self.sessions.begin() as db:
            db.get(Tenant, 1).name = "Renamed tenant"
        for path in ("/images", "/images/2"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json(), {"detail": "Demo tenant not found"})

    def test_request_parameters_cannot_switch_tenant(self):
        response = self.client.get("/images?tenant_id=2", headers={"X-Tenant-ID": "2"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [1])
        self.assertEqual(self.client.get("/images/2?tenant_id=2").status_code, 404)

    def test_post_list_remains_scoped(self):
        response = self.client.get("/posts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [1])

    def test_own_post_lookup_remains_available(self):
        response = self.client.get("/posts/1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Tenant 1 post")

    def test_other_tenant_post_lookup_remains_hidden(self):
        response = self.client.get("/posts/2")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Post not found"})

    def test_empty_post_list_does_not_fall_back_to_other_tenant(self):
        with self.sessions.begin() as db:
            db.delete(db.get(Post, 1))
        self.assertEqual(self.client.get("/posts").json(), [])


if __name__ == "__main__":
    unittest.main()
