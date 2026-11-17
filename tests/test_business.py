from datetime import datetime, timedelta, timezone
import pytest
from tests.conftest import Api, uniq


def order_payload(w, qty=2, otype="pickup", method="cash_at_pickup", branch=None, **kw):
    d = {"branch_id": branch or w["AAA"], "order_type": otype, "contact_name": "Ada Obi", "contact_phone": "08031234567",
         "contact_email": "ada@bonjour-test.com", "payment_method": method, "items": [{"product_id": w["bread"], "quantity": qty}]}
    if otype == "delivery":
        d.update({"delivery_address": "12 Mbiama Rd, Yenagoa", "delivery_lga": "Yenagoa"})
    d.update(kw)
    return d


def stock(admin, w, pid, branch):
    r = admin.get("/api/inventory/stock", params={"branch_id": branch})
    return next((i["quantity"] for i in r.json()["items"] if i["product_id"] == pid), 0)


def test_product_creation_validation(admin, world):
    r = admin.post("/api/products", json={"sku": uniq("P"), "name": "Cheap", "kind": "finished", "price_kobo": 0})
    assert r.status_code == 400  # sellable needs price
    sku = uniq("DUP")
    assert admin.post("/api/products", json={"sku": sku, "name": "Dup One", "price_kobo": 100}).status_code == 201
    assert admin.post("/api/products", json={"sku": sku, "name": "Dup Two", "price_kobo": 100}).status_code == 409
    assert world["sales_a"].post("/api/products", json={"sku": uniq("Z"), "name": "Nope", "price_kobo": 5}).status_code == 403


def test_order_calculation_is_server_side(app, admin, world):
    cust = Api(app)
    # tampered client total/price fields are ignored by the schema; totals come from DB prices
    p = order_payload(world, qty=3, otype="delivery", method="cash_on_delivery", total_kobo=1, price_kobo=1)
    r = cust.post("/api/public/orders", json=p)
    assert r.status_code == 201, r.text
    t = cust.get("/api/public/track", params={"number": r.json()["order_number"], "phone": "08031234567"}).json()
    assert t["subtotal_kobo"] == 3 * 180000
    assert t["total_kobo"] == t["subtotal_kobo"] + t["delivery_fee_kobo"]
    assert t["delivery_fee_kobo"] == 100000  # default configured fee
    assert "stock_deducted" not in t and "history" not in t  # no internal fields for customers
    assert cust.post("/api/public/orders", json=order_payload(world, method="cash_on_delivery")).status_code == 400  # COD needs delivery
    assert cust.post("/api/public/orders", json={**p, "items": [{"product_id": world["flour"], "quantity": 1}]}).status_code == 400  # raw material not sellable
    assert cust.post("/api/public/orders", json={**p, "items": []}).status_code == 400


def test_guest_tracking_requires_matching_phone(app, world):
    c = Api(app)
    r = c.post("/api/public/orders", json=order_payload(world))
    num = r.json()["order_number"]
    assert c.get("/api/public/track", params={"number": num, "phone": "09000000000"}).status_code == 404
    assert c.get("/api/public/track", params={"number": num, "phone": "08031234567"}).status_code == 200
    assert c.get("/api/public/track", params={"number": num, "token": r.json()["tracking_token"]}).status_code == 200


def test_bank_transfer_never_auto_paid(app, admin, world):
    c = Api(app)
    r = c.post("/api/public/orders", json=order_payload(world, qty=1, method="bank_transfer")).json()
    num, tok = r["order_number"], r["tracking_token"]
    assert r["status"] == "awaiting_payment"
    pr = c.post(f"/api/public/orders/{num}/payment-proof", params={"token": tok}, json={"transfer_reference": "TRF123456"})
    assert pr.status_code == 200 and pr.json()["payment_status"] == "awaiting_verification"
    t = c.get("/api/public/track", params={"number": num, "token": tok}).json()
    assert t["payment_status"] == "pending_verification" and t["paid_kobo"] == 0  # screenshot/reference alone is NOT payment
    # sales officer cannot verify; accountant can
    pays = world["acct"].get("/api/payments", params={"q": num}).json()["items"]
    pid = pays[0]["id"]
    assert world["sales_a"].post(f"/api/payments/{pid}/verify", json={"approve": True}).status_code == 403
    v = world["acct"].post(f"/api/payments/{pid}/verify", json={"approve": True, "note": "seen in bank"})
    assert v.status_code == 200 and v.json()["status"] == "verified"
    t = c.get("/api/public/track", params={"number": num, "token": tok}).json()
    assert t["payment_status"] == "paid" and t["status"] == "paid"
    assert world["acct"].post(f"/api/payments/{pid}/verify", json={"approve": True}).status_code == 409  # cannot verify twice
    led = world["acct"].get("/api/finance/transactions", params={"kind": "revenue"}).json()["items"]
    assert any(x["order_id"] and x["amount_kobo"] == 180000 for x in led)


