# alembic/versions/0001_initial_schema.py

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision, down_revision, branch_labels, depends_on = "0001", None, None, None
JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("now()")


def _col(name, type_, **kw):
    return sa.Column(name, type_, **kw)


def _timestamps():
    return [
        _col(n, sa.DateTime(timezone=True), server_default=NOW, nullable=False) for n in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    op.create_table(
        "contents",
        _col("id", sa.Integer(), nullable=False),
        _col("tmdb_id", sa.Integer()),
        _col("imdb_id", sa.String(20)),
        _col("title", sa.String(500), nullable=False),
        _col("original_title", sa.String(500)),
        _col("content_type", sa.String(10), nullable=False),
        _col("genres", JSONB, nullable=False, server_default="[]"),
        _col("languages", JSONB, nullable=False, server_default="[]"),
        _col("release_date", sa.Date()),
        _col("runtime", sa.Integer()),
        _col("rating", sa.Float()),
        _col("vote_count", sa.Integer(), nullable=False, server_default="0"),
        _col("popularity", sa.Float(), nullable=False, server_default="0.0"),
        _col("overview", sa.Text()),
        _col("poster_path", sa.String(255)),
        _col("backdrop_path", sa.String(255)),
        _col("youtube_trailer_id", sa.String(20)),
        *[
            _col(f, sa.Boolean(), nullable=False, server_default="false")
            for f in ("is_trending", "is_new_release", "is_critics_choice")
        ],
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in (
        ("imdb_id", ["imdb_id"]),
        ("title", ["title"]),
        ("type", ["content_type"]),
        ("release_date", ["release_date"]),
        ("rating", ["rating"]),
        ("popularity", ["popularity"]),
        ("type_trending", ["content_type", "is_trending"]),
        ("type_release", ["content_type", "release_date"]),
        ("rating_votes", ["rating", "vote_count"]),
    ):
        op.create_index(f"ix_content_{name}", "contents", cols)
    for col in ("genres", "languages"):
        op.create_index(f"ix_content_{col}_gin", "contents", [col], postgresql_using="gin")
    op.execute(
        "CREATE UNIQUE INDEX uq_content_tmdb_type_nonzero ON contents (tmdb_id, content_type) "
        "WHERE tmdb_id IS NOT NULL AND tmdb_id > 0"
    )
    for flag, name in (
        ("is_trending", "trending"),
        ("is_new_release", "new_release"),
        ("is_critics_choice", "critics_choice"),
    ):
        op.execute(f"CREATE INDEX ix_content_{name} ON contents ({flag}) WHERE {flag} = true")

    op.create_table(
        "persons",
        _col("id", sa.Integer(), nullable=False),
        _col("tmdb_id", sa.Integer(), nullable=False),
        _col("name", sa.String(255), nullable=False),
        _col("biography", sa.Text()),
        _col("birthday", sa.Date()),
        _col("deathday", sa.Date()),
        _col("place_of_birth", sa.String(255)),
        _col("profile_path", sa.String(255)),
        _col("backdrop_path", sa.String(255)),
        _col("popularity", sa.Float(), nullable=False, server_default="0.0"),
        _col("known_for_department", sa.String(50)),
        _col("gender", sa.Integer()),
        _col("also_known_as", JSONB, nullable=False, server_default="[]"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tmdb_id"),
    )
    for name, col in (
        ("tmdb_id", "tmdb_id"),
        ("name", "name"),
        ("popularity", "popularity"),
        ("known_for_dept", "known_for_department"),
    ):
        op.create_index(f"ix_person_{name}", "persons", [col])

    op.create_table(
        "content_persons",
        _col("id", sa.Integer(), nullable=False),
        _col("content_id", sa.Integer(), nullable=False),
        _col("person_id", sa.Integer(), nullable=False),
        _col("role_type", sa.String(10), nullable=False),
        _col("character", sa.String(255)),
        _col("job", sa.String(100)),
        _col("department", sa.String(100)),
        _col("order", sa.Integer()),
        sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_person_content_role", "content_persons", ["content_id", "role_type"])
    op.create_index("ix_content_person_person_role", "content_persons", ["person_id", "role_type"])
    op.create_index("ix_content_person_content_id", "content_persons", ["content_id"])
    op.create_index("ix_content_person_person_id", "content_persons", ["person_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_content_person_role ON content_persons "
        "(content_id, person_id, role_type, character, job)"
    )

    op.create_table(
        "anonymous_interactions",
        _col("id", sa.Integer(), nullable=False),
        _col("session_id", sa.String(64), nullable=False),
        _col("content_id", sa.Integer(), nullable=False),
        _col("interaction_type", sa.String(20), nullable=False),
        _col("interaction_metadata", JSONB),
        _col("timestamp", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in (
        ("session", ["session_id"]),
        ("session_type", ["session_id", "interaction_type"]),
        ("timestamp", ["timestamp"]),
        ("session_content_type", ["session_id", "content_id", "interaction_type"]),
        ("content", ["content_id"]),
    ):
        op.create_index(f"ix_anon_{name}", "anonymous_interactions", cols)


def downgrade() -> None:
    for table in ("anonymous_interactions", "content_persons", "persons", "contents"):
        op.drop_table(table)
