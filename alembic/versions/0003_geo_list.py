"""created_campaigns.country -> geo: несколько стран через запятую

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("created_campaigns") as batch:
        batch.alter_column("country", new_column_name="geo",
                           existing_type=sa.String(2), type_=sa.String(512), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("created_campaigns") as batch:
        batch.alter_column("geo", new_column_name="country",
                           existing_type=sa.String(512), type_=sa.String(2), existing_nullable=False)
