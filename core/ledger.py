"""사용량 원장 — A·B엔 없던 신규 코어 자산. "날 것의 사실"을 남기고 과금 공식은 나중에.

요청마다 tenant·기능·수량·provider·모델·성공여부·토큰(meta)을 append.
과금 단위(건당/페이지/토큰)나 상용/자체 구분은 이 원장 위에서 나중에 계산·변경한다.
"""
import json
from datetime import datetime, timezone

from core.db import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append(tenant: str, feature: str, quantity: int, unit: str,
           provider: str, model: str, ok: bool = True, meta: dict | None = None) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO usage_ledger (ts, tenant, feature, quantity, unit, provider, model, ok, meta)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), tenant, feature, quantity, unit, provider, model,
             1 if ok else 0, json.dumps(meta or {}, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


TEST_TENANT = "__test__"   # 콘솔 OCR 테스트 tenant. '__' 접두사 = 내부/비청구 tenant 구분자
INTERNAL_PREFIX = "__"     # 이 접두사 tenant는 화면에서 '실고객사' 필터로 걸러진다


def rollup(tenant: str | None = None) -> list[dict]:
    """고객사별·기능별·provider별 집계. 전부 반환하고, 실/테스트 구분은 tenant명(__접두사)으로.
    (화면이 __ 접두사로 필터링 — 실고객사/테스트/전체)."""
    conn = connect()
    try:
        sql = (
            "SELECT tenant, feature, provider, "
            "SUM(quantity) AS quantity, COUNT(*) AS requests, SUM(ok) AS ok_count "
            "FROM usage_ledger"
        )
        args: tuple = ()
        if tenant:
            sql += " WHERE tenant=?"
            args = (tenant,)
        sql += " GROUP BY tenant, feature, provider ORDER BY tenant, feature"
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()
