"""SQLite 빠른 조회 — 임의 SQL 실행해 표로 출력. 의존성 0 (stdlib sqlite3).

실행:
  py scripts/db_query.py                          # 테이블 목록
  py scripts/db_query.py "SELECT * FROM users"
  py scripts/db_query.py "SELECT tenant, feature, provider, SUM(quantity) q FROM usage_ledger GROUP BY 1,2,3"
쓰기(INSERT/UPDATE/DELETE)도 됨(자동 commit) — 조심해서.
"""
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import DB_PATH   # noqa: E402


def main():
    sql = sys.argv[1] if len(sys.argv) > 1 else \
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql)
        conn.commit()                 # 쓰기 쿼리도 반영
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print(f"(행 없음)  affected={cur.rowcount}")
        return
    cols = rows[0].keys()
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    line = "  ".join(c.ljust(widths[c]) for c in cols)
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in cols))
    print(f"\n({len(rows)} rows)")


if __name__ == "__main__":
    main()
