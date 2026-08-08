"""Alembic environment.

Uses the synchronous psycopg driver: migrations are a one-shot batch job, so
async buys nothing here while sync keeps ``alembic`` behaving normally.

Two guards matter on a PostGIS database:

1. The PostGIS images put ``topology`` and ``tiger`` on the search path and
   populate them with dozens of extension-owned tables. Autogenerate reflects
   them, sees nothing matching in our metadata, and cheerfully emits
   ``DROP TABLE`` for every one. :func:`include_object` filters out anything
   owned by an extension, queried from ``pg_depend`` rather than hardcoded, so
   it keeps working as extensions change.
2. Migrations run with ``search_path`` pinned to ``public`` so new objects
   cannot land in an extension's schema.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context
from app.core.config import get_settings
from app.models import Base  # noqa: F401 - registers every table on the metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.sync_database_url)

target_metadata = Base.metadata

#: Populated in :func:`run_migrations_online` from the live database.
_extension_owned_tables: set[str] = set()

#: ``spatial_ref_sys`` is created directly by PostGIS rather than as a
#: dependency, so it is not caught by the extension query. ``alembic_version``
#: is Alembic's own bookkeeping table and must never appear in a revision.
ALWAYS_EXCLUDED_TABLES = {"spatial_ref_sys", "alembic_version"}


def _load_extension_owned_tables(connection) -> set[str]:  # noqa: ANN001
    """Names of every table and view that belongs to an installed extension."""
    rows = connection.execute(
        text(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_depend d ON d.objid = c.oid AND d.deptype = 'e'
            JOIN pg_extension e ON e.oid = d.refobjid
            WHERE c.relkind IN ('r', 'v', 'm', 'f', 'p')
            """
        )
    )
    return {row[0] for row in rows}


def include_object(obj, name, type_, reflected, compare_to) -> bool:  # noqa: ANN001
    if type_ == "table":
        if name in ALWAYS_EXCLUDED_TABLES or name in _extension_owned_tables:
            return False
        # Anything outside `public` belongs to an extension's own schema.
        schema = getattr(obj, "schema", None)
        if reflected and schema not in (None, "public"):
            return False
    return not (
        type_ == "index"
        and reflected
        and getattr(obj, "table", None) is not None
        and obj.table.name in _extension_owned_tables
    )


def run_migrations_offline() -> None:
    """Emit SQL without a database connection.

    Extension filtering is unavailable here — there is nothing to query — so
    offline mode is for reviewing a known revision, not for autogenerate.
    """
    context.configure(
        url=settings.sync_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        include_schemas=False,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    global _extension_owned_tables

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.execute(text("SET search_path TO public"))
        _extension_owned_tables = _load_extension_owned_tables(connection)
        # Close the implicit transaction those two statements opened. Alembic
        # only commits a transaction it began itself, and it skips beginning one
        # when the connection is already in a transaction — so leaving this open
        # makes every migration roll back at close while still logging success.
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            include_schemas=False,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
