# alembic/versions/0001_initial_schema.py
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision, down_revision, branch_labels, depends_on = "0001", None, None, None

JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("now()")


def _timestamps():
    return [
        sa.Column(name, sa.DateTime(timezone=True), server_default=NOW, nullable=False)
        for name in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    # ── contents ──────────────────────────────────────────────────────────
    op.create_table(
        "contents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tmdb_id", sa.Integer()),
        sa.Column("imdb_id", sa.String(20)),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("original_title", sa.String(500)),
        sa.Column("content_type", sa.String(10), nullable=False),
        sa.Column("genres", JSONB, nullable=False, server_default="[]"),
        sa.Column("languages", JSONB, nullable=False, server_default="[]"),
        sa.Column("release_date", sa.Date()),
        sa.Column("runtime", sa.Integer()),
        sa.Column("rating", sa.Float()),
        sa.Column("vote_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("popularity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("overview", sa.Text()),
        sa.Column("poster_path", sa.String(255)),
        sa.Column("backdrop_path", sa.String(255)),
        sa.Column("youtube_trailer_id", sa.String(20)),
        sa.Column("is_trending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_new_release", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_critics_choice", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tmdb_id", "content_type", name="uq_content_tmdb_type"),
    )
    for name, cols in (
        ("ix_contents_imdb_id", ["imdb_id"]),
        ("ix_contents_title", ["title"]),
        ("ix_contents_content_type", ["content_type"]),
        ("ix_contents_release_date", ["release_date"]),
        ("ix_content_rating", ["rating"]),
        ("ix_content_popularity", ["popularity"]),
        ("ix_content_type_trending", ["content_type", "is_trending"]),
        ("ix_content_type_release", ["content_type", "release_date"]),
        ("ix_content_rating_votes", ["rating", "vote_count"]),
        ("ix_content_release_popularity", ["release_date", "popularity"]),
    ):
        op.create_index(name, "contents", cols)

    op.create_index("ix_content_genres_gin", "contents", ["genres"], postgresql_using="gin")
    op.create_index("ix_content_languages_gin", "contents", ["languages"], postgresql_using="gin")

    for flag, name in (
        ("is_trending", "ix_content_trending"),
        ("is_new_release", "ix_content_new_release"),
        ("is_critics_choice", "ix_content_critics_choice"),
    ):
        op.create_index(name, "contents", [flag], postgresql_where=sa.text(f"{flag} = true"))

    # Trigram index for fuzzy title search (skipped quietly if pg_trgm is unavailable)
    op.execute(
        """DO $$ BEGIN
            CREATE EXTENSION IF NOT EXISTS pg_trgm;
            CREATE INDEX IF NOT EXISTS ix_content_title_trgm ON contents USING gin (title gin_trgm_ops);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'pg_trgm unavailable, skipping trigram index: %', SQLERRM;
        END $$"""
    )

    # ── persons ───────────────────────────────────────────────────────────
    op.create_table(
        "persons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("biography", sa.Text()),
        sa.Column("birthday", sa.Date()),
        sa.Column("deathday", sa.Date()),
        sa.Column("place_of_birth", sa.String(255)),
        sa.Column("profile_path", sa.String(255)),
        sa.Column("backdrop_path", sa.String(255)),
        sa.Column("popularity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("known_for_department", sa.String(50)),
        sa.Column("gender", sa.Integer()),
        sa.Column("also_known_as", JSONB, nullable=False, server_default="[]"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_persons_tmdb_id", "persons", ["tmdb_id"], unique=True)
    op.create_index("ix_persons_name", "persons", ["name"])
    op.create_index("ix_person_popularity", "persons", ["popularity"])
    op.create_index("ix_person_known_for_dept", "persons", ["known_for_department"])

    # ── content_persons ───────────────────────────────────────────────────
    op.create_table(
        "content_persons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("role_type", sa.String(10), nullable=False),
        sa.Column("character", sa.String(255)),
        sa.Column("job", sa.String(100)),
        sa.Column("department", sa.String(100)),
        sa.Column("order", sa.Integer()),
        sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_id", "person_id", "role_type", "character", "job", name="uq_content_person_role"),
    )
    op.create_index("ix_content_persons_content_id", "content_persons", ["content_id"])
    op.create_index("ix_content_persons_person_id", "content_persons", ["person_id"])
    op.create_index("ix_content_person_content_role", "content_persons", ["content_id", "role_type"])
    op.create_index("ix_content_person_person_role", "content_persons", ["person_id", "role_type"])

    # ── anonymous_interactions ────────────────────────────────────────────
    op.create_table(
        "anonymous_interactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("interaction_type", sa.String(20), nullable=False),
        sa.Column("interaction_metadata", JSONB),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in (
        ("ix_anon_session", ["session_id"]),
        ("ix_anon_session_type", ["session_id", "interaction_type"]),
        ("ix_anon_timestamp", ["timestamp"]),
        ("ix_anon_session_content_type", ["session_id", "content_id", "interaction_type"]),
        ("ix_anon_content", ["content_id"]),
        ("ix_anon_session_timestamp", ["session_id", "timestamp"]),
    ):
        op.create_index(name, "anonymous_interactions", cols)

    op.create_index(
        "uq_anon_list_item",
        "anonymous_interactions",
        ["session_id", "content_id", "interaction_type"],
        unique=True,
        postgresql_where=sa.text("interaction_type IN ('watchlist','favorite')"),
    )


def downgrade() -> None:
    for table in ("anonymous_interactions", "content_persons", "persons", "contents"):
        op.drop_table(table)