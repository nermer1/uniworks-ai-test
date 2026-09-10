"""코어 계약 — envelope, 인증, 모델 권한, OCR(mock). 네트워크/모델 불필요(card-mock)."""


def test_health_envelope(client):
    r = client.get("/core/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "ok"
    assert body["meta"]["request_id"]           # 요청ID 실림
    assert r.headers.get("x-request-id")        # 응답 헤더에도


def test_ocr_requires_key(client):
    r = client.post("/ocr", files={"file": ("t.png", b"x", "image/png")})
    assert r.status_code == 401
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_ocr_mock_success(client, api_key):
    r = client.post("/ocr", headers={"X-API-Key": api_key},
                    data={"model": "card-mock"},
                    files={"file": ("t.png", b"x", "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["meta"]["usage"]["provider"] == "mock"   # usage는 meta에 (data=결과, meta=메타)
    assert "가맹점명" in body["data"]["result"]


def test_ocr_model_forbidden(client, api_key):
    # 키는 card-mock만 허용 → card-vertex 요청은 403
    r = client.post("/ocr", headers={"X-API-Key": api_key},
                    data={"model": "card-vertex"},
                    files={"file": ("t.png", b"x", "image/png")})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_recommend_mock(client, api_key):
    r = client.post("/recommend", headers={"X-API-Key": api_key},
                    json={"merchant_name": "스타벅스"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["data"]["recommendations"]) > 0
