# app/models.py

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Content(TimestampMixin, Base):
    __tablename__ = "contents"
    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imdb_id: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    original_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    genres: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    languages: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    runtime: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    vote_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    popularity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    backdrop_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    youtube_trailer_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_trending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_new_release: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_critics_choice: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("tmdb_id", "content_type", name="uq_content_tmdb_type"),
        Index("ix_content_trending", "is_trending", postgresql_where=text("is_trending = true")),
        Index("ix_content_new_release", "is_new_release", postgresql_where=text("is_new_release = true")),
        Index("ix_content_critics_choice", "is_critics_choice", postgresql_where=text("is_critics_choice = true")),
        Index("ix_content_rating", "rating"),
        Index("ix_content_popularity", "popularity"),
        Index("ix_content_type_trending", "content_type", "is_trending"),
        Index("ix_content_type_release", "content_type", "release_date"),
        Index("ix_content_rating_votes", "rating", "vote_count"),
        Index("ix_content_genres_gin", "genres", postgresql_using="gin"),
        Index("ix_content_languages_gin", "languages", postgresql_using="gin"),
    )


class Person(TimestampMixin, Base):
    __tablename__ = "persons"
    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    biography: Mapped[str | None] = mapped_column(Text, nullable=True)
    birthday: Mapped[date | None] = mapped_column(Date, nullable=True)
    deathday: Mapped[date | None] = mapped_column(Date, nullable=True)
    place_of_birth: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    backdrop_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    popularity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    known_for_department: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gender: Mapped[int | None] = mapped_column(Integer, nullable=True)
    also_known_as: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    __table_args__ = (
        Index("ix_person_popularity", "popularity"),
        Index("ix_person_known_for_dept", "known_for_department"),
    )


class ContentPerson(Base):
    __tablename__ = "content_persons"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("contents.id", ondelete="CASCADE"), nullable=False, index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)
    role_type: Mapped[str] = mapped_column(String(10), nullable=False)
    character: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (
        UniqueConstraint("content_id", "person_id", "role_type", "character", "job", name="uq_content_person_role"),
        Index("ix_content_person_content_role", "content_id", "role_type"),
        Index("ix_content_person_person_role", "person_id", "role_type"),
    )


class AnonymousInteraction(Base):
    __tablename__ = "anonymous_interactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("contents.id", ondelete="CASCADE"), nullable=False)
    interaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    interaction_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        Index("ix_anon_session", "session_id"),
        Index("ix_anon_session_type", "session_id", "interaction_type"),
        Index("ix_anon_timestamp", "timestamp"),
        Index("ix_anon_session_content_type", "session_id", "content_id", "interaction_type"),
        Index("ix_anon_content", "content_id"),
        Index("ix_anon_session_timestamp", "session_id", "timestamp"),
        Index(
            "uq_anon_list_item",
            "session_id",
            "content_id",
            "interaction_type",
            unique=True,
            postgresql_where=text("interaction_type IN ('watchlist','favorite')"),
        ),
    )
