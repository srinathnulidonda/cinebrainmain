# alembic/versions/0002_add_unique_constraint_tmdb_type.py

from alembic import op

revision, down_revision, branch_labels, depends_on = "0002", "0001", None, None


def upgrade() -> None:
    op.create_unique_constraint("uq_content_tmdb_type", "contents", ["tmdb_id", "content_type"])


def downgrade() -> None:
    op.drop_constraint("uq_content_tmdb_type", "contents", type_="unique")
