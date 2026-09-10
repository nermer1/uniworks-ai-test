"""첫 관리자 유저 심기 — 사내 화면 로그인용. seed_key.py의 유저 버전.

실행: py scripts/seed_admin.py [username] [password]
  - username 생략 시 'admin'
  - password 생략 시 랜덤 생성해 1회 출력
이미 있는 username이면 건너뜀.
"""
import sys
import secrets
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import init_db                              # noqa: E402
from core.users import create_user, get_user_by_username  # noqa: E402


def main():
    init_db()
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    password = sys.argv[2] if len(sys.argv) > 2 else ("pw-" + secrets.token_urlsafe(12))
    role = "관리자"

    if get_user_by_username(username):
        print(f"이미 존재하는 사용자: {username} (건너뜀)")
        return

    uid = create_user(username, password, role)
    print("=" * 50)
    print("관리자 유저 발급:")
    print(f"  username = {username}")
    print(f"  password = {password}   ← 지금만 표시(비번은 해시로 저장됨)")
    print(f"  role     = {role}  id={uid}")
    print("=" * 50)


if __name__ == "__main__":
    main()
