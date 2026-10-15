"""Inspect table comments in the configured MySQL database; prints no credentials."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text

from app.db.session import engine


with engine.connect() as connection:
    print("connection target:", engine.url.host, engine.url.port, engine.url.database)
    identity = connection.execute(text(
        "SELECT @@hostname, @@port, DATABASE(), CURRENT_USER(), @@character_set_connection"
    )).one()
    print("server, port, database, account, charset:", identity)
    rows = connection.execute(text(
        "SELECT table_name, table_comment, HEX(table_comment) "
        "FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE' "
        "ORDER BY table_name"
    )).all()
    for table_name, comment, encoded in rows:
        print(f"{table_name}: {comment}")
    columns = connection.execute(text(
        "SELECT COUNT(*), SUM(column_comment <> '') FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name <> 'alembic_version'"
    )).one()
    print("business columns / columns with comments:", columns)
    sample = connection.execute(text(
        "SELECT column_name, column_comment FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'software' "
        "AND column_name IN ('name', 'slug') ORDER BY column_name"
    )).all()
    print("sample software columns:", sample)
