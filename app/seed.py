"""Demo data. Everything created here is flagged is_demo=True and only visible while Settings > data_mode = 'demo'.

    python -m app.seed demo [--password 'Demo2026pass']     create demo data and switch to demo mode
    python -m app.seed purge                                delete ALL demo records and switch back to live mode
"""
import random
import secrets
import sys
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
from sqlalchemy import text
from app.database import SessionLocal, Base, engine
from app import bootstrap
from app.models import *  # noqa
from app.security import hash_password
from app.services import settings_service, numbering, production as prodsvc
from app.utils import common

R = random.Random(2026)
DEMO_MAIL = "bonjour-demo.com"


def ago(days, hour=None):
    d = datetime.now(timezone.utc) - timedelta(days=days)
    return d.replace(hour=hour if hour is not None else R.randint(7, 18), minute=R.randint(0, 59), second=0, microsecond=0)


def purge(db):
    demo_users = [u.id for u in db.query(User).filter(User.is_demo == True)]  # noqa
    with db.begin_nested():
        order_ids = [o.id for o in db.query(Order).filter(Order.is_demo == True)]  # noqa
        db.execute(text("DELETE FROM delivery_runs WHERE is_demo"))
        db.execute(text("DELETE FROM cash_register_closes WHERE is_demo"))
        db.execute(text("DELETE FROM financial_transactions WHERE is_demo"))
        db.execute(text("DELETE FROM payment_verifications WHERE payment_id IN (SELECT id FROM payments WHERE is_demo)"))
        db.execute(text("DELETE FROM payments WHERE is_demo"))
        db.execute(text("DELETE FROM production_batches WHERE is_demo"))
        db.execute(text("DELETE FROM production_plans WHERE is_demo"))
        db.execute(text("DELETE FROM orders WHERE is_demo"))
        db.execute(text("DELETE FROM expenses WHERE is_demo"))
        db.execute(text("DELETE FROM supplier_payments WHERE is_demo"))
        db.execute(text("DELETE FROM supplier_invoices WHERE is_demo"))
        db.execute(text("DELETE FROM goods_receipt_items WHERE receipt_id IN (SELECT id FROM goods_receipts WHERE po_id IN (SELECT id FROM purchase_orders WHERE is_demo))"))
        db.execute(text("DELETE FROM goods_receipts WHERE po_id IN (SELECT id FROM purchase_orders WHERE is_demo)"))
        db.execute(text("DELETE FROM purchase_orders WHERE is_demo"))
        db.execute(text("DELETE FROM purchase_requests WHERE is_demo"))
        db.execute(text("DELETE FROM stock_transfers WHERE product_id IN (SELECT id FROM products WHERE is_demo)"))
        db.execute(text("DELETE FROM stock_movements WHERE is_demo OR product_id IN (SELECT id FROM products WHERE is_demo)"))
        db.execute(text("DELETE FROM recipes WHERE product_id IN (SELECT id FROM products WHERE is_demo)"))
        db.execute(text("DELETE FROM inventory_balances WHERE product_id IN (SELECT id FROM products WHERE is_demo)"))
        db.execute(text("DELETE FROM products WHERE is_demo"))
        db.execute(text("DELETE FROM suppliers WHERE is_demo"))
        db.execute(text("DELETE FROM customers WHERE is_demo"))
        db.execute(text("DELETE FROM drivers WHERE is_demo"))
        db.execute(text("DELETE FROM vehicles WHERE is_demo"))
        if demo_users:
            db.execute(text("DELETE FROM tasks WHERE assigned_to = ANY(:u) OR created_by = ANY(:u)"), {"u": demo_users})
            db.execute(text("DELETE FROM notifications WHERE user_id = ANY(:u)"), {"u": demo_users})
        db.execute(text("UPDATE branches SET manager_id = NULL WHERE is_demo"))
        db.execute(text("DELETE FROM users WHERE is_demo"))
        db.execute(text("DELETE FROM branches WHERE is_demo"))
    settings_service.set_value(db, "data_mode", "live")
    db.commit()
    print("Demo data removed. Data mode: live.")


