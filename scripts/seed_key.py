"""데모 API Key 발급 — 뼈대 테스트용.

발급 키를 한 번만 출력(원문은 저장 안 함, 해시만 DB에). tenant=demo-corp.
실행: py scripts/seed_key.py
"""
import sys
import json
import uuid
import secrets
from pathlib import Path
from datetime import datetime, timezone

# 프로젝트 루트를 import 경로에 추가 (scripts/ 하위에서 실행되므로)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import init_db, connect          # noqa: E402
from core.auth import hash_key                 # noqa: E402


def main():
    init_db()
    raw_key = "sk-" + secrets.token_urlsafe(32)
    key_id = uuid.uuid4().hex[:8]
    capabilities = {
        "features": ["ocr", "recommend", "admin"],
        "models": ["card-mock", "card-9b", "card-commercial", "card-vertex"],
    }
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO api_keys (id, key_hash, tenant, capabilities, is_active, created_at)"
            " VALUES (?, ?, ?, ?, 1, ?)",
            (key_id, hash_key(raw_key), "demo-corp",
             json.dumps(capabilities, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    print("=" * 50)
    print("발급된 API Key (이번 한 번만 표시됨):")
    print("  " + raw_key)
    print(f"  tenant=demo-corp  id={key_id}")
    print(f"  features={capabilities['features']}")
    print("=" * 50)


if __name__ == "__main__":
    main()
