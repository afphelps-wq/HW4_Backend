import jwt

from app.config import JWT_ALGORITHM, jwt_secret


def test_login_success_and_me(client, auth_headers):
    headers = auth_headers()
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "alice@lab.org"
    assert "password_hash" not in me.json()


def test_login_is_case_insensitive_on_email(client, make_user):
    make_user("alice@lab.org", "correct-horse-1")
    r = client.post("/auth/login", json={"email": "Alice@Lab.ORG", "password": "correct-horse-1"})
    assert r.status_code == 200


def test_login_wrong_password_and_unknown_user_look_identical(client, make_user):
    make_user()
    bad_pw = client.post("/auth/login", json={"email": "alice@lab.org", "password": "nope"})
    no_user = client.post("/auth/login", json={"email": "ghost@lab.org", "password": "nope"})
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json()


def test_overlong_password_is_401_not_500(client, make_user):
    make_user()
    r = client.post("/auth/login", json={"email": "alice@lab.org", "password": "x" * 150})
    assert r.status_code == 401


def test_inactive_user_cannot_login_or_use_existing_token(client, make_user, session_factory):
    from app.models import User

    headers_user = "bob@lab.org"
    make_user(headers_user, "correct-horse-1")
    token = client.post(
        "/auth/login", json={"email": headers_user, "password": "correct-horse-1"}
    ).json()["access_token"]
    with session_factory() as db:
        db.query(User).filter_by(email=headers_user).one().is_active = False
        db.commit()
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    r = client.post("/auth/login", json={"email": headers_user, "password": "correct-horse-1"})
    assert r.status_code == 401


def test_missing_bad_and_expired_tokens_are_401(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    expired = jwt.encode({"sub": "00000000-0000-0000-0000-000000000000", "exp": 1},
                         jwt_secret(), algorithm=JWT_ALGORITHM)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_no_public_registration_route(client):
    assert client.post("/auth/register", json={}).status_code == 404
