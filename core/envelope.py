"""응답 계약 (A안 — envelope로 감싸기).

성공: {ok:true,  data:{...}, meta:{request_id, ...}}
실패: {ok:false, error:{code, message, detail?}, meta:{request_id}}

모든 엔드포인트는 success()로 감싸 반환하고, 실패는 core.errors.ApiError를 raise한다
(전역 핸들러가 error 형태로 변환). 클라이언트는 항상 같은 형태를 받는다.
"""
from typing import Any

from core.context import request_id_var


def success(data: Any = None, **meta) -> dict:
    m = {"request_id": request_id_var.get()}
    m.update(meta)
    return {"ok": True, "data": data, "meta": m}


def error_body(code: str, message: str, detail: Any = None) -> dict:
    err = {"code": code, "message": message}
    if detail is not None:
        err["detail"] = detail
    return {"ok": False, "error": err, "meta": {"request_id": request_id_var.get()}}
