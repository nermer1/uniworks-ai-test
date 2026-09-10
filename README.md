# AI API Platform — 뼈대 (Stage 1)

공용 코어 + 꽂아 쓰는 기능 모듈(모듈러 모놀리스)의 **1단계 수직 슬라이스**.

관통 목표: `API Key로 /ocr 호출 → 인증 → 모델 게이트웨이 호출 → 사용량 원장 1행 → 모니터링에 남음`.
GPU/RunPod 없이도 돌도록 **mock provider**가 기본값이라 바로 실행 가능.

## 구조

```
aiplatform/
├─ app.py                  FastAPI 앱: 코어 초기화 + 계약된 모듈만 mount
├─ core/                   공용 코어 (모든 모듈이 공유하는 라이브러리)
│  ├─ config.py            설정 로드 (어떤 모듈 켜냐 / 어떤 provider 쓰냐) — 파일 읽어 hot-reload
│  ├─ db.py                SQLite 연결(WAL) + 테이블 생성
│  ├─ auth.py              API Key 검증 → Principal(tenant, capabilities)
│  ├─ permissions.py       capability 매트릭스 (기능·모델 권한 체크)
│  ├─ ledger.py            사용량 원장 append / 고객사별 롤업        ★신규(A·B엔 없던 것)
│  ├─ model_gateway.py     litellm 자리 — 자체 vLLM ↔ 상용 ↔ mock 스위치
│  ├─ prompt_store.py      프롬프트 조회 (파일, 편집하면 다음 요청부터 반영)
│  ├─ monitoring.py        접근 로그 미들웨어
│  └─ registry.py          config의 enabled_modules만 import·mount
├─ modules/
│  ├─ ocr/                 B(OCR) 모듈
│  │  ├─ router.py         POST /ocr
│  │  ├─ extract.py        이미지→JSON (model_gateway 통해서만 모델 호출)
│  │  └─ manifest.py       이 모듈이 뭘 요구하는지 선언
│  └─ recommend/           A(추천) 모듈 — Stage 3 (지금은 자리만)
├─ config/app.config.json  배포별 설정
├─ scripts/seed_key.py     데모 API Key 발급
└─ data/                   app.db(SQLite), prompts/ (런타임 산출물은 gitignore)
```

## 실행

```bash
py -m pip install -r requirements.txt              # 코어 (항상)
# 산 것만 추가 설치 (à la carte):
#   py -m pip install -r requirements-ocr.txt       # OCR 모듈 쓰면 (PyMuPDF + litellm)
#   py -m pip install -r requirements-vertex.txt    # vertex_ai provider 쓰면
#   py -m pip install -r requirements-recommend.txt # recommend 모듈 쓰면
py scripts/seed_key.py          # API Key 발급 (한 번만 표시됨 — 복사해둘 것)
py -m uvicorn app:app --port 8080
```

**의존성도 à la carte**: 코어 requirements는 항상 설치, 나머지는 그 배포가 실제 쓰는
provider/모듈 것만 추가 설치한다. (OCR만 산 고객 서버엔 추천의 torch가 안 깔림)

## 수직 슬라이스 테스트

`KEY`는 seed_key.py가 출력한 값. mock provider라 아무 파일이나 올려도 관통 확인됨.

```bash
# 1) OCR 호출 (mock 모델이 샘플 JSON 반환 + 원장에 1행 기록)
curl -H "X-API-Key: KEY" -F "file=@아무이미지.jpg" http://localhost:8080/ocr

# 2) 사용량 롤업 (회계 화면이 쓸 데이터) — admin 권한 필요
curl -H "X-API-Key: KEY" http://localhost:8080/core/usage
```

`/ocr`이 `{result, usage:{pages,provider,model,tokens}}`를 주고, `/core/usage`에
`demo-corp / ocr / mock` 집계 1건이 뜨면 관통 성공.

## provider 토글 (Stage 2 미리보기)

`config/app.config.json`의 `default_model`을 바꾸면 코드 수정 없이 백엔드가 갈림:
- `mock` — 로컬 목업 (기본, 모델 불필요)
- `vllm` — 자체 vLLM (OpenAI 호환) `base_url` 넣으면 사용
- `gemini` — 상용 (Gemini AI Studio, `GEMINI_API_KEY`)
- `vertex` — Vertex AI (GCP 서비스계정)

이게 "옵션만 토글" 의 실체. `model_gateway.py`를 litellm으로 교체하면 provider가 더 늘어남.

## 다음 단계
- Stage 2: model_gateway를 실제 vLLM/상용에 연결 + provider 토글 검증
- Stage 3: `modules/recommend/` 에 A 스코어링·Qdrant 이식 (코어 안 건드리고 모듈만 추가)
- Stage 4: role별 화면(개발자/회계/관리자)
