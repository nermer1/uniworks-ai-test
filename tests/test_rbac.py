"""유저 인증 + role→permission RBAC — 세션 로그인 후 권한별 접근 차단 검증."""
from core import users


def _login(client, username, password):
    return client.post("/auth/login", data={"username": username, "password": password})


def test_password_hash_roundtrip():
    salt, h = users.hash_password("secret")
    assert users.verify_password("secret", salt, h)
    assert not users.verify_password("wrong", salt, h)


def test_login_bad_password(client):
    users.create_user("t_x", "goodpw", "관리자")
    assert _login(client, "t_x", "badpw").status_code == 401


def test_rbac_accounting(client):
    users.create_user("t_acc", "pw", "회계")
    assert _login(client, "t_acc", "pw").status_code == 200
    assert client.get("/core/usage").status_code == 200      # 회계 = usage:read ✓
    assert client.get("/admin/users").status_code == 403     # users:manage ✗


def test_rbac_developer(client):
    users.create_user("t_dev", "pw", "개발자")
    assert _login(client, "t_dev", "pw").status_code == 200
    assert client.get("/core/logs").status_code == 200       # logs:read ✓
    assert client.get("/core/usage").status_code == 403      # usage:read ✗


def test_admin_full_access(client):
    users.create_user("t_admin", "pw", "관리자")
    assert _login(client, "t_admin", "pw").status_code == 200
    assert client.get("/core/usage").status_code == 200      # 관리자 = "*"
    assert client.get("/admin/users").status_code == 200
    assert client.get("/core/logs").status_code == 200
