from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import JobStatus, JobType
from app.db.base import Base, beijing_now
from app.models import SystemSetting
from app.schemas.entities import JobRead
from app.services.system_settings import SettingsPatch, load_overrides, save_overrides


def test_beijing_clock_and_api_timestamps():
    difference = beijing_now() - datetime.now(timezone.utc).replace(tzinfo=None)
    assert 8 * 3600 - 2 < difference.total_seconds() < 8 * 3600 + 2
    job = JobRead(id=1, created_at=datetime(2026, 10, 7, 12),
                  updated_at=datetime(2026, 10, 7, 12),
                  job_type=JobType.CRAWL, target_type="source", target_id=1,
                  status=JobStatus.SUCCESS, progress=100, message=None,
                  error_message=None, payload=None, result=None,
                  started_at=datetime(2026, 10, 7, 12), finished_at=None)
    data = job.model_dump(mode="json")
    assert data["created_at"] == "2026-10-07T12:00:00+08:00"
    assert data["started_at"] == "2026-10-07T12:00:00+08:00"


def test_editable_settings_persist_and_reload():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    original = {key: getattr(settings, key) for key in ("spider_timeout", "spider_max_retries")}
    try:
        with Session(engine) as db:
            save_overrides(db, SettingsPatch(spider_timeout=11, spider_max_retries=2))
            row = db.get(SystemSetting, 1)
            assert row is not None and row.data["spider_timeout"] == 11
            settings.spider_timeout = 30
            load_overrides(db)
            assert settings.spider_timeout == 11
            save_overrides(db, SettingsPatch(spider_timeout=12))
            db.refresh(row)
            assert row.data == {"spider_timeout": 12, "spider_max_retries": 2}
    finally:
        for key, value in original.items():
            setattr(settings, key, value)


def test_settings_reject_invalid_or_secret_fields():
    with pytest.raises(ValidationError):
        SettingsPatch(spider_timeout=0)
    with pytest.raises(ValidationError):
        SettingsPatch(db_password="secret")
    with pytest.raises(ValidationError):
        SettingsPatch(spider_max_concurrency=2)


def test_legacy_spider_concurrency_is_normalized_to_one():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    original = settings.spider_max_concurrency
    try:
        with Session(engine) as db:
            db.add(SystemSetting(id=1, data={"spider_max_concurrency": 3}))
            db.commit()
            load_overrides(db)
            row = db.get(SystemSetting, 1)
            assert row.data["spider_max_concurrency"] == 1
            assert settings.spider_max_concurrency == 1
    finally:
        settings.spider_max_concurrency = original
