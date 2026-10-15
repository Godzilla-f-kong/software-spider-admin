"""Database-backed, non-secret runtime settings for the single-process Admin."""
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import SystemSetting


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_root: str | None = Field(default=None, min_length=1, max_length=1024)
    spider_enabled: bool | None = None
    spider_user_agent: str | None = Field(default=None, min_length=8, max_length=255)
    spider_timeout: float | None = Field(default=None, ge=1, le=120)
    spider_max_retries: int | None = Field(default=None, ge=0, le=10)
    spider_max_concurrency: int | None = Field(default=None, ge=1, le=1)
    spider_request_delay: float | None = Field(default=None, ge=0, le=10)

    @field_validator("data_root", "spider_user_agent")
    @classmethod
    def non_blank(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or "\n" in value or "\r" in value):
            raise ValueError("Must be a non-empty single-line value")
        return value.strip() if value is not None else None


def apply_overrides(values: dict[str, object]) -> None:
    """Use the same validated values for API requests and background spider jobs."""
    patch = SettingsPatch.model_validate(values)
    for key, value in patch.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(settings, key, value)


def load_overrides(db: Session) -> None:
    row = db.get(SystemSetting, 1)
    if row:
        values = dict(row.data)
        if values.get("spider_max_concurrency", 1) != 1:
            values["spider_max_concurrency"] = 1
            row.data = values
            db.commit()
        apply_overrides(values)


def save_overrides(db: Session, patch: SettingsPatch) -> None:
    changes = patch.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        return
    row = db.get(SystemSetting, 1)
    if row is None:
        row = SystemSetting(id=1, data=changes)
        db.add(row)
    else:
        row.data = {**row.data, **changes}
    db.commit()
    apply_overrides(changes)


def effective_data_path() -> str:
    return str(Path(settings.data_path))
