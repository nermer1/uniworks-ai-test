# recommend 모듈 (Stage 3 예정)

A(추천) 엔진을 여기로 이식한다. **코어는 건드리지 않고 이 폴더만 추가**되는 것이
모듈러 구조가 실제로 동작한다는 증거가 된다.

예정 파일:
- `router.py` — `/recommend`, `/ingest`
- `engine.py` — Adaptive Max-Weighted 스코어링 (레퍼런스 A의 core.py에서 이식)
- `vectorstore.py` — Qdrant 클라이언트 (이 모듈 전용 의존)
- `manifest.py` — `requires: {vector_store, text_embedding}` 선언
- `__init__.py` — `register(app)` 노출

켜는 법: `config/app.config.json` 의 `enabled_modules` 에 `"recommend"` 추가.
(추가 전엔 import조차 안 되므로 torch/qdrant 의존성도 안 딸려온다 = à la carte)
