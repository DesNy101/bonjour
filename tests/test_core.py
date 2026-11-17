import pytest
from tests.conftest import Api, uniq


def test_startup_health_and_db(app):
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["database"] == "up"
    assert c.get("/openapi.json").status_code == 200


def test_migrations_created_core_tables(app):
    from sqlalchemy import inspect
    from app.database import engine
    names = set(inspect(engine).get_table_names())
    for t in ("users", "orders", "stock_movements", "production_batches", "delivery_runs", "financial_transactions", "audit_logs", "alembic_version"):
        assert t in names


def test_invalid_login_and_lockout(app, world):
    a = Api(app)
    assert a.login("nobody@bonjour-test.com", "whatever1").status_code == 401
    email = f"lock.{uniq()}@bonjour-test.com"
    owner = Api(app); owner.login("owner@bonjour-test.com", "OwnerPass2026")
    assert owner.post("/api/staff", json={"full_name": "Lock Me", "email": email, "role_key": "general_staff", "password": "StaffPass2026"}).status_code == 201
    from app.middleware.security import limiter
    for _ in range(5):
        assert a.login(email, "wrong-pass1").status_code == 401
        limiter.reset()
    assert a.login(email, "StaffPass2026").status_code == 423  # locked even with the right password


def test_password_is_hashed_with_argon2(app, world):
    from app.database import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "owner@bonjour-test.com").one()
        assert u.password_hash.startswith("$argon2") and "OwnerPass2026" not in u.password_hash


def test_unauthenticated_and_csrf(app, world):
    a = Api(app)
    assert a.get("/api/orders").status_code == 401
    b = Api(app); b.login("owner@bonjour-test.com", "OwnerPass2026")
    del b.c.headers["x-csrf-token"]
    r = b.post("/api/product-categories", json={"name": "NoCsrf", "kind": "finished"})
    assert r.status_code == 403 and "CSRF" in r.json()["detail"]


def test_logout_invalidates_session(app, world):
    a = Api(app); a.login("owner@bonjour-test.com", "OwnerPass2026")
    assert a.get("/api/auth/me").status_code == 200
    token = a.c.cookies.get("bj_session")
    assert a.post("/api/auth/logout").status_code == 200
    a.c.cookies.set("bj_session", token)  # replay the old cookie
    assert a.get("/api/auth/me").status_code == 401


def test_role_permissions_enforced_on_backend(world):
    assert world["sales_a"].post("/api/staff", json={"full_name": "x y", "email": "x@y.com", "role_key": "general_staff"}).status_code == 403
    assert world["sales_a"].get("/api/finance/summary").status_code == 403
    assert world["acct"].post("/api/inventory/movements", json={"product_id": world["bread"], "branch_id": world["AAA"], "movement_type": "addition", "quantity": 1, "reason": "nope nope"}).status_code == 403
    assert world["gen_staff"].get("/api/orders").status_code == 403
    assert world["driver1"].get("/api/dashboard").status_code == 403


def test_changing_role_changes_permissions(admin, app, world):
    email = f"mover.{uniq()}@bonjour-test.com"
    r = admin.post("/api/staff", json={"full_name": "Mover M", "email": email, "role_key": "general_staff", "password": "StaffPass2026", "branch_id": world["AAA"]})
    uid = r.json()["id"]
    u = Api(app); u.login(email, "StaffPass2026")
    assert u.get("/api/orders").status_code == 403
    assert admin.patch(f"/api/staff/{uid}", json={"role_key": "sales_officer"}).status_code == 200
    assert u.get("/api/orders").status_code == 401  # old session revoked
    u.login(email, "StaffPass2026")
    assert u.get("/api/orders").status_code == 200


def test_deactivated_account_loses_access(admin, app, world):
    email = f"gone.{uniq()}@bonjour-test.com"
    uid = admin.post("/api/staff", json={"full_name": "Gone Soon", "email": email, "role_key": "sales_officer", "password": "StaffPass2026", "branch_id": world["AAA"]}).json()["id"]
    u = Api(app); u.login(email, "StaffPass2026")
    assert u.get("/api/orders").status_code == 200
    assert admin.patch(f"/api/staff/{uid}", json={"is_active": False}).status_code == 200
    assert u.get("/api/orders").status_code == 401
    assert u.login(email, "StaffPass2026").status_code == 401


def test_branch_manager_cannot_grant_privileged_roles(world):
    r = world["branch_mgr_a"].post("/api/staff", json={"full_name": "Evil Boss", "email": "evil@bonjour-test.com", "role_key": "super_admin"})
    assert r.status_code in (403,)


def test_reset_password_flow(admin, app, world):
    email = f"reset.{uniq()}@bonjour-test.com"
    uid = admin.post("/api/staff", json={"full_name": "Reset Me", "email": email, "role_key": "general_staff", "password": "StaffPass2026"}).json()["id"]
    r = admin.post(f"/api/staff/{uid}/reset-password")
    tmp = r.json()["temporary_password"]
    u = Api(app)
    assert u.login(email, "StaffPass2026").status_code == 401
    assert u.login(email, tmp).status_code == 200 and u.user["must_change_password"] is True
