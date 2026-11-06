"""Authentication, CSRF, tenant isolation, security headers, and credentials."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.main import app
from app.security import decrypt_secret, encrypt_secret, hash_password, rate_limiter, verify_password
from tests.conftest import SALES_CSV, ApiClient


def anon() -> TestClient:
    return TestClient(app, base_url="http://localhost:8000")


def test_register_login_logout_cycle(api: ApiClient):
    assert api.get("/api/auth/me").json()["email"] == api.email
    assert api.post("/api/auth/logout").status_code == 200
    assert api.get("/api/auth/me").status_code == 401
    bad = api.client.post("/api/auth/login", json={"email": api.email, "password": "wrong-password-1"})
    assert bad.status_code == 401
    assert bad.json()["detail"] == "Incorrect email or password."
    good = api.client.post("/api/auth/login", json={"email": api.email, "password": api.password})
    assert good.status_code == 200
    assert api.get("/api/auth/me").status_code == 200


def test_weak_password_and_duplicate_email_are_rejected(api: ApiClient):
    client = anon()
    weak = client.post("/api/auth/register", json={"email": "weak@example.com", "full_name": "A", "password": "short1"})
    assert weak.status_code == 422
    letters = client.post("/api/auth/register", json={"email": "weak2@example.com", "full_name": "A", "password": "onlylettershere"})
    assert letters.status_code == 422
    duplicate = client.post("/api/auth/register", json={"email": api.email, "full_name": "A", "password": "another-password-1"})
    assert duplicate.status_code == 409


def test_password_hash_is_not_plaintext():
    hashed = hash_password("my-secret-pass-1")
    assert "my-secret-pass-1" not in hashed
    assert hashed.startswith("$argon2")
    assert verify_password("my-secret-pass-1", hashed)
    assert not verify_password("wrong", hashed)


def test_protected_routes_require_authentication():
    client = anon()
    for path in ("/api/overview", "/api/datasets", "/api/reports", "/api/connections", "/api/analyst/conversations", "/api/anomalies/runs", "/api/visualisations"):
        assert client.get(path).status_code == 401, path


def test_session_cookie_flags(api: ApiClient):
    client = anon()
    response = client.post("/api/auth/login", json={"email": api.email, "password": api.password})
    cookies = response.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("dataforge_session="))
    assert "HttpOnly" in session and "SameSite=lax" in session
    csrf = next(c for c in cookies if c.startswith("dataforge_csrf="))
    assert "HttpOnly" not in csrf


def test_csrf_required_on_state_changes(api: ApiClient):
    response = api.client.post("/api/projects", json={"name": "No header"}, headers={"X-Workspace-Id": api.workspace_id})
    assert response.status_code == 403
    wrong = api.client.post("/api/projects", json={"name": "Bad"}, headers={"X-CSRF-Token": "forged", "X-Workspace-Id": api.workspace_id})
    assert wrong.status_code == 403
    assert api.post("/api/projects", json={"name": "Good"}).status_code == 201


def test_foreign_origin_is_blocked(api: ApiClient):
    response = api.post("/api/projects", json={"name": "Evil"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    allowed = api.post("/api/projects", json={"name": "Allowed"}, headers={"Origin": "http://localhost:5173"})
    assert allowed.status_code == 201


def test_security_headers_present():
    response = anon().get("/api/health")
    headers = response.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["cache-control"] == "no-store"


def test_user_isolation_across_every_resource(api: ApiClient, other_api: ApiClient):
    dataset = api.upload("sales.csv", SALES_CSV)
    dataset_id = dataset["id"]
    run = api.post("/api/anomalies/run", json={"dataset_id": dataset_id}).json()
    report = api.post("/api/reports", json={"dataset_id": dataset_id, "report_type": "data_quality"}).json()
    viz = api.post("/api/visualisations", json={"dataset_id": dataset_id, "name": "c", "spec": {"chart_type": "bar", "x": "region", "y": "revenue"}}).json()
    chat = api.post("/api/analyst/ask", json={"dataset_id": dataset_id, "question": "total revenue"}).json()

    attempts = [
        other_api.get(f"/api/datasets/{dataset_id}"),
        other_api.get(f"/api/datasets/{dataset_id}/profile"),
        other_api.post(f"/api/datasets/{dataset_id}/rows", json={}),
        other_api.post(f"/api/datasets/{dataset_id}/export", json={}),
        other_api.patch(f"/api/datasets/{dataset_id}", json={"name": "stolen"}),
        other_api.delete(f"/api/datasets/{dataset_id}"),
        other_api.post(f"/api/datasets/{dataset_id}/duplicate"),
        other_api.post(f"/api/datasets/{dataset_id}/cleaning/preview", json={"operations": [{"op": "remove_duplicates"}]}),
        other_api.post("/api/charts/run", json={"dataset_id": dataset_id, "spec": {"chart_type": "bar", "x": "region", "y": "revenue"}}),
        other_api.post("/api/analyst/ask", json={"dataset_id": dataset_id, "question": "total revenue"}),
        other_api.get(f"/api/analyst/conversations/{chat['conversation_id']}"),
        other_api.post("/api/anomalies/run", json={"dataset_id": dataset_id}),
        other_api.get(f"/api/anomalies/runs/{run['id']}/results"),
        other_api.get(f"/api/reports/{report['id']}"),
        other_api.get(f"/api/reports/{report['id']}/export/pdf"),
        other_api.delete(f"/api/reports/{report['id']}"),
        other_api.delete(f"/api/visualisations/{viz['id']}"),
        other_api.get(f"/api/visualisations/{viz['id']}/data"),
    ]
    for response in attempts:
        assert response.status_code == 404, response.request.url
    assert other_api.get("/api/datasets").json() == []
    assert other_api.get("/api/reports").json() == []
    assert api.get(f"/api/datasets/{dataset_id}").json()["name"] == "sales"


def test_cannot_select_a_workspace_you_do_not_belong_to(api: ApiClient, other_api: ApiClient):
    api.upload("sales.csv", SALES_CSV)
    response = other_api.get("/api/datasets", headers={"X-Workspace-Id": api.workspace_id})
    assert response.status_code == 404


def test_workspace_roles(api: ApiClient, other_api: ApiClient):
    dataset = api.upload("sales.csv", SALES_CSV)
    added = api.post("/api/workspaces/current/members", json={"email": other_api.email, "role": "viewer"})
    assert added.status_code == 201
    other_api.workspace_id = api.workspace_id
    assert other_api.get(f"/api/datasets/{dataset['id']}").status_code == 200
    assert other_api.delete(f"/api/datasets/{dataset['id']}").status_code == 403
    assert other_api.post("/api/analyst/ask", json={"dataset_id": dataset["id"], "question": "total revenue"}).status_code == 403
    assert other_api.get("/api/audit-logs").status_code == 403
    api.patch(f"/api/workspaces/current/members/{added.json()['id']}", json={"role": "member"})
    assert other_api.post("/api/analyst/ask", json={"dataset_id": dataset["id"], "question": "total revenue"}).status_code == 200
    assert other_api.delete(f"/api/workspaces/current/members/{added.json()['id']}").status_code == 403


def test_conversations_are_private_within_a_workspace(api: ApiClient, other_api: ApiClient):
    dataset = api.upload("sales.csv", SALES_CSV)
    chat = api.post("/api/analyst/ask", json={"dataset_id": dataset["id"], "question": "total revenue"}).json()
    api.post("/api/workspaces/current/members", json={"email": other_api.email, "role": "member"})
    other_api.workspace_id = api.workspace_id
    assert other_api.get(f"/api/analyst/conversations/{chat['conversation_id']}").status_code == 404
    assert other_api.get("/api/analyst/conversations").json() == []


def test_password_reset_flow(api: ApiClient):
    client = anon()
    unknown = client.post("/api/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert unknown.status_code == 200 and "dev_reset_link" not in unknown.json()
    response = client.post("/api/auth/password-reset/request", json={"email": api.email})
    assert response.json()["message"] == unknown.json()["message"]
    token = re.search(r"token=([\w-]+)", response.json()["dev_reset_link"]).group(1)
    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "brand-new-password-2"}).status_code == 200
    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "another-password-3"}).status_code == 400
    assert api.get("/api/auth/me").status_code == 401, "existing sessions end after a reset"
    assert client.post("/api/auth/login", json={"email": api.email, "password": "brand-new-password-2"}).status_code == 200


def test_login_rate_limit(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_auth_per_minute", 3)
    rate_limiter.reset()
    client = anon()
    codes = [client.post("/api/auth/login", json={"email": "x@example.com", "password": "whatever-1"}).status_code for _ in range(5)]
    rate_limiter.reset()
    assert codes[:3] == [401, 401, 401]
    assert codes[3:] == [429, 429]


def test_credentials_are_encrypted():
    token = encrypt_secret({"password": "hunter2-secret"})
    assert "hunter2-secret" not in token
    assert decrypt_secret(token)["password"] == "hunter2-secret"


def test_unhandled_error_does_not_leak_details(api: ApiClient, monkeypatch):
    from app.api import datasets as module

    def explode(*_args, **_kwargs):
        raise RuntimeError(r"C:\secret\path password=hunter2")

    monkeypatch.setattr(module, "fetch_rows", explode)
    client = TestClient(app, base_url="http://localhost:8000", raise_server_exceptions=False, cookies=dict(api.client.cookies))
    dataset = api.upload("sales.csv", SALES_CSV)
    response = client.post(f"/api/datasets/{dataset['id']}/rows", json={}, headers=api._headers())
    assert response.status_code == 500
    assert "secret" not in response.text and "hunter2" not in response.text
