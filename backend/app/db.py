from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.engine import URL, make_url


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), default='')
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(String(255), default='')
    role: Mapped[str] = mapped_column(String(64), index=True)
    designation: Mapped[str] = mapped_column(String(128), default='')
    email: Mapped[str] = mapped_column(String(255), default='')
    phone: Mapped[str] = mapped_column(String(64), default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    reporting_manager_username: Mapped[str] = mapped_column(String(128), default='')


class SessionToken(Base):
    __tablename__ = 'sessions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    user: Mapped[User] = relationship()


class SheetRow(Base):
    """Lossless phase-one staging store for the 18 non-Users workbook tabs.

    Next phase: normalize high-volume workflows into typed, indexed tables.
    The original spreadsheet 'Password' column is NEVER stored here.
    """
    __tablename__ = 'source_rows'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sheet_name: Mapped[str] = mapped_column(String(100), index=True)
    source_row: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint('sheet_name', 'source_row', name='uq_sheet_source_row'),
                      Index('ix_source_sheet_row', 'sheet_name', 'source_row'))


class ExternalTrainingUpdate(Base):
    """Additive relational store; leaves original imported sheets unchanged."""
    __tablename__ = 'external_training_updates'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    update_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    project_type: Mapped[str] = mapped_column(String(16), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    project_name: Mapped[str] = mapped_column(String(255))
    trainer_username: Mapped[str] = mapped_column(String(128), index=True)
    trainer_name: Mapped[str] = mapped_column(String(255))
    reviewer_username: Mapped[str] = mapped_column(String(128), index=True)
    training_date: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(255))
    topic: Mapped[str] = mapped_column(Text)
    attendance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='Pending', index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str] = mapped_column(String(128), default='')
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comments: Mapped[str] = mapped_column(Text, default='')
    __table_args__ = (UniqueConstraint('project_type', 'project_id', 'trainer_username',
                                      'training_date', 'category', name='uq_external_daily_training'),)


class ImportSheet(Base):
    __tablename__ = 'source_sheets'
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    columns: Mapped[list] = mapped_column(JSON, nullable=False)


def database_url():
    """Construct a safe URL from raw Docker environment variables.

    SQLAlchemy's URL.create() escapes special characters in passwords.  Never
    concatenate POSTGRES_PASSWORD into a database URI: 'pass@1234' would be
    misread as a hostname and crash the API (Nginx then returns HTTP 502).

    DATABASE_URL remains supported for local development / explicit overrides
    when the raw POSTGRES_PASSWORD variable is not defined.
    """
    password = os.getenv('POSTGRES_PASSWORD')
    if password is not None:
        if not password:
            raise ValueError('POSTGRES_PASSWORD must not be empty')
        return URL.create(
            drivername='postgresql+psycopg',
            username=os.getenv('POSTGRES_USER', 'ltmp'),
            password=password,
            host=os.getenv('POSTGRES_HOST', 'db'),
            port=int(os.getenv('POSTGRES_PORT', '5432')),
            database=os.getenv('POSTGRES_DB', 'ltmp'),
        )
    value = os.getenv('DATABASE_URL', '').strip()
    if value:
        return value
    if os.getenv('REQUIRE_DATABASE_URL', '').lower() == 'true':
        raise RuntimeError('DATABASE_URL is required for hosted deployment; refusing SQLite fallback')
    return 'sqlite+pysqlite:///./ltmp-dev.db'


def engine_for(url=None):
    url = url if url is not None else database_url()
    # Neon provides a 'postgresql://' URL. SQLAlchemy otherwise selects the
    # psycopg2 driver, but this project deliberately installs psycopg v3 only.
    if isinstance(url, str) and url.startswith(('postgresql://', 'postgres://')):
        url = make_url(url).set(drivername='postgresql+psycopg')
    is_sqlite = url.startswith('sqlite') if isinstance(url, str) else url.get_backend_name() == 'sqlite'
    opts = {'connect_args': {'check_same_thread': False}} if is_sqlite else {'pool_pre_ping': True, 'pool_recycle': 300, 'pool_size': 3, 'max_overflow': 2, 'pool_timeout': 20}
    return create_engine(url, **opts)


def setup_engine(url=None):
    engine = engine_for(url)
    Base.metadata.create_all(engine)
    return engine


def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
