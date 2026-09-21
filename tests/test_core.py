"""코어 계약 — envelope, 인증, 모델 권한, OCR(mock). 네트워크/모델 불필요(mock)."""


def test_health_envelope(client):
    r = client.get("/core/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "ok"
    assert body["meta"]["request_id"]           # 요청ID 실림
    assert r.headers.get("x-request-id")        # 응답 헤더에도


def test_ocr_requires_key(client):
    r = client.post("/ocr", files={"files": ("t.png", b"x", "image/png")})
    assert r.status_code == 401
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_ocr_mock_success(client, api_key):
    r = client.post("/ocr", headers={"X-API-Key": api_key},
                    data={"model": "mock"},
                    files={"files": ("t.png", b"x", "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["meta"]["usage"]["provider"] == "mock"   # usage는 meta에 (data=결과, meta=메타)
    # 응답은 항상 files[] 통일. 단일 파일도 files 1개 → pages 1개.
    file0 = body["data"]["files"][0]
    assert file0["ok"] is True
    assert "가맹점명" in file0["pages"][0]["result"]


def test_ocr_multi_file(client, api_key):
    # 파일 2개 동시 업로드 → files 2개, 각각 성공
    r = client.post("/ocr", headers={"X-API-Key": api_key},
                    data={"model": "mock"},
                    files=[("files", ("a.png", b"x", "image/png")),
                           ("files", ("b.png", b"y", "image/png"))])
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["file_count"] == 2
    assert len(body["data"]["files"]) == 2
    assert body["meta"]["usage"]["ok_count"] == 2


def test_ocr_model_forbidden(client, api_key):
    # 키는 mock만 허용 → vertex 요청은 403
    r = client.post("/ocr", headers={"X-API-Key": api_key},
                    data={"model": "vertex"},
                    files={"files": ("t.png", b"x", "image/png")})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_ocr_test_route_developer_ok(client):
    """콘솔 OCR 테스트 라우트 — 개발자(ocr:test)는 세션 로그인 후 접근 가능."""
    from core import users
    users.create_user("t_ocrdev", "pw", "개발자")
    client.post("/auth/login", data={"username": "t_ocrdev", "password": "pw"})
    r = client.post("/ocr/test", data={"model": "mock", "doc_type": "card"},
                    files={"files": ("t.png", b"x", "image/png")})
    assert r.status_code == 200
    assert r.json()["data"]["files"][0]["ok"] is True


def test_ocr_test_history_records_run(client):
    """테스트 실행 → 이력에 남고, 상세에 결과 JSON 포함."""
    from core import users
    users.create_user("t_hist", "pw", "개발자")
    client.post("/auth/login", data={"username": "t_hist", "password": "pw"})
    client.post("/ocr/test", data={"model": "mock", "doc_type": "card"},
                files={"files": ("t.png", b"x", "image/png")})
    runs = client.get("/ocr/test/history").json()["data"]["runs"]
    assert len(runs) >= 1
    detail = client.get(f"/ocr/test/history/{runs[0]['id']}").json()["data"]
    assert detail["result"]["files"][0]["ok"] is True
    # 삭제 → 목록에서 사라짐
    d = client.post("/ocr/test/history/delete", json={"ids": [runs[0]["id"]]})
    assert d.status_code == 200 and d.json()["data"]["deleted"] == 1
    assert all(r["id"] != runs[0]["id"] for r in client.get("/ocr/test/history").json()["data"]["runs"])


def test_test_run_recorded_under_test_tenant(client):
    """콘솔 테스트 실행은 __test__ tenant로 원장에 남는다(실/테스트 구분은 tenant명, 필터는 화면)."""
    from core import users
    users.create_user("t_admin2", "pw", "관리자")            # 관리자 = ocr:test + usage:read 둘 다
    client.post("/auth/login", data={"username": "t_admin2", "password": "pw"})
    client.post("/ocr/test", data={"model": "mock", "doc_type": "card"},
                files={"files": ("t.png", b"x", "image/png")})
    rollup = client.get("/core/usage").json()["data"]["rollup"]
    assert any(r["tenant"] == "__test__" for r in rollup)


def test_ocr_test_route_accounting_forbidden(client):
    """회계는 ocr:test 권한 없음 → 403."""
    from core import users
    users.create_user("t_ocracc", "pw", "회계")
    client.post("/auth/login", data={"username": "t_ocracc", "password": "pw"})
    r = client.post("/ocr/test", data={"model": "mock", "doc_type": "card"},
                    files={"files": ("t.png", b"x", "image/png")})
    assert r.status_code == 403


def test_recommend_mock(client, api_key):
    r = client.post("/recommend", headers={"X-API-Key": api_key},
                    json={"merchant_name": "스타벅스"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["data"]["recommendations"]) > 0