def seed(db, password):
    if db.query(Branch).filter(Branch.is_demo == True).count():  # noqa
        raise SystemExit("Demo data already exists. Run 'python -m app.seed purge' first.")
    bootstrap.init(db)
    roles = {r.key: r for r in db.query(Role)}
    cats = {c.name: c for c in db.query(ProductCategory)}
    ecats = {c.name: c for c in db.query(ExpenseCategory)}
    stages = db.query(ProductionStage).order_by(ProductionStage.sequence).all()

    # --- branches
    brs = []
    for code, name, lga, addr in (("YNG", "Yenagoa Main Bakery", "Yenagoa", "Mbiama-Yenagoa Rd, Yenagoa"), ("AMR", "Amarata Outlet", "Yenagoa", "Amarata, Yenagoa"),
                                  ("KPS", "Kpansia Outlet", "Yenagoa", "Kpansia, Yenagoa"), ("PHC", "Port Harcourt Depot", "Port Harcourt", "Trans-Amadi, Port Harcourt")):
        b = Branch(code="D-" + code, name=name, lga=lga, address=addr, state="Rivers" if code == "PHC" else "Bayelsa", phone="0803000" + str(R.randint(1000, 9999)),
                   opened_on=date(2024, 1, 15), is_demo=True)
        db.add(b)
        brs.append(b)
    db.flush()
    main, amr, kps, phc = brs

    # --- staff
    pw = hash_password(password)
    staff = {}
    plan = [("general_manager", "Ngozi Eze", None), ("branch_manager", "Tamuno Briggs", main), ("production_manager", "Emeka Okoro", main), ("inventory_manager", "Fatima Bello", main),
            ("sales_officer", "Blessing Ebi", main), ("dispatch_manager", "Preye Dickson", main), ("accountant", "Chinedu Ibe", None), ("customer_service", "Ebiere Alagoa", main),
            ("general_staff", "Soala Peterside", main), ("driver", "Daniel Ogoli", main), ("driver", "Isaac Timi", main), ("branch_manager", "Mercy Nwosu", amr),
            ("sales_officer", "Gift Amos", amr), ("sales_officer", "Kemi Alabi", kps)]
    for i, (role, name, br) in enumerate(plan, 1):
        email = f"demo.{role}{'' if role not in ('driver', 'branch_manager', 'sales_officer') else i}@{DEMO_MAIL}"
        u = User(email=email, full_name=name, phone=f"0805{R.randint(1000000, 9999999)}", password_hash=pw, role_id=roles[role].id, branch_id=br.id if br else None,
                 employee_id=f"DEMO-{i:03d}", department={"production_manager": "Production", "inventory_manager": "Inventory", "driver": "Logistics", "dispatch_manager": "Logistics",
                                                          "accountant": "Finance", "sales_officer": "Sales", "branch_manager": "Management"}.get(role, "Operations"),
                 job_title=roles[role].name, is_demo=True)
        db.add(u)
        staff.setdefault(role, []).append(u)
    db.flush()
    main.manager_id, amr.manager_id = staff["branch_manager"][0].id, staff["branch_manager"][1].id
    drivers = []
    for u in staff["driver"]:
        d = Driver(user_id=u.id, license_no=f"BYS-{R.randint(100000, 999999)}", phone=u.phone, branch_id=main.id, is_demo=True)
        db.add(d)
        drivers.append(d)
    vehicles = [Vehicle(plate_number=p, vehicle_type=t, capacity_units=c, branch_id=main.id, is_demo=True) for p, t, c in (("DEMO-BYS-101", "Delivery van", 600), ("DEMO-BYS-202", "Mini bus", 300), ("DEMO-BYS-303", "Tricycle", 120))]
    db.add_all(vehicles)
    db.flush()

    # --- products
    def mk(kind, sku, name, price=0, cost=0, unit="pcs", reorder=0, cat="Bread", size="", desc="", wholesale=0):
        p = Product(sku="D-" + sku, name=name, kind=kind, category_id=cats[cat].id, price_kobo=price, cost_kobo=cost, unit=unit, reorder_level=reorder, size_label=size,
                    description=desc, wholesale_price_kobo=wholesale, is_sellable=kind == "finished", is_demo=True)
        db.add(p)
        return p
    breads = [mk("finished", "BRD-FAM", "Family Bread", 180000, reorder=40, size="Family", desc="Soft, golden family loaf baked fresh every morning.", wholesale=160000),
              mk("finished", "BRD-SND", "Large Sandwich Bread", 130000, reorder=40, size="Large", desc="Perfectly sliced for sandwiches.", wholesale=115000),
              mk("finished", "BRD-MIN", "Mini Loaf", 80000, reorder=60, size="Mini", desc="Handy little loaf for one or two.", wholesale=70000),
              mk("finished", "BRD-COC", "Coconut Bread", 200000, reorder=20, cat="Special Bread", size="Medium", desc="Sweet coconut-flavoured loaf.", wholesale=180000),
              mk("finished", "BRD-BTR", "Butter Bread", 220000, reorder=20, cat="Special Bread", size="Medium", desc="Rich, buttery and tender.", wholesale=200000),
              mk("finished", "BRD-JMB", "Jumbo Sliced Bread", 280000, reorder=20, size="Jumbo", desc="Extra-large loaf for big households.", wholesale=250000)]
    raws = {n: mk("raw", s, n, cost=c, unit=u, reorder=r, cat="Raw Materials") for n, s, c, u, r in (("Flour", "FLR", 120000, "kg", 300), ("Sugar", "SGR", 150000, "kg", 60),
            ("Yeast", "YST", 450000, "kg", 8), ("Salt", "SLT", 40000, "kg", 20), ("Margarine", "MRG", 350000, "kg", 25), ("Milk Powder", "MLK", 700000, "kg", 10), ("Desiccated Coconut", "COC", 600000, "kg", 8))}
    nylon = mk("packaging", "NYL", "Bread Nylon", cost=1500, unit="pcs", reorder=800, cat="Packaging")
    label = mk("packaging", "LBL", "Bread Label", cost=500, unit="pcs", reorder=800, cat="Packaging")
    db.flush()
    flour, sugar, yeast, salt, marg, milk, coco = list(raws.values())

    def recipe(p, yield_, ing, instr):
        r = Recipe(product_id=p.id, name=p.name + " standard recipe", yield_qty=yield_, instructions=instr)
        r.ingredients = [RecipeIngredient(material_id=m.id, quantity=q) for m, q in ing]
        db.add(r)
        db.flush()
        db.refresh(r)
        p.cost_kobo = int(round(prodsvc.recipe_unit_cost(r) * 1.15))
        return r
    base = "Mix dry ingredients, add water and fats, knead 12 min, proof 45 min, shape, proof 40 min, bake at 200C for 30 min, cool and pack."
    rec = {b.sku: recipe(b, 100, [(flour, 40), (sugar, 2), (yeast, 0.6), (salt, 0.8), (marg, 2), (nylon, 100), (label, 100)], base) for b in breads[:3]}
    rec[breads[3].sku] = recipe(breads[3], 100, [(flour, 42), (sugar, 4), (yeast, 0.6), (salt, 0.8), (marg, 3), (coco, 3), (nylon, 100), (label, 100)], base + " Fold in coconut.")
    rec[breads[4].sku] = recipe(breads[4], 100, [(flour, 42), (sugar, 3), (yeast, 0.6), (salt, 0.8), (marg, 6), (milk, 1.5), (nylon, 100), (label, 100)], base)
    rec[breads[5].sku] = recipe(breads[5], 100, [(flour, 55), (sugar, 3), (yeast, 0.8), (salt, 1), (marg, 3), (nylon, 100), (label, 100)], base)

    # --- stock (chronological ledger starting 35 days ago)
    bal = {}

    def mv(prod, br, qty, typ, when, reason, ref_type="", ref=""):
        k = (prod.id, br.id)
        new = bal.get(k, Decimal(0)) + Decimal(str(qty))
        assert new >= 0, (prod.name, br.name)
        bal[k] = new
        db.add(StockMovement(product_id=prod.id, branch_id=br.id, movement_type=typ, quantity=Decimal(str(qty)), balance_after=bal[k], reason=reason,
                             reference_type=ref_type, reference_id=ref, user_id=staff["inventory_manager"][0].id, created_at=when, is_demo=True))
    work_branches = [main, amr, kps]
    for b in work_branches:
        for m in list(raws.values()) + [nylon, label]:
            base_qty = {"Flour": 4000, "Sugar": 400, "Yeast": 60, "Salt": 120, "Margarine": 300, "Milk Powder": 60, "Desiccated Coconut": 60, "Bread Nylon": 60000, "Bread Label": 60000}[m.name]
            q = base_qty if b is main else max(int(base_qty * 0.3), 1)
            if m.name == "Yeast" and b is amr:
                q = 9  # near its reorder level so the demo shows a live low-stock alert
            mv(m, b, q, "opening", ago(35, 8), "Opening stock")
        for p in breads:
            mv(p, b, 200 if b is main else 500, "opening", ago(35, 8), "Opening stock")

    # --- production batches (completed over last 14 days at main)
    ops = staff["production_manager"][0]
    sku_i = 0
    for day in range(14, 0, -1):
        for p in R.sample(breads, 3):
            planned = R.choice([100, 150, 200, 250])
            actual = int(planned * R.uniform(0.93, 1.0))
            rej, was = R.randint(0, 4), R.randint(0, 3)
            r = rec[p.sku]
            n = numbering.number(db, "batch", "DBAT")
            b = ProductionBatch(batch_number=n, branch_id=main.id, product_id=p.id, recipe_id=r.id, planned_qty=planned, actual_qty=actual, rejected_qty=rej, wastage_qty=was,
                                status="completed", supervisor_id=ops.id, scheduled_start=ago(day, 4), started_at=ago(day, 4), completed_at=ago(day, 10), created_by=ops.id,
                                created_at=ago(day, 3), is_demo=True)
            cost = 0
            for ing in r.ingredients:
                used = (Decimal(ing.quantity) * Decimal(planned) / Decimal(r.yield_qty)).quantize(Decimal("0.001"))
                b.consumption.append(BatchConsumption(material_id=ing.material_id, expected_qty=used, actual_qty=used, cost_kobo=int(used * ing.material.cost_kobo)))
                cost += int(used * ing.material.cost_kobo)
                mv(ing.material, main, -used, "production_out", ago(day, 10), f"Batch {n}", "production", n)
            b.total_cost_kobo = int(cost * 1.15)
            b.stage_logs = [BatchStageLog(stage_id=s.id, status="done", started_at=ago(day, 4), completed_at=ago(day, 10)) for s in stages]
            db.add(b)
            mv(p, main, actual - rej, "production_in", ago(day, 10), f"Batch {n}", "production", n)
    for p in (breads[0], breads[3]):  # two live planned batches
        b = ProductionBatch(batch_number=numbering.number(db, "batch", "DBAT"), branch_id=main.id, product_id=p.id, recipe_id=rec[p.sku].id, planned_qty=200, status="planned",
                            supervisor_id=ops.id, scheduled_start=datetime.now(timezone.utc) + timedelta(hours=6), created_by=ops.id, is_demo=True)
        db.add(b)
        db.flush()
        prodsvc.init_batch(db, b)
    # waste events and transfers
    mv(breads[2], main, -6, "damaged", ago(5), "Dropped tray during cooling")
    mv(raws["Yeast"], amr, -2, "expired", ago(9), "Past use-by date")

    # --- suppliers, purchasing
    sups = [Supplier(name=n, contact_person=c, phone=ph, email=em, address=a, materials_supplied=m, is_demo=True) for n, c, ph, em, a, m in (
        ("Delta Flour Mills Ltd", "Mr Okonkwo", "08033445566", "sales@deltaflour.example.com", "Warri, Delta State", "Flour, Salt"),
        ("Sweet Sugar Traders", "Mrs Amaka", "08099887766", "orders@sweetsugar.example.com", "Yenagoa Market", "Sugar, Margarine, Milk powder"),
        ("PackRight Nigeria", "Mr Adeyemi", "08122334455", "hello@packright.example.com", "Port Harcourt", "Bread nylon, labels"))]
    db.add_all(sups)
    db.flush()
    po = PurchaseOrder(number=numbering.number(db, "po", "DPO"), supplier_id=sups[0].id, branch_id=main.id, status="received", created_by=staff["inventory_manager"][0].id,
                       approved_by=staff["general_manager"][0].id, created_at=ago(20), is_demo=True)
    po.items = [PurchaseOrderItem(product_id=flour.id, quantity=500, unit_cost_kobo=118000, received_qty=500)]
    po.total_kobo = 500 * 118000
    db.add(po)
    db.flush()
    mv(flour, main, 500, "purchase_in", ago(19), f"{po.number}", "purchase_order", po.number)
    inv1 = SupplierInvoice(supplier_id=sups[0].id, po_id=po.id, branch_id=main.id, invoice_number="DFM-2231", amount_kobo=po.total_kobo, paid_kobo=po.total_kobo // 2, status="part_paid",
                           due_date=date.today() + timedelta(days=10), is_demo=True, created_at=ago(19))
    inv2 = SupplierInvoice(supplier_id=sups[2].id, branch_id=main.id, invoice_number="PRN-884", amount_kobo=45000000, paid_kobo=0, due_date=date.today() + timedelta(days=5), is_demo=True)
    db.add_all([inv1, inv2])
    db.flush()
    pr = PurchaseRequest(number=numbering.number(db, "pr", "DPR"), branch_id=main.id, requested_by=staff["inventory_manager"][0].id, status="submitted", reason="Yeast and sugar running low", is_demo=True)
    pr.items = [PurchaseRequestItem(product_id=yeast.id, quantity=20, est_unit_cost_kobo=450000), PurchaseRequestItem(product_id=sugar.id, quantity=100, est_unit_cost_kobo=150000)]
    db.add(pr)

    # --- customers
    custs = [Customer(name=n, phone=ph, email=f"{n.split()[0].lower()}@{DEMO_MAIL}", customer_type=t, preferred_branch_id=main.id, is_demo=True) for n, ph, t in (
        ("Ada Obi", "08031110001", "retail"), ("Pastor Joseph Ere", "08031110002", "retail"), ("Mama Ngozi Provisions", "08031110003", "wholesale"), ("Glory Hotels Yenagoa", "08031110004", "business"),
        ("Bayelsa Schools Canteen", "08031110005", "bulk"), ("Tonye Harry", "08031110006", "retail"), ("Fresh Mart Supermarket", "08031110007", "wholesale"), ("Ebi Kingdom", "08031110008", "retail"),
        ("Hope Foundation", "08031110009", "bulk"), ("Alfred Seiyefa", "08031110010", "retail"))]
    db.add_all(custs)
    db.flush()
    for c in custs:
        db.add(CustomerAddress(customer_id=c.id, label="Main", address=f"{R.randint(1, 80)} {R.choice(['Okaka', 'Ovom', 'Etegwe', 'Epie', 'Opolo', 'Akenfa'])} Road, Yenagoa", lga="Yenagoa", is_default=True))
    db.flush()

    # --- orders (last 30 days)
    sales_users = staff["sales_officer"]
    ready_pool = []
    for i in range(70):
        day = R.randint(0, 29)
        br = R.choices(work_branches, weights=[6, 3, 2])[0]
        c = R.choice(custs)
        wholesale = c.customer_type in ("wholesale", "bulk", "business")
        channel = "wholesale" if wholesale else R.choice(["online", "online", "walk_in"])
        otype = "pickup" if channel == "walk_in" else R.choice(["delivery", "pickup"])
        lines = [(p, R.randint(20, 120) if wholesale else R.randint(1, 5)) for p in R.sample(breads, R.randint(1, 3))]
        sub = sum((p.wholesale_price_kobo if wholesale else p.price_kobo) * q for p, q in lines)
        fee = 100000 if otype == "delivery" else 0
        when = ago(day)
        # older orders are finished, recent ones in flight
        if day > 3:
            status = R.choices(["completed", "cancelled"], weights=[93, 7])[0]
        else:
            status = R.choice(["pending", "confirmed", "awaiting_payment", "paid", "in_production", "ready_for_dispatch" if otype == "delivery" else "ready_for_collection", "completed"])
        if channel == "walk_in":
            status = "completed" if status != "cancelled" else "completed"
        o = Order(order_number=f"DEMO-{when:%Y%m%d}-{i + 1:04d}", tracking_token=secrets.token_urlsafe(12), customer_id=c.id, branch_id=br.id, channel=channel, order_type=otype,
                  status=status, contact_name=c.name, contact_phone=c.phone, contact_email=c.email, delivery_address=c.addresses[0].address if otype == "delivery" else "",
                  delivery_lga="Yenagoa" if otype == "delivery" else "", preferred_date=(when + timedelta(days=1)).date(), preferred_time="10am - 1pm" if otype == "delivery" else "",
                  subtotal_kobo=sub, delivery_fee_kobo=fee, total_kobo=sub + fee, created_at=when, is_demo=True, created_by=sales_users[0].id)
        o.items = [OrderItem(product_id=p.id, name=p.name, unit_price_kobo=p.wholesale_price_kobo if wholesale else p.price_kobo, unit_cost_kobo=p.cost_kobo, quantity=q,
                             line_total_kobo=(p.wholesale_price_kobo if wholesale else p.price_kobo) * q) for p, q in lines]
        o.history = [OrderStatusHistory(from_status="", to_status="pending", user_label="Customer" if channel == "online" else sales_users[0].full_name, created_at=when)]
        if status != "pending":
            o.history.append(OrderStatusHistory(from_status="pending", to_status=status, user_label=sales_users[0].full_name, created_at=when + timedelta(hours=2)))
        db.add(o)
        db.flush()
        paid_states = ("completed", "paid", "in_production", "ready_for_dispatch", "ready_for_collection")
        will_pay = status in paid_states and not (wholesale and R.random() < 0.3)  # some wholesale buyers owe money
        method = R.choice(["bank_transfer", "cash", "pos"]) if channel != "online" else R.choice(["bank_transfer", "cash_on_delivery" if otype == "delivery" else "cash_at_pickup"])
        if status != "cancelled":
            pay = Payment(reference=f"DPAY-{o.order_number[5:]}", order_id=o.id, branch_id=br.id, amount_kobo=o.total_kobo, method=method, is_demo=True, created_at=when,
                          status="verified" if will_pay else ("awaiting_verification" if status == "paid" else "pending"))
            if will_pay:
                pay.verified_by, pay.verified_at = staff["accountant"][0].id, when + timedelta(hours=3)
                o.paid_kobo, o.payment_status = o.total_kobo, "paid"
                db.add(FinancialTransaction(reference=f"DTXN-{o.order_number[5:]}", kind="revenue", direction="in", amount_kobo=o.total_kobo, method=method, branch_id=br.id,
                                            txn_date=when.date(), description=f"Order {o.order_number}", sales_channel={"online": "online", "walk_in": "walk_in", "wholesale": "wholesale"}[channel],
                                            order_id=o.id, recorded_by=staff["accountant"][0].id, verification_status="verified", is_demo=True, created_at=when))
            db.add(pay)
        if status in ("completed", "ready_for_dispatch", "ready_for_collection"):
            o.stock_deducted = True
            for p, q in lines:
                try:
                    mv(p, br, -q, "sale_out", when + timedelta(hours=4), f"Order {o.order_number}", "order", o.order_number)
                except AssertionError:
                    o.stock_deducted = False
                    break
        if status == "ready_for_dispatch":
            ready_pool.append(o)

    # --- dispatch: one finished run, one in-progress run, remaining ready orders stay unassigned
    done_orders = db.query(Order).filter(Order.is_demo == True, Order.status == "completed", Order.order_type == "delivery").limit(3).all()  # noqa
    if done_orders:
        run = DeliveryRun(run_number="DRUN-0001", branch_id=main.id, driver_id=drivers[0].id, vehicle_id=vehicles[0].id, scheduled_departure=ago(2, 8), expected_return=ago(2, 12), status="completed",
                          actual_departure=ago(2, 8), actual_return=ago(2, 12), created_by=staff["dispatch_manager"][0].id, is_demo=True)
        run.assignments = [DeliveryAssignment(order_id=o.id, sequence=k + 1, status="delivered", started_at=ago(2, 9), completed_at=ago(2, 11),
                                              confirmation=DeliveryConfirmation(received_by_name=o.contact_name, customer_confirmed=True, notes="Delivered to gate")) for k, o in enumerate(done_orders)]
        db.add(run)
    live = ready_pool[:2]
    if live:
        run = DeliveryRun(run_number="DRUN-0002", branch_id=main.id, driver_id=drivers[1].id, vehicle_id=vehicles[1].id, scheduled_departure=datetime.now(timezone.utc) - timedelta(hours=1),
                          expected_return=datetime.now(timezone.utc) + timedelta(hours=3), status="in_progress", actual_departure=datetime.now(timezone.utc) - timedelta(hours=1),
                          created_by=staff["dispatch_manager"][0].id, is_demo=True)
        drivers[1].status = "on_delivery"
        vehicles[1].status = "in_use"
        run.assignments = [DeliveryAssignment(order_id=o.id, sequence=k + 1, status="out_for_delivery" if k == 0 else "assigned", started_at=datetime.now(timezone.utc) - timedelta(minutes=40) if k == 0 else None)
                           for k, o in enumerate(live)]
        for k, o in enumerate(live):
            o.status = "out_for_delivery" if k == 0 else "assigned_to_driver"
        db.add(run)

    # --- expenses
    for day in range(29, -1, -1):
        for _ in range(R.choice([0, 1, 1, 2])):
            cat = R.choice(list(ecats.values()))
            br = R.choice(work_branches)
            amt = R.choice([500000, 800000, 1200000, 2500000, 3500000, 6500000, 9000000]) if not cat.counts_in_cogs else R.choice([6000000, 9500000, 12000000])
            e = Expense(reference=f"DEXP-{day:02d}-{R.randint(100, 999)}", category_id=cat.id, description=f"{cat.name} - {br.name}", amount_kobo=amt, branch_id=br.id,
                        expense_date=(datetime.now() - timedelta(days=day)).date(), status="approved", recorded_by=staff["branch_manager"][0].id, decided_by=staff["accountant"][0].id,
                        created_at=ago(day), is_demo=True)
            db.add(e)
            db.flush()
            db.add(FinancialTransaction(reference=f"DTX-{e.reference}", kind="expense", direction="out", amount_kobo=amt, method="cash", branch_id=br.id, txn_date=e.expense_date,
                                        description=e.description, expense_id=e.id, recorded_by=e.recorded_by, is_demo=True, created_at=e.created_at))
    db.add(Expense(reference="DEXP-PEND-1", category_id=ecats["Repairs"].id, description="Oven thermostat replacement", amount_kobo=18500000, branch_id=main.id, expense_date=date.today(),
                   status="pending_approval", recorded_by=staff["branch_manager"][0].id, is_demo=True))

    # --- balances from ledger
    for (pid, bid), q in bal.items():
        db.add(InventoryBalance(product_id=pid, branch_id=bid, quantity=q))

    # --- tasks and notifications
    gm = staff["general_manager"][0]
    for title, to, pr_, st in (("Deep-clean proofing room", staff["general_staff"][0], "high", "assigned"), ("Count packaging stock", staff["inventory_manager"][0], "normal", "in_progress"),
                               ("Service delivery van DEMO-BYS-101", staff["dispatch_manager"][0], "urgent", "assigned"), ("Review weekend production plan", ops, "normal", "accepted")):
        db.add(Task(title=title, instructions="Demo task - please complete and add notes.", priority=pr_, status=st, assigned_to=to.id, department=to.department,
                    branch_id=main.id, created_by=gm.id, due_at=datetime.now(timezone.utc) + timedelta(days=1)))
    for u in staff["general_manager"] + staff["branch_manager"][:1]:
        db.add(Notification(user_id=u.id, kind="approval", title="Expense requires approval", body="DEXP-PEND-1: Oven thermostat replacement (₦185,000.00)", link="#/expenses"))
        db.add(Notification(user_id=u.id, kind="stock", title="Low stock: Yeast", body="Yeast is below its reorder level at Amarata Outlet.", link="#/inventory"))
    settings_service.set_value(db, "data_mode", "demo")
    settings_service.set_value(db, "bank_name", "Demo Bank Plc")
    settings_service.set_value(db, "bank_account_number", "0123456789")
    settings_service.set_value(db, "bank_account_name", "Bonjour Bakery (Demo)")
    db.commit()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    db = SessionLocal()
    if cmd == "purge":
        purge(db)
    elif cmd == "demo":
        pw = None
        if "--password" in sys.argv:
            pw = sys.argv[sys.argv.index("--password") + 1]
        pw = pw or ("Demo" + secrets.token_hex(3) + "26x")
        seed(db, pw)
        print(f"Demo data created and data mode switched to 'demo'.\nDemo staff logins use emails like demo.general_manager@{DEMO_MAIL}, demo.accountant@{DEMO_MAIL} ...\nDemo password: {pw}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
