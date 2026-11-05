"""Run one SQL file against the project database.   python python/run_sql.py sql/00_raw_indexes.sql"""
import sys
import time
from pathlib import Path

from db import PROJECT_ROOT, get_engine


def run_file(path):
    sql = Path(path)
    sql = sql if sql.is_absolute() else PROJECT_ROOT / sql
    connection = get_engine().raw_connection()
    try:
        started = time.time()
        with connection.cursor() as cursor:
            cursor.execute(sql.read_text(encoding="utf-8"))
        connection.commit()
        print(f"{sql.name}: done in {time.time() - started:.1f}s")
    finally:
        connection.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python python/run_sql.py <file.sql>")
    run_file(sys.argv[1])
