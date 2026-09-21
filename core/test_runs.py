"""테스트 실행 이력 저장소 — 콘솔 테스트 결과를 보관해 나중에 다시 조회.

usage_ledger(과금용 날 것의 사실)와 별개다. 여기는 "테스트해본 결과 자체"를 남겨
이력 화면에서 되짚어 본다. kind로 종류를 구분해 추후 부하테스트도 같은 표를 공용한다.
"""
import json
from datetime import datetime, timezone

from core.db import connect

_COLS = ("ts", "username", "group_name", "kind", "provider", "model", "doc_type",
         "file_count", "page_count", "ok_count", "fail_count",
         "wall_ms", "work_ms", "total_tokens", "result")


def record(username: str, kind: str, provider: str | None, model: str | None,
           doc_type: str | None, file_count: int, page_count: int,
           ok_count: int, fail_count: int, wall_ms: int, work_ms: int,
           total_tokens: int, result: dict, group_name: str = "") -> None:
    conn = connect()
    try:
        conn.execute(
            f"INSERT INTO test_runs ({', '.join(_COLS)}) VALUES ({', '.join(['?'] * len(_COLS))})",
            (datetime.now(timezone.utc).isoformat(), username, group_name or None, kind,
             provider, model, doc_type, file_count, page_count, ok_count, fail_count,
             wall_ms, work_ms, total_tokens, json.dumps(result, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def recent(limit: int = 200) -> list[dict]:
    """이력 목록 — 상세(result) 제외한 요약만(가벼움). 비교뷰도 이 데이터를 씀."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, ts, username, group_name, kind, provider, model, doc_type, file_count,"
            " page_count, ok_count, fail_count, wall_ms, work_ms, total_tokens"
            " FROM test_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def groups() -> list[str]:
    """그룹명 목록 (자동완성·비교용). 지정 안 된 실행은 제외."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT group_name FROM test_runs WHERE group_name IS NOT NULL AND group_name != ''"
            " GROUP BY group_name ORDER BY MAX(id) DESC"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def delete(ids: list[int]) -> int:
    """여러 이력 삭제 → 삭제된 행 수. (개별 삭제 = 길이 1 리스트)"""
    ids = [int(i) for i in ids]
    if not ids:
        return 0
    conn = connect()
    try:
        placeholders = ",".join("?" * len(ids))
        cur = conn.execute(f"DELETE FROM test_runs WHERE id IN ({placeholders})", tuple(ids))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get(run_id: int) -> dict | None:
    """단건 상세 — result(JSON) 파싱해서 포함."""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM test_runs WHERE id=?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    d = dict(row)
    try:
        d["result"] = json.loads(d["result"]) if d.get("result") else None
    except (json.JSONDecodeError, TypeError):
        d["result"] = None
    return d
