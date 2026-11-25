# alembic/versions/0003_recommendation_indexes.py

from alembic import op

revision, down_revision, branch_labels, depends_on = "0003", "0002", None, None


def upgrade() -> None:
    op.execute("""DO $$ BEGIN
        CREATE EXTENSION IF NOT EXISTS pg_trgm;
        CREATE INDEX IF NOT EXISTS ix_content_title_trgm ON contents USING gin (title gin_trgm_ops);
    EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'pg_trgm unavailable, skipping trigram index: %', SQLERRM; END $$""")
    op.create_index("ix_content_release_popularity", "contents", ["release_date", "popularity"])
    op.create_index("ix_anon_session_timestamp", "anonymous_interactions", ["session_id", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_anon_session_timestamp", table_name="anonymous_interactions")
    op.drop_index("ix_content_release_popularity", table_name="contents")
    op.execute("DROP INDEX IF EXISTS ix_content_title_trgm")
