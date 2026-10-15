from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.db.base import Base


class Repository:
    def __init__(self, db: Session, model: type[Base]):
        self.db = db
        self.model = model

    def get(self, item_id: int) -> Base | None:
        return self.db.get(self.model, item_id)

    def list(self, *, page: int = 1, page_size: int = 20, search: str | None = None,
             search_fields: tuple[str, ...] = (), filters: dict[str, Any] | None = None,
             sort: str = "-created_at") -> tuple[list[Base], int]:
        query: Select = select(self.model)
        if search and search_fields:
            query = query.where(or_(*(getattr(self.model, f).ilike(f"%{search}%") for f in search_fields)))
        for key, value in (filters or {}).items():
            if value is not None:
                query = query.where(getattr(self.model, key) == value)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        desc = sort.startswith("-")
        column = getattr(self.model, sort.lstrip("-"))
        query = query.order_by(column.desc() if desc else column.asc(), self.model.id.desc())
        rows = self.db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
        return list(rows), total

    def create(self, data: dict[str, Any]) -> Base:
        item = self.model(**data)
        self.db.add(item)
        self.db.flush()
        return item

    def update(self, item: Base, data: dict[str, Any]) -> Base:
        for key, value in data.items():
            setattr(item, key, value)
        self.db.flush()
        return item