def test_order_lifecycle_and_stock_movements(app, admin, world):
    A = world["AAA"]
    admin.post("/api/inventory/movements", json={"product_id": world["bread"], "branch_id": A, "movement_type": "addition", "quantity": 50, "reason": "bake output"})
    before = stock(admin, world, world["bread"], A)
    c = Api(app)
    num = c.post("/api/public/orders", json=order_payload(world, qty=4)).json()["order_number"]
    sales = world["sales_a"]
    oid = sales.get("/api/orders", params={"q": num}).json()["items"][0]["id"]
    assert sales.post(f"/api/orders/{oid}/status", json={"status": "completed"}).status_code == 409  # illegal jump
    assert sales.post(f"/api/orders/{oid}/status", json={"status": "confirmed"}).status_code == 200
    r = sales.post(f"/api/orders/{oid}/status", json={"status": "ready_for_dispatch"})
    assert r.status_code == 400  # pickup order
    assert sales.post(f"/api/orders/{oid}/status", json={"status": "ready_for_collection"}).status_code == 200
    assert stock(admin, world, world["bread"], A) == before - 4
    mv = admin.get("/api/inventory/movements", params={"product_id": world["bread"], "branch_id": A}).json()["items"]
    assert mv[0]["type"] == "sale_out" and mv[0]["quantity"] == -4 and num in mv[0]["reference"] and mv[0]["by"]
    assert sales.post(f"/api/orders/{oid}/status", json={"status": "cancelled", "note": ""}).status_code in (400, 403)
    assert sales.post(f"/api/orders/{oid}/status", json={"status": "completed"}).status_code == 200
    hist = sales.get(f"/api/orders/{oid}").json()["history"]
    assert [h["to"] for h in hist][-3:] == ["confirmed", "ready_for_collection", "completed"] and all(h["by"] for h in hist)


def test_cancel_requires_reason_and_restores_stock(app, admin, world):
    A = world["AAA"]
    admin.post("/api/inventory/movements", json={"product_id": world["bread"], "branch_id": A, "movement_type": "addition", "quantity": 20, "reason": "stock for cancel test"})
    c = Api(app)
    num = c.post("/api/public/orders", json=order_payload(world, qty=2)).json()["order_number"]
    oid = admin.get("/api/orders", params={"q": num}).json()["items"][0]["id"]
    admin.post(f"/api/orders/{oid}/status", json={"status": "confirmed"})
    admin.post(f"/api/orders/{oid}/status", json={"status": "ready_for_collection"})
    s1 = stock(admin, world, world["bread"], A)
    assert admin.post(f"/api/orders/{oid}/status", json={"status": "cancelled"}).status_code == 400
    # ready_for_collection -> cancelled is allowed with a reason, stock returns
    assert admin.post(f"/api/orders/{oid}/status", json={"status": "cancelled", "note": "customer changed mind"}).status_code == 200
    assert stock(admin, world, world["bread"], A) == s1 + 2


def test_insufficient_stock_blocks_and_never_goes_negative(app, admin, world):
    A = world["AAA"]
    c = Api(app)
    num = c.post("/api/public/orders", json=order_payload(world, qty=99999 - 1)).json()["order_number"]
    oid = admin.get("/api/orders", params={"q": num}).json()["items"][0]["id"]
    admin.post(f"/api/orders/{oid}/status", json={"status": "confirmed"})
    r = admin.post(f"/api/orders/{oid}/status", json={"status": "ready_for_collection"})
    assert r.status_code == 400 and "Insufficient stock" in r.json()["detail"]
    assert admin.post("/api/inventory/movements", json={"product_id": world["bread"], "branch_id": A, "movement_type": "deduction", "quantity": 10 ** 6, "reason": "too much"}).status_code == 400
    assert stock(admin, world, world["bread"], A) >= 0


