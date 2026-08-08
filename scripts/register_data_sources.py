#!/usr/bin/env python
"""Load the provenance manifest into the ``data_sources`` table.

This is the only supported way to introduce a dataset to UrbanPulse. Ingestion
jobs look sources up by slug and refuse to write records for a slug that is not
registered, so nothing can enter the warehouse without a recorded provider,
licence and origin.

The script is idempotent: re-running it updates existing rows by slug rather
than inserting duplicates.

Usage::

    python scripts/register_data_sources.py
    python scripts/register_data_sources.py --manifest data/metadata/data_sources.json
    python scripts/register_data_sources.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models.provenance import DataOrigin, DataSource, DataSourceKind  # noqa: E402

DEFAULT_MANIFEST = REPO_ROOT / "data" / "metadata" / "data_sources.json"

REQUIRED_FIELDS = ("slug", "name", "provider", "kind", "origin", "source_url", "license")


def load_manifest(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"Manifest not found: {path}")

    payload = json.loads(path.read_text())
    datasets = payload.get("datasets")
    if not isinstance(datasets, list):
        raise SystemExit(f"{path} has no 'datasets' array.")

    for index, entry in enumerate(datasets):
        missing = [field for field in REQUIRED_FIELDS if not entry.get(field)]
        if missing:
            raise SystemExit(
                f"datasets[{index}] ({entry.get('slug', '?')}) is missing: {', '.join(missing)}"
            )
        # Fail loudly on an unknown enum value rather than coercing it: a typo
        # in `origin` would otherwise mislabel simulated data as observed.
        try:
            DataSourceKind(entry["kind"])
            DataOrigin(entry["origin"])
        except ValueError as exc:
            raise SystemExit(f"datasets[{index}] ({entry['slug']}): {exc}") from exc

    return datasets


async def upsert(session: AsyncSession, entries: list[dict]) -> tuple[int, int]:
    created = updated = 0

    for entry in entries:
        existing = (
            await session.execute(select(DataSource).where(DataSource.slug == entry["slug"]))
        ).scalar_one_or_none()

        fields = {
            "name": entry["name"],
            "provider": entry["provider"],
            "kind": DataSourceKind(entry["kind"]),
            "origin": DataOrigin(entry["origin"]),
            "source_url": entry["source_url"],
            "license": entry["license"],
            "attribution": entry.get("attribution"),
            "description": entry.get("description"),
            "update_interval_seconds": entry.get("update_interval_seconds"),
            "is_active": entry.get("is_active", True),
        }

        if existing is None:
            session.add(DataSource(slug=entry["slug"], **fields))
            created += 1
        else:
            for key, value in fields.items():
                setattr(existing, key, value)
            updated += 1

    await session.commit()
    return created, updated


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the manifest without touching the database.",
    )
    args = parser.parse_args()

    entries = load_manifest(args.manifest)
    print(f"Manifest OK: {len(entries)} dataset(s) in {args.manifest}")
    for entry in entries:
        print(f"  - {entry['slug']:<26} {entry['origin']:<10} {entry['license']}")

    if args.dry_run:
        print("\nDry run: no database changes made.")
        return 0

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as session:
            created, updated = await upsert(session, entries)
    finally:
        await engine.dispose()

    print(f"\nRegistered: {created} created, {updated} updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
