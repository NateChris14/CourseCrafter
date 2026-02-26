"""generation model updated with Text

Revision ID: c9391ece59ad
Revises: 510517af1360
Create Date: 2026-02-23 17:29:41.108455
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c9391ece59ad"
down_revision: Union[str, None] = "510517af1360"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make drops safe on fresh DBs / partially applied states
    op.execute("DROP INDEX IF EXISTS checkpoint_blobs_thread_id_idx")
    op.execute("DROP TABLE IF EXISTS checkpoint_blobs")
    op.execute("DROP TABLE IF EXISTS checkpoint_migrations")
    op.execute("DROP INDEX IF EXISTS checkpoints_thread_id_idx")
    op.execute("DROP TABLE IF EXISTS checkpoints")
    op.execute("DROP INDEX IF EXISTS checkpoint_writes_thread_id_idx")
    op.execute("DROP TABLE IF EXISTS checkpoint_writes")

    op.alter_column(
        "generation_runs",
        "message",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "generation_runs",
        "message",
        existing_type=sa.Text(),
        type_=sa.VARCHAR(length=255),
        existing_nullable=True,
    )

    op.create_table(
        "checkpoint_writes",
        sa.Column("thread_id", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column(
            "checkpoint_ns",
            sa.TEXT(),
            server_default=sa.text("''::text"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("checkpoint_id", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column("task_id", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column("idx", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("channel", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column("type", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column("blob", postgresql.BYTEA(), autoincrement=False, nullable=False),
        sa.Column(
            "task_path",
            sa.TEXT(),
            server_default=sa.text("''::text"),
            autoincrement=False,
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "task_id",
            "idx",
            name="checkpoint_writes_pkey",
        ),
    )
    op.create_index(
        "checkpoint_writes_thread_id_idx", "checkpoint_writes", ["thread_id"], unique=False
    )

    op.create_table(
        "checkpoints",
        sa.Column("thread_id", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column(
            "checkpoint_ns",
            sa.TEXT(),
            server_default=sa.text("''::text"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("checkpoint_id", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column("parent_checkpoint_id", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column("type", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column(
            "checkpoint",
            postgresql.JSONB(astext_type=sa.Text()),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            autoincrement=False,
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "thread_id", "checkpoint_ns", "checkpoint_id", name="checkpoints_pkey"
        ),
    )
    op.create_index("checkpoints_thread_id_idx", "checkpoints", ["thread_id"], unique=False)

    op.create_table(
        "checkpoint_migrations",
        sa.Column("v", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.PrimaryKeyConstraint("v", name="checkpoint_migrations_pkey"),
    )

    op.create_table(
        "checkpoint_blobs",
        sa.Column("thread_id", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column(
            "checkpoint_ns",
            sa.TEXT(),
            server_default=sa.text("''::text"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("channel", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column("version", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column("type", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column("blob", postgresql.BYTEA(), autoincrement=False, nullable=True),
        sa.PrimaryKeyConstraint(
            "thread_id",
            "checkpoint_ns",
            "channel",
            "version",
            name="checkpoint_blobs_pkey",
        ),
    )
    op.create_index(
        "checkpoint_blobs_thread_id_idx", "checkpoint_blobs", ["thread_id"], unique=False
    )
