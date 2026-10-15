from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")


def beijing_now() -> datetime:
    """MySQL DATETIME convention: naive clock time in Asia/Shanghai."""
    return datetime.now(BEIJING).replace(tzinfo=None)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=beijing_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=beijing_now, onupdate=beijing_now, nullable=False)
