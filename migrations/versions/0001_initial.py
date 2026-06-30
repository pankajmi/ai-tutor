"""Create initial schema: child, subject, session, mistake, topic_mastery.

Enables pgvector extension (idempotent).
Creates the error_type ENUM and all five tables.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "child",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "subject",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "session",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("child_id", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("topics_covered", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["child_id"],
            ["child.id"],
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subject.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "mistake",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("child_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column(
            "error_type",
            sa.Enum("conceptual", "procedural", "careless", name="error_type"),
            nullable=False,
        ),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["child_id"],
            ["child.id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["session.id"],
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subject.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "topic_mastery",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("child_id", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column(
            "last_tested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["child_id"],
            ["child.id"],
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subject.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("topic_mastery")
    op.drop_table("mistake")
    op.execute("DROP TYPE IF EXISTS error_type")
    op.drop_table("session")
    op.drop_table("subject")
    op.drop_table("child")
