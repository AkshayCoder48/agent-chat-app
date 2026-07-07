
"""add env_vars column to user_settings

Revision ID: 0027_user_settings_env_vars
Revises: 0026_user_settings_mcp_tools
"""

revision = "0027_user_settings_env_vars"
down_revision = "0026_user_settings_mcp_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import JSONB

    op.add_column(
        "user_settings",
        sa.Column("env_vars", JSONB, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    from alembic import op

    op.drop_column("user_settings", "env_vars")
