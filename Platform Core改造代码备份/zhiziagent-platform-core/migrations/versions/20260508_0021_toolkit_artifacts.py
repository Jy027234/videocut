"""add toolkit artifact byte service table

Revision ID: 20260508_0021
Revises: 20260507_0020
Create Date: 2026-05-08 02:15:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260508_0021"
down_revision = "20260507_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "toolkit_artifacts",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("tenant_id", sa.String(length=40), nullable=False),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("toolkit_id", sa.String(length=120), nullable=False),
        sa.Column("capability", sa.String(length=160), nullable=True),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=160), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=80), nullable=True),
        sa.Column("data_class", sa.String(length=32), nullable=False),
        sa.Column("retention_policy", sa.String(length=80), nullable=False),
        sa.Column("access_policy_json", sa.JSON(), nullable=False),
        sa.Column("storage_kind", sa.String(length=32), nullable=False),
        sa.Column("content_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_id", sa.String(length=160), nullable=True),
        sa.Column("trace_id", sa.String(length=160), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_toolkit_artifacts_capability", "toolkit_artifacts", ["capability"], unique=False)
    op.create_index("ix_toolkit_artifacts_expires_at", "toolkit_artifacts", ["expires_at"], unique=False)
    op.create_index("ix_toolkit_artifacts_owner_id", "toolkit_artifacts", ["owner_id"], unique=False)
    op.create_index("ix_toolkit_artifacts_owner_type", "toolkit_artifacts", ["owner_type"], unique=False)
    op.create_index("ix_toolkit_artifacts_run_id", "toolkit_artifacts", ["run_id"], unique=False)
    op.create_index("ix_toolkit_artifacts_status", "toolkit_artifacts", ["status"], unique=False)
    op.create_index("ix_toolkit_artifacts_tenant_id", "toolkit_artifacts", ["tenant_id"], unique=False)
    op.create_index("ix_toolkit_artifacts_toolkit_id", "toolkit_artifacts", ["toolkit_id"], unique=False)
    op.create_index("ix_toolkit_artifacts_trace_id", "toolkit_artifacts", ["trace_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_toolkit_artifacts_trace_id", table_name="toolkit_artifacts")
    op.drop_index("ix_toolkit_artifacts_toolkit_id", table_name="toolkit_artifacts")
    op.drop_index("ix_toolkit_artifacts_tenant_id", table_name="toolkit_artifacts")
    op.drop_index("ix_toolkit_artifacts_status", table_name="toolkit_artifacts")
    op.drop_index("ix_toolkit_artifacts_run_id", table_name="toolkit_artifacts")
    op.drop_index("ix_toolkit_artifacts_owner_type", table_name="toolkit_artifacts")
    op.drop_index("ix_toolkit_artifacts_owner_id", table_name="toolkit_artifacts")
    op.drop_index("ix_toolkit_artifacts_expires_at", table_name="toolkit_artifacts")
    op.drop_index("ix_toolkit_artifacts_capability", table_name="toolkit_artifacts")
    op.drop_table("toolkit_artifacts")