def test_stock_adjustments_need_reason_type_and_branch(admin, world):
    A, B = world["AAA"], world["BBB"]
    inv = world["inv_a"]
    assert inv.post("/api/inventory/movements", json={"product_id": world["flour"], "branch_id": A, "movement_type": "damaged", "quantity": 2, "reason": "torn sack"}).status_code == 201
    assert inv.post("/api/inventory/movements", json={"product_id": world["flour"], "branch_id": A, "movement_type": "bogus", "quantity": 2, "reason": "torn sack"}).status_code == 400
    assert inv.post("/api/inventory/movements", json={"product_id": world["flour"], "branch_id": A, "movement_type": "wastage", "quantity": 1, "reason": "x"}).status_code == 422
    # branch isolation: manager of A cannot touch B's stock
    assert inv.post("/api/inventory/movements", json={"product_id": world["flour"], "branch_id": B, "movement_type": "addition", "quantity": 5, "reason": "sneaky add"}).status_code == 403
    assert inv.get("/api/inventory/stock", params={"branch_id": B}).status_code == 403


def test_branch_data_isolation_for_orders(app, admin, world):
    c = Api(app)
    num = c.post("/api/public/orders", json=order_payload(world)).json()["order_number"]
    oid = admin.get("/api/orders", params={"q": num}).json()["items"][0]["id"]
    other = world["branch_mgr_b"]
    assert other.get(f"/api/orders/{oid}").status_code == 404
    assert num not in [o["order_number"] for o in other.get("/api/orders").json()["items"]]
    assert other.post(f"/api/orders/{oid}/status", json={"status": "confirmed"}).status_code == 404
    assert other.get("/api/orders", params={"branch_id": world["AAA"]}).status_code == 403
    assert world["branch_mgr_a"].get(f"/api/orders/{oid}").status_code == 200


def test_stock_transfer_between_branches(admin, world):
    A, B = world["AAA"], world["BBB"]
    b0 = stock(admin, world, world["flour"], A)
    r = admin.post("/api/inventory/transfers", json={"product_id": world["flour"], "from_branch_id": A, "to_branch_id": B, "quantity": 20})
    assert r.status_code == 201
    assert stock(admin, world, world["flour"], A) == b0 - 20 and stock(admin, world, world["flour"], B) == 20
    assert admin.post("/api/inventory/transfers", json={"product_id": world["flour"], "from_branch_id": A, "to_branch_id": A, "quantity": 1}).status_code == 400
    assert world["inv_a"].post("/api/inventory/transfers", json={"product_id": world["flour"], "from_branch_id": A, "to_branch_id": B, "quantity": 1}).status_code == 403


