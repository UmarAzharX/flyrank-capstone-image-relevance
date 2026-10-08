import json
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Image, Tenant


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data" / "images.json"
DEMO_TENANT_NAME = "FlyRank Demo"


def main():
    with MANIFEST_PATH.open("r", encoding="utf-8") as file:
        manifest = json.load(file)

    with SessionLocal.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.name == DEMO_TENANT_NAME))
        if tenant is None:
            tenant = Tenant(name=DEMO_TENANT_NAME)
            db.add(tenant)
            db.flush()

        existing_ids = set(
            db.scalars(
                select(Image.external_id).where(Image.tenant_id == tenant.id)
            )
        )
        created = 0
        skipped = 0

        for item in manifest:
            external_id = item["id"]
            if external_id in existing_ids:
                skipped += 1
                continue

            db.add(
                Image(
                    tenant_id=tenant.id,
                    external_id=external_id,
                    filename=item["filename"],
                    source=item["source"],
                    source_page_url=item["source_page_url"],
                )
            )
            existing_ids.add(external_id)
            created += 1

    print(f"Created images: {created}")
    print(f"Skipped existing images: {skipped}")


if __name__ == "__main__":
    main()
