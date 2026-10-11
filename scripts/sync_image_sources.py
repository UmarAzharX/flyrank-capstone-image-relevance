"""Correct three verified source links in the demo tenant; preserve AI results."""
import argparse
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Image, Tenant
from scripts.download_images import load_manifest, verify_existing

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORRECTIONS = {
    'fox_001': ('https://www.pexels.com/photo/red-fox-in-snowy-winter-setting-outdoors-35986459/',
                'https://www.pexels.com/photo/a-fox-sitting-outdoors-23914490/'),
    'fox_002': ('https://www.pexels.com/photo/red-fox-walking-in-snow-20853949/',
                'https://www.pexels.com/photo/a-brown-and-white-fox-on-snow-covered-ground-7006996/'),
    'fox_003': ('https://www.pexels.com/photo/ezo-red-fox-walking-on-road-9681745/',
                'https://www.pexels.com/photo/brown-fox-walking-on-the-gray-asphalt-road-9681751/'),
}


def sync_sources(db, rows: list[dict], folder: Path, *, apply=False) -> list[str]:
    tenant = db.scalar(select(Tenant).where(Tenant.name == 'FlyRank Demo'))
    if tenant is None:
        raise ValueError('Demo tenant is missing. Run the seed command first.')
    by_id = {row['id']: row for row in rows}
    changes = []
    for external_id, (old, new) in CORRECTIONS.items():
        row = by_id.get(external_id)
        if row is None or row['source_page_url'] != new:
            raise ValueError('Manifest does not contain the verified source correction.')
        image = db.scalar(select(Image).where(Image.tenant_id == tenant.id, Image.external_id == external_id).with_for_update())
        if image is None or image.filename != row['filename'] or image.source != 'pexels':
            raise ValueError('Image record does not match the verified manifest.')
        verify_existing(folder / row['filename'], row)
        if image.source_page_url not in (old, new):
            raise ValueError('Unexpected existing source link. No corrections were applied.')
        if image.source_page_url == old:
            changes.append((image, new))
    # All three records and local hashes must pass before changing any field.
    if apply:
        for image, new in changes:
            image.source_page_url = new
        db.flush()
    return [image.external_id for image, _ in changes]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Save the three verified source-link corrections.')
    args = parser.parse_args()
    try:
        rows = load_manifest(PROJECT_ROOT / 'data/images.json')
        with SessionLocal.begin() as db:
            changes = sync_sources(db, rows, PROJECT_ROOT / 'data/images', apply=args.apply)
    except Exception as exc:
        print(f'Source-link check stopped ({type(exc).__name__}).')
        if isinstance(exc, ValueError):
            print(str(exc))
        return 1
    print(f"Source links {'updated' if args.apply else 'needing correction'}: {len(changes)}")
    for external_id in changes:
        print(external_id)
    if not args.apply:
        print('Preview only. Use --apply to save these verified corrections.')
    print('Image files, metadata, embeddings, suggestions and cost records were not changed.')
    print('No Gemini requests.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
