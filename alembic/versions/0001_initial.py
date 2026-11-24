"""initial: created_campaigns, offer_changes

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "created_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keitaro_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("alias", sa.String(255), nullable=True),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("geo_stream_id", sa.Integer(), nullable=True),
        sa.Column("offer_stream_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_created_campaigns_keitaro_id", "created_campaigns", ["keitaro_id"], unique=True)

    op.create_table(
        "offer_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("offers_before", sa.JSON(), nullable=False),
        sa.Column("offers_after", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_offer_changes_campaign_id", "offer_changes", ["campaign_id"])
    op.create_index("ix_offer_changes_stream_id", "offer_changes", ["stream_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_changes_stream_id", "offer_changes")
    op.drop_index("ix_offer_changes_campaign_id", "offer_changes")
    op.drop_table("offer_changes")
    op.drop_index("ix_created_campaigns_keitaro_id", "created_campaigns")
    op.drop_table("created_campaigns")
