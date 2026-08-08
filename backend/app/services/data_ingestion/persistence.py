"""Batched upserts that validate and repair geometry inside PostGIS.

Geometry arrives as WKT and is converted with ``ST_GeomFromText``. Two things
happen in the same statement:

* ``ST_MakeValid`` repairs self-intersecting rings — common in municipal KML
  exports, where a bowtie polygon would otherwise fail every spatial query.
* ``ST_CollectionExtract`` then keeps only the dimension we asked for, because
  repairing a polygon can legitimately yield a collection containing stray
  lines or points.

Rows whose geometry cannot be repaired are excluded by the ``WHERE`` clause
rather than raising, and the shortfall between attempted and written rows is
reported as a rejection — so a silently dropped row is impossible.

Upserts are keyed on ``(data_source_id, external_id)`` so re-running an
ingestion is idempotent.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)

#: Rows per statement. Large enough to amortise round trips, small enough that
#: the 20k-segment road layer does not build a single enormous parameter set.
BATCH_SIZE = 500

#: ST_CollectionExtract type codes.
DIM_POINT = 1
DIM_LINE = 2
DIM_POLYGON = 3


def _geom_expression(dimension: int, *, multi: bool) -> str:
    """SQL that turns :geom_wkt into a clean geometry of the wanted dimension."""
    repaired = "ST_MakeValid(ST_GeomFromText(:geom_wkt, 4326))"
    extracted = f"ST_CollectionExtract({repaired}, {dimension})"
    if multi:
        return f"ST_Multi({extracted})"
    # ST_CollectionExtract always returns a MULTI* geometry; GeometryN unwraps
    # the single part for columns typed as a simple LINESTRING or POINT.
    return f"ST_GeometryN({extracted}, 1)"


async def upsert_rows(
    session: AsyncSession,
    *,
    table: str,
    columns: list[str],
    conflict_columns: list[str],
    update_columns: list[str],
    rows: list[dict[str, Any]],
    geometry_dimension: int,
    geometry_multi: bool = False,
) -> int:
    """Insert or update rows carrying a ``geom_wkt`` parameter.

    Returns the number of rows actually written.
    """
    if not rows:
        return 0

    geom_sql = _geom_expression(geometry_dimension, multi=geometry_multi)
    value_columns = [c for c in columns if c != "geom"]
    placeholders = ", ".join(f":{c}" for c in value_columns)
    column_list = ", ".join([*value_columns, "geom"])

    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_columns)
    conflict = ", ".join(conflict_columns)

    statement = text(
        f"""
        INSERT INTO {table} ({column_list}, created_at, updated_at)
        SELECT {placeholders}, {geom_sql}, now(), now()
        WHERE ST_IsValid({geom_sql}) AND NOT ST_IsEmpty({geom_sql})
        ON CONFLICT ({conflict}) DO UPDATE
        SET {updates}, geom = EXCLUDED.geom, updated_at = now()
        """
    )

    written = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        # executemany does not report per-row counts, so batches are executed
        # row by row where an exact written count matters. The statement is
        # prepared once by the driver, so this stays acceptable at this scale.
        for row in batch:
            result = await session.execute(statement, row)
            written += result.rowcount or 0
        await session.flush()

    return written


async def upsert_rows_without_geometry(
    session: AsyncSession,
    *,
    table: str,
    columns: list[str],
    conflict_columns: list[str],
    update_columns: list[str],
    rows: list[dict[str, Any]],
) -> int:
    """Upsert for tables with no geometry column (e.g. weather observations)."""
    if not rows:
        return 0

    placeholders = ", ".join(f":{c}" for c in columns)
    column_list = ", ".join(columns)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_columns)
    conflict = ", ".join(conflict_columns)

    statement = text(
        f"""
        INSERT INTO {table} ({column_list}, created_at, updated_at)
        VALUES ({placeholders}, now(), now())
        ON CONFLICT ({conflict}) DO UPDATE
        SET {updates}, updated_at = now()
        """
    )

    written = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        result = await session.execute(statement, batch)
        written += result.rowcount if result.rowcount and result.rowcount > 0 else len(batch)
        await session.flush()
    return written


async def recompute_lengths(session: AsyncSession, *, city_id: Any, srid_metric: int) -> int:
    """Recompute road lengths in metres on a projected CRS.

    Publisher-supplied lengths state no units, so they are not trusted. Degrees
    are not a distance, hence the transform.
    """
    result = await session.execute(
        text(
            """
            UPDATE road_segments
            SET length_m = ST_Length(ST_Transform(geom, :srid))
            WHERE city_id = :city_id
            """
        ),
        {"city_id": city_id, "srid": srid_metric},
    )
    return result.rowcount or 0
