# alembic/versions/0004_interaction_integrity.py

import sqlalchemy as sa

from alembic import op

revision, down_revision, branch_labels, depends_on = "0004", "0003", None, None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM anonymous_interactions a
        USING anonymous_interactions b
        WHERE a.id > b.id
          AND a.session_id = b.session_id
          AND a.content_id = b.content_id
          AND a.interaction_type = b.interaction_type
          AND a.interaction_type IN ('watchlist', 'favorite')
        """
    )
    op.create_index(
        "uq_anon_list_item",
        "anonymous_interactions",
        ["session_id", "content_id", "interaction_type"],
        unique=True,
        postgresql_where=sa.text("interaction_type IN ('watchlist','favorite')"),
    )


def downgrade() -> None:
    op.drop_index("uq_anon_list_item", table_name="anonymous_interactions")
