"""Add subjects_covered JSON column to session table.

Revision ID: 0002_add_subjects_covered
Revises: 0001_initial
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_add_subjects_covered"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("session", sa.Column("subjects_covered", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("session", "subjects_covered")
