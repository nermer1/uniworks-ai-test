"""SQLite 저장소 — 서버·포트 없는 내장 RDBMS. 멀티워커 동시성은 SQLite가 처리.

A의 api_keys.json(파일+메모리 곡예)을 안 따라하고 여기서 DB로 일원화한다.
연결은 호출마다 새로 열고 닫는다(스레드 안전 단순화). WAL로 읽기 다수 + 쓰기 1 공존.
"""
import os
import sqlite3
from pathlib import Path
from core.config import DATA_DIR

# 기본 data/app.db. 테스트/배포는 PLATFORM_DB_PATH 환경변수로 위치 덮어쓰기 가능.
DB_PATH = Path(os.environ["PLATFORM_DB_PATH"]) if os.environ.get("PLATFORM_DB_PATH") else (DATA_DIR / "app.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id          TEXT PRIMARY KEY,
    key_hash    TEXT UNIQUE NOT NULL,
    tenant      TEXT NOT NULL,
    capabilities TEXT NOT NULL,      -- JSON: {"features":[...], "models":[...]}
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_ledger (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    tenant    TEXT NOT NULL,
    feature   TEXT NOT NULL,         -- 'ocr' / 'recommend' ...
    quantity  INTEGER NOT NULL,      -- 페이지 수 등
    unit      TEXT NOT NULL,         -- 'page' / 'request'
    provider  TEXT NOT NULL,         -- 'mock' / 'openai_compat(자체)' / 'openai_compat(상용)'
    model     TEXT NOT NULL,
    ok        INTEGER NOT NULL,
    meta      TEXT                   -- JSON: 토큰수 등 날 것의 사실 (과금 공식은 나중에)
);
CREATE INDEX IF NOT EXISTS idx_ledger_tenant_ts ON usage_ledger (tenant, ts);

CREATE TABLE IF NOT EXISTS access_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    method  TEXT,
    path    TEXT,
    status  INTEGER,
    ms      INTEGER
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    role          TEXT NOT NULL,          -- 개발자 / 회계 / 관리자
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

-- 테스트 실행 이력 (콘솔 OCR 테스트 결과 보관 — 실사용 원장과 별개, 나중에 부하테스트도 kind로 공용)
CREATE TABLE IF NOT EXISTS test_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    username     TEXT,                    -- 실행한 사람
    group_name   TEXT,                    -- 비교용 그룹 태그 (예: vertex / 원본100)
    kind         TEXT NOT NULL,           -- 'ocr' (추후 'load' 등)
    provider     TEXT,
    model        TEXT,
    doc_type     TEXT,
    file_count   INTEGER,
    page_count   INTEGER,
    ok_count     INTEGER,
    fail_count   INTEGER,
    wall_ms      INTEGER,
    work_ms      INTEGER,
    total_tokens INTEGER,
    result       TEXT                     -- JSON: 응답 payload(파일별·페이지별 결과) — 상세 조회용
);
CREATE INDEX IF NOT EXISTS idx_testruns_ts ON test_runs (ts);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(_SCHEMA)
        # 마이그레이션: 이전에 만들어진 test_runs엔 group_name이 없으므로 없으면 추가
        cols = {r[1] for r in conn.execute("PRAGMA table_info(test_runs)").fetchall()}
        if "group_name" not in cols:
            conn.execute("ALTER TABLE test_runs ADD COLUMN group_name TEXT")
        conn.commit()
    finally:
        conn.close()