def test_production_batch_consumes_materials_and_adds_stock(admin, world):
    A = world["AAA"]
    prod = world["prod_a"]
    f0, y0, b0 = (stock(admin, world, world[k], A) for k in ("flour", "yeast", "bread"))
    r = prod.post("/api/production/plans", json={"branch_id": A, "plan_date": datetime.now().date().isoformat(), "batches": [{"product_id": world["bread"], "planned_qty": 100}]})
    assert r.status_code == 201, r.text
    bid = prod.get("/api/production/batches", params={"status": "planned"}).json()["items"][0]["id"]
    b = prod.get(f"/api/production/batches/{bid}").json()
    flour = next(c for c in b["consumption"] if c["name"] == "Test Flour")
    assert flour["expected_qty"] == 50  # 5kg per 10 loaves * 100
    assert len(b["stages"]) == 9
    assert prod.post(f"/api/production/batches/{bid}/start").status_code == 200
    assert prod.post(f"/api/production/batches/{bid}/advance", json={}).status_code == 200
    r = prod.post(f"/api/production/batches/{bid}/complete", json={"actual_qty": 96, "rejected_qty": 6, "wastage_qty": 2, "actual_consumption": {str(world["flour"]): 52}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "completed" and d["efficiency"] == 96.0 and d["total_cost_kobo"] > 0
    assert stock(admin, world, world["flour"], A) == f0 - 52
    assert stock(admin, world, world["yeast"], A) == y0 - 1
    assert stock(admin, world, world["bread"], A) == b0 + 90  # good units = produced - rejected
    assert prod.post(f"/api/production/batches/{bid}/complete", json={"actual_qty": 1}).status_code == 409
    s = prod.get("/api/production/summary").json()
    assert s["actual"] >= 96 and s["rejected"] >= 6


def test_batch_cannot_start_without_ingredients(admin, world):
    prod = world["prod_a"]
    r = prod.post("/api/production/plans", json={"branch_id": world["AAA"], "plan_date": datetime.now().date().isoformat(), "batches": [{"product_id": world["bread"], "planned_qty": 10 ** 7}]})
    bid = prod.get("/api/production/batches", params={"status": "planned"}).json()["items"][0]["id"]
    r = prod.post(f"/api/production/batches/{bid}/start")
    assert r.status_code == 400 and "Insufficient raw materials" in r.json()["detail"]
    assert prod.post(f"/api/production/batches/{bid}/cancel").status_code == 200


def test_production_branch_restriction(world):
    r = world["prod_a"].post("/api/production/plans", json={"branch_id": world["BBB"], "plan_date": "2026-11-20", "batches": [{"product_id": world["bread"], "planned_qty": 1}]})
    assert r.status_code == 403


def test_expense_recording_and_approval(admin, world):
    cats = world["branch_mgr_a"].get("/api/expense-categories").json()
    fuel = next(c["id"] for c in cats if c["name"] == "Fuel")
    bm = world["branch_mgr_a"]
    r = bm.post("/api/expenses", json={"category_id": fuel, "description": "Diesel for van", "amount_kobo": 1500000, "branch_id": world["AAA"]})
    assert r.status_code == 201 and r.json()["status"] == "approved"  # below threshold (₦50,000)
    big = bm.post("/api/expenses", json={"category_id": fuel, "description": "Generator overhaul", "amount_kobo": 9000000, "branch_id": world["AAA"]})
    assert big.status_code == 201 and big.json()["status"] == "pending_approval"
    eid = big.json()["id"]
    led_before = admin.get("/api/finance/transactions", params={"kind": "expense"}).json()["total"]
    assert bm.post(f"/api/expenses/{eid}/decide", json={"approve": True}).status_code == 403
    assert world["acct"].post(f"/api/expenses/{eid}/decide", json={"approve": True, "note": "ok"}).status_code == 200
    assert admin.get("/api/finance/transactions", params={"kind": "expense"}).json()["total"] == led_before + 1
    assert bm.post("/api/expenses", json={"category_id": fuel, "description": "wrong branch", "amount_kobo": 100, "branch_id": world["BBB"]}).status_code == 403
    assert bm.post("/api/expenses", json={"category_id": fuel, "description": "neg", "amount_kobo": -5, "branch_id": world["AAA"]}).status_code == 422
    assert world["sales_a"].post("/api/expenses", json={"category_id": fuel, "description": "nope nope", "amount_kobo": 5, "branch_id": world["AAA"]}).status_code == 403


def test_money_is_integer_kobo(admin, world):
    s = admin.get("/api/dashboard").json()["stats"]
    assert all(isinstance(v, int) for k, v in s.items() if k.endswith("_kobo"))
    d = admin.get("/api/finance/summary").json()["pnl"]
    assert all(isinstance(v, int) for k, v in d.items() if k.endswith("_kobo"))


def _ready_delivery_order(app, admin, world, qty=2):
    admin.post("/api/inventory/movements", json={"product_id": world["bread"], "branch_id": world["AAA"], "movement_type": "addition", "quantity": 100, "reason": "dispatch test stock"})
    c = Api(app)
    num = c.post("/api/public/orders", json=order_payload(world, qty=qty, otype="delivery", method="cash_on_delivery")).json()["order_number"]
    oid = admin.get("/api/orders", params={"q": num}).json()["items"][0]["id"]
    assert admin.post(f"/api/orders/{oid}/status", json={"status": "confirmed"}).status_code == 200
    assert admin.post(f"/api/orders/{oid}/status", json={"status": "ready_for_dispatch"}).status_code == 200
    return oid, num


def _driver_id(admin, world, key):
    uid = world[key].id
    return next(d["id"] for d in admin.get("/api/drivers").json() if d["user_id"] == uid)


def test_delivery_assignment_conflicts_and_completion(app, admin, world):
    disp = world["dispatch_a"]
    oid, num = _ready_delivery_order(app, admin, world)
    oid2, num2 = _ready_delivery_order(app, admin, world)
    d1, d2 = _driver_id(admin, world, "driver1"), _driver_id(admin, world, "driver2")
    dep = datetime.now(timezone.utc) + timedelta(days=1)
    body = {"branch_id": world["AAA"], "driver_id": d1, "vehicle_id": world["vehicle"], "scheduled_departure": dep.isoformat(), "expected_return": (dep + timedelta(hours=3)).isoformat(), "order_ids": [oid]}
    r = disp.post("/api/dispatch/runs", json=body)
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["assignments"][0]["order_number"] == num
    # same driver, overlapping window -> conflict; same vehicle with other driver -> conflict
    assert disp.post("/api/dispatch/runs", json={**body, "order_ids": [oid2]}).status_code == 409
    assert disp.post("/api/dispatch/runs", json={**body, "driver_id": d2, "order_ids": [oid2]}).status_code == 409
    # capacity: vehicle2 holds 5 units, order has 2 -> ok on capacity; overload by checking small vehicle with qty above capacity
    big_oid, _ = _ready_delivery_order(app, admin, world, qty=9)
    assert disp.post("/api/dispatch/runs", json={**body, "driver_id": d2, "vehicle_id": world["vehicle2"], "order_ids": [big_oid]}).status_code == 400
    # an order already assigned cannot be re-assigned
    assert disp.post("/api/dispatch/runs", json={**body, "driver_id": d2, "vehicle_id": world["vehicle2"], "scheduled_departure": (dep + timedelta(days=2)).isoformat(),
                     "expected_return": (dep + timedelta(days=2, hours=2)).isoformat(), "order_ids": [oid]}).status_code == 409
    assert admin.get(f"/api/orders/{oid}").json()["status"] == "assigned_to_driver"
    # driver sees only own deliveries
    mine = world["driver1"].get("/api/driver/deliveries", params={"scope": "all"}).json()
    assert [i["order_number"] for i in mine["items"]] == [num]
    assert world["driver2"].get("/api/driver/deliveries", params={"scope": "all"}).json()["items"] == []
    aid = mine["items"][0]["id"]
    assert world["driver2"].post(f"/api/driver/deliveries/{aid}/start").status_code == 404  # not their assignment
    assert world["driver1"].post(f"/api/driver/deliveries/{aid}/complete", json={}).status_code == 409  # must start first
    assert world["driver1"].post(f"/api/driver/deliveries/{aid}/start").status_code == 200
    assert admin.get(f"/api/orders/{oid}").json()["status"] == "out_for_delivery"
    r = world["driver1"].post(f"/api/driver/deliveries/{aid}/complete", json={"received_by_name": "Ada", "latitude": 4.92, "longitude": 6.26, "cash_collected_kobo": 460000})
    assert r.status_code == 200, r.text
    o = admin.get(f"/api/orders/{oid}").json()
    assert o["status"] == "delivered"  # cash not yet verified -> not auto-completed
    assert o["payment_status"] == "pending_verification" and o["paid_kobo"] == 0  # driver cash needs finance verification
    pid = next(p["id"] for p in o["payments"] if p["status"] == "awaiting_verification")
    assert world["acct"].post(f"/api/payments/{pid}/verify", json={"approve": True}).status_code == 200
    o = admin.get(f"/api/orders/{oid}").json()
    assert o["payment_status"] == "paid"
    run_after = disp.get("/api/dispatch/runs", params={"status": "completed"}).json()
    assert any(r["run_number"] == run["run_number"] for r in run_after)


def test_failed_delivery_returns_order_to_pool(app, admin, world):
    disp = world["dispatch_a"]
    oid, num = _ready_delivery_order(app, admin, world)
    dep = datetime.now(timezone.utc) + timedelta(days=10)
    run = disp.post("/api/dispatch/runs", json={"branch_id": world["AAA"], "driver_id": _driver_id(admin, world, "driver2"), "vehicle_id": world["vehicle"],
                    "scheduled_departure": dep.isoformat(), "expected_return": (dep + timedelta(hours=2)).isoformat(), "order_ids": [oid]}).json()
    aid = run["assignments"][0]["id"]
    d = world["driver2"]
    d.post(f"/api/driver/deliveries/{aid}/start")
    assert d.post(f"/api/driver/deliveries/{aid}/fail", json={"reason": "x"}).status_code == 422
    assert d.post(f"/api/driver/deliveries/{aid}/fail", json={"reason": "Customer unreachable"}).status_code == 200
    assert admin.get(f"/api/orders/{oid}").json()["status"] == "ready_for_dispatch"
    assert any(f["order_number"] == num for f in disp.get("/api/dispatch/failed").json())


def test_customer_cannot_access_internal_endpoints(app, world):
    c = Api(app)
    email = f"cust.{uniq()}@bonjour-test.com"
    r = c.post("/api/auth/register", json={"name": "Chi Customer", "email": email, "phone": "08077776666", "password": "Customer2026"})
    assert r.status_code == 201
    c.c.headers["x-csrf-token"] = r.json()["csrf_token"]
    for path in ("/api/orders", "/api/staff", "/api/dashboard", "/api/finance/summary", "/api/customers", "/api/inventory/stock", "/api/audit-logs", "/api/settings", "/api/driver/deliveries"):
        assert c.get(path).status_code in (401, 403), path
    assert c.post("/api/orders", json={}).status_code in (401, 403)
    # but can order, see history and reorder
    num = c.post("/api/public/orders", json=order_payload(world)).json()["order_number"]
    mine = c.get("/api/me/orders").json()
    assert mine[0]["order_number"] == num
    ro = c.post(f"/api/me/orders/{num}/reorder").json()
    assert ro["items"][0]["quantity"] == 2
    # another customer cannot see it
    d = Api(app)
    r2 = d.post("/api/auth/register", json={"name": "Other One", "email": f"o.{uniq()}@bonjour-test.com", "phone": "08011112222", "password": "Customer2026"})
    d.c.headers["x-csrf-token"] = r2.json()["csrf_token"]
    assert d.get("/api/me/orders").json() == []
    assert d.post(f"/api/me/orders/{num}/reorder").status_code == 404


def test_walk_in_sale_and_receipt_pdf(admin, world):
    admin.post("/api/inventory/movements", json={"product_id": world["bread"], "branch_id": world["AAA"], "movement_type": "addition", "quantity": 30, "reason": "walkin stock"})
    sales = world["sales_a"]
    b0 = stock(admin, world, world["bread"], world["AAA"])
    r = sales.post("/api/orders", json={"branch_id": world["AAA"], "order_type": "pickup", "channel": "walk_in", "contact_name": "Walk In", "payment_method": "cash",
                                         "items": [{"product_id": world["bread"], "quantity": 3}]})
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["status"] == "completed" and o["total_kobo"] == 540000
    assert stock(admin, world, world["bread"], world["AAA"]) == b0 - 3
    pdf = sales.get(f"/api/orders/{o['id']}/document.pdf", params={"kind": "receipt"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_reports_filter_and_export(admin, world):
    r = admin.get("/api/reports/sales_daily").json()
    assert r["columns"][0] == "Period" and len(r["rows"]) >= 1
    assert admin.get("/api/reports/sales_daily", params={"format": "csv"}).text.count("\n") >= 3
    assert admin.get("/api/reports/stock", params={"format": "pdf"}).content.startswith(b"%PDF")
    assert admin.get("/api/reports/profit_loss").status_code == 200
    assert world["sales_a"].get("/api/reports/sales_daily").status_code == 403
    assert world["inv_a"].get("/api/reports/profit_loss").status_code == 403  # inventory manager: no finance access
    assert world["inv_a"].get("/api/reports/stock").status_code == 200


def test_audit_log_records_actions(admin, world):
    for a in ("login", "staff_created", "product_created", "order_status", "expense_recorded", "stock_damaged"):
        r = admin.get("/api/audit-logs", params={"action": a}).json()
        assert r["total"] >= 1 and r["items"][0]["user"], a
    assert world["sales_a"].get("/api/audit-logs").status_code == 403


def test_settings_change_without_code(admin, world):
    assert admin.put("/api/settings", json={"values": {"delivery_fee_kobo": 250000}}).status_code == 200
    assert admin.put("/api/settings", json={"values": {"nonsense": 1}}).status_code == 400
    assert admin.put("/api/settings", json={"values": {"timezone": "Mars/Base"}}).status_code == 400
    assert world["sales_a"].put("/api/settings", json={"values": {"delivery_fee_kobo": 1}}).status_code == 403
    cfg = admin.get("/api/public/config").json()
    assert cfg["delivery_fee_kobo"] == 250000
    admin.put("/api/settings", json={"values": {"delivery_fee_kobo": 100000}})


def test_paystack_not_configured_is_honest(app, world):
    c = Api(app)
    r = c.post("/api/public/orders", json=order_payload(world, method="paystack"))
    assert r.status_code == 400 and "not configured" in r.json()["detail"].lower()
    assert c.post("/api/webhooks/paystack", content=b"{}", headers={"x-paystack-signature": "bad"}).status_code == 401
