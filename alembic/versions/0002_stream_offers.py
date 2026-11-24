"""stream_offers: черновики офферов, пины и архив

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stream_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("share", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("pushed_share", sa.Integer(), nullable=True),
        sa.Column("pushed_state", sa.String(16), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stream_id", "offer_id", name="uq_stream_offers_stream_offer"),
    )
    op.create_index("ix_stream_offers_campaign_id", "stream_offers", ["campaign_id"])
    op.create_index("ix_stream_offers_stream_id", "stream_offers", ["stream_id"])


def downgrade() -> None:
    op.drop_index("ix_stream_offers_stream_id", "stream_offers")
    op.drop_index("ix_stream_offers_campaign_id", "stream_offers")
    op.drop_table("stream_offers")
