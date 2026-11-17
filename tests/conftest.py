import os
os.environ["BOOTSTRAP_SYNC"] = "1"
import secrets
import subprocess
import sys
from pathlib import Path

TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@/bonjour_test?host=/tmp&port=5433")
os.environ["DATABASE_URL"] = TEST_URL
os.environ["ADMIN_EMAIL"] = "owner@bonjour-test.com"
os.environ["ADMIN_PASSWORD"] = "OwnerPass2026"
os.environ["APP_ENV"] = "development"
os.environ["UPLOAD_DIR"] = "/tmp/bonjour-test-uploads"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    """Fresh schema built through the real Alembic migrations (this is also the migration test)."""
    from app.database import engine
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, capture_output=True, text=True, env=os.environ)
    assert r.returncode == 0, r.stderr
    yield


@pytest.fixture(scope="session")
def app(migrated_db):
    from app.main import app as a
    with TestClient(a):  # runs lifespan -> bootstrap (roles, admin)
        yield a


class Api:
    def __init__(self, app):
        self.c = TestClient(app, base_url="http://testserver")

    def login(self, email, password):
        r = self.c.post("/api/auth/login", json={"email": email, "password": password})
        if r.status_code == 200:
            self.c.headers["x-csrf-token"] = r.json()["csrf_token"]
            self.user = r.json()["user"]
        return r

    def get(self, *a, **k): return self.c.get(*a, **k)
    def post(self, *a, **k): return self.c.post(*a, **k)
    def put(self, *a, **k): return self.c.put(*a, **k)
    def patch(self, *a, **k): return self.c.patch(*a, **k)


@pytest.fixture(autouse=True)
def _reset_limiter():
    from app.middleware.security import limiter
    limiter.reset()


@pytest.fixture(scope="session")
def admin(app):
    a = Api(app)
    r = a.login("owner@bonjour-test.com", "OwnerPass2026")
    assert r.status_code == 200, r.text
    return a


def uniq(p="x"):
    return f"{p}{secrets.token_hex(3)}"


@pytest.fixture(scope="session")
def world(admin, app):
    """A small bakery: 2 branches, staff in each role, products, materials, recipe, stock."""
    w = {}
    for code, name in (("AAA", "Alpha Branch"), ("BBB", "Beta Branch")):
        r = admin.post("/api/branches", json={"code": code + uniq("")[:2].upper(), "name": name, "lga": "Yenagoa"})
        assert r.status_code == 201, r.text
        w[code] = r.json()["id"]
    A, B = w["AAA"], w["BBB"]

    def staff(role, branch=None, **kw):
        email = f"{role}.{uniq()}@bonjour-test.com"
        r = admin.post("/api/staff", json={"full_name": f"{role} user", "email": email, "role_key": role, "branch_id": branch,
                                           "password": "StaffPass2026", **kw})
        assert r.status_code == 201, r.text
        api = Api(app)
        assert api.login(email, "StaffPass2026").status_code == 200
        api.id = r.json()["id"]
        return api

    w["branch_mgr_a"] = staff("branch_manager", A)
    w["sales_a"] = staff("sales_officer", A)
    w["inv_a"] = staff("inventory_manager", A)
    w["prod_a"] = staff("production_manager", A)
    w["dispatch_a"] = staff("dispatch_manager", A)
    w["acct"] = staff("accountant", None)
    w["driver1"] = staff("driver", A, license_no="LIC1")
    w["driver2"] = staff("driver", A, license_no="LIC2")
    w["gen_staff"] = staff("general_staff", A)
    w["branch_mgr_b"] = staff("branch_manager", B)

    def prod(**kw):
        r = admin.post("/api/products", json=kw)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    w["bread"] = prod(sku=uniq("BRD"), name="Test Family Bread", kind="finished", price_kobo=180000, wholesale_price_kobo=150000, reorder_level=5, size_label="Family")
    w["flour"] = prod(sku=uniq("FLR"), name="Test Flour", kind="raw", unit="kg", cost_kobo=90000, reorder_level=10)
    w["yeast"] = prod(sku=uniq("YST"), name="Test Yeast", kind="raw", unit="kg", cost_kobo=250000, reorder_level=1)
    for m in ("flour", "yeast"):
        assert admin.post("/api/inventory/movements", json={"product_id": w[m], "branch_id": A, "movement_type": "addition", "quantity": 500, "reason": "initial test stock"}).status_code == 201
    r = admin.post("/api/production/recipes", json={"product_id": w["bread"], "name": "Family loaf", "yield_qty": 10,
                                                    "ingredients": [{"material_id": w["flour"], "quantity": 5}, {"material_id": w["yeast"], "quantity": 0.1}]})
    assert r.status_code == 201, r.text
    w["vehicle"] = admin.post("/api/vehicles", json={"plate_number": uniq("YEN-").upper(), "capacity_units": 50}).json()["id"]
    w["vehicle2"] = admin.post("/api/vehicles", json={"plate_number": uniq("BYS-").upper(), "capacity_units": 5}).json()["id"]
    return w
