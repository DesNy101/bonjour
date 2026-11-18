"""Permission catalogue and default role definitions. Seeded into the DB at startup (idempotent)."""

PERMISSIONS = {
    "dashboard.view": ("View management dashboard", "Overview"),
    "branches.view": ("View branches", "Branches"),
    "branches.manage": ("Create/edit branches", "Branches"),
    "orders.view": ("View orders", "Orders"),
    "orders.create": ("Create orders for customers / walk-in sales", "Orders"),
    "orders.manage": ("Update order status and details", "Orders"),
    "orders.cancel": ("Cancel orders", "Orders"),
    "payments.view": ("View payments", "Payments"),
    "payments.verify": ("Verify or reject payments", "Payments"),
    "customers.view": ("View customers", "Customers"),
    "customers.manage": ("Create/edit customers", "Customers"),
    "products.view": ("View products", "Products"),
    "products.manage": ("Create/edit products and categories", "Products"),
    "inventory.view": ("View inventory", "Inventory"),
    "inventory.adjust": ("Record stock movements", "Inventory"),
    "inventory.transfer": ("Transfer stock between branches", "Inventory"),
    "production.view": ("View production", "Production"),
    "production.manage": ("Plan and run production batches", "Production"),
    "recipes.manage": ("Manage recipes and production stages", "Production"),
    "suppliers.view": ("View suppliers", "Suppliers"),
    "suppliers.manage": ("Create/edit suppliers", "Suppliers"),
    "purchasing.view": ("View purchase requests and orders", "Purchasing"),
    "purchasing.request": ("Create purchase requests", "Purchasing"),
    "purchasing.approve": ("Approve purchase requests and orders", "Purchasing"),
    "purchasing.receive": ("Record goods received", "Purchasing"),
    "dispatch.view": ("View dispatch board", "Dispatch"),
    "dispatch.manage": ("Create delivery runs and assign drivers", "Dispatch"),
    "drivers.manage": ("Manage drivers", "Dispatch"),
    "vehicles.manage": ("Manage vehicles", "Dispatch"),
    "driver.app": ("Use the driver app", "Driver"),
    "staff.view": ("View staff", "Staff"),
    "staff.manage": ("Create staff, reset passwords, change roles", "Staff"),
    "roles.manage": ("Edit role permissions", "Staff"),
    "tasks.manage": ("Create and review tasks", "Tasks"),
    "finance.view": ("View finance dashboard and ledger", "Finance"),
    "finance.manage": ("Close cash register, post adjustments", "Finance"),
    "expenses.record": ("Record expenses", "Finance"),
    "expenses.approve": ("Approve or reject expenses", "Finance"),
    "reports.view": ("View reports", "Reports"),
    "reports.export": ("Export reports to CSV/PDF", "Reports"),
    "audit.view": ("View audit logs", "Admin"),
    "settings.view": ("View settings", "Admin"),
    "settings.manage": ("Change settings", "Admin"),
}

ALL = list(PERMISSIONS)

_branch_mgr = [
    "dashboard.view", "branches.view", "orders.view", "orders.create", "orders.manage", "orders.cancel",
    "payments.view", "customers.view", "customers.manage", "products.view", "inventory.view", "inventory.adjust",
    "inventory.transfer", "production.view", "production.manage", "suppliers.view", "purchasing.view",
    "purchasing.request", "purchasing.receive", "dispatch.view", "dispatch.manage", "staff.view", "tasks.manage",
    "finance.view", "expenses.record", "reports.view", "reports.export",
]

# key: (name, description, all_branches, is_staff, permissions)
ROLES = {
    "super_admin": ("Super Administrator", "Owner. Full access to every module and branch.", True, True, ALL),
    "general_manager": ("General Manager", "Runs the business across all branches.", True, True,
                        [p for p in ALL if p not in ("roles.manage", "settings.manage")]),
    "branch_manager": ("Branch Manager", "Manages the operations of assigned branch(es).", False, True, _branch_mgr),
    "production_manager": ("Production Manager", "Plans and supervises bread production.", False, True, [
        "dashboard.view", "production.view", "production.manage", "recipes.manage", "inventory.view", "inventory.adjust",
        "products.view", "tasks.manage", "orders.view", "reports.view", "purchasing.request", "purchasing.view", "staff.view"]),
    "inventory_manager": ("Inventory Manager", "Controls stock, materials and goods received.", False, True, [
        "inventory.view", "inventory.adjust", "inventory.transfer", "products.view", "products.manage",
        "suppliers.view", "purchasing.view", "purchasing.request", "purchasing.receive", "reports.view", "dashboard.view"]),
    "sales_officer": ("Sales Officer", "Takes and manages customer and walk-in orders.", False, True, [
        "orders.view", "orders.create", "orders.manage", "customers.view", "customers.manage", "products.view",
        "payments.view", "inventory.view", "dashboard.view"]),
    "dispatch_manager": ("Supply / Dispatch Manager", "Schedules deliveries, drivers and vehicles.", False, True, [
        "dispatch.view", "dispatch.manage", "drivers.manage", "vehicles.manage", "orders.view", "orders.manage",
        "customers.view", "inventory.view", "reports.view", "dashboard.view"]),
    "driver": ("Driver", "Sees and completes own deliveries only.", False, True, ["driver.app"]),
    "accountant": ("Accountant / Finance Officer", "Finance, payments, expenses and reports across all branches.", True, True, [
        "dashboard.view", "finance.view", "finance.manage", "expenses.record", "expenses.approve", "payments.view",
        "payments.verify", "reports.view", "reports.export", "suppliers.view", "purchasing.view", "orders.view",
        "customers.view", "branches.view"]),
    "customer_service": ("Customer Service Officer", "Handles customer enquiries, orders and complaints.", False, True, [
        "orders.view", "orders.create", "orders.manage", "orders.cancel", "customers.view", "customers.manage",
        "payments.view", "products.view", "dashboard.view"]),
    "general_staff": ("General Staff", "Personal workspace, tasks and notifications.", False, True, []),
    "customer": ("Customer", "Online ordering customer. No internal access.", False, False, []),
}

DEFAULT_PRODUCTION_STAGES = [
    ("Ingredients Preparation", "Production"), ("Mixing", "Production"), ("Kneading", "Production"),
    ("Proofing", "Production"), ("Baking", "Production"), ("Cooling", "Production"), ("Packaging", "Packaging"),
    ("Quality Inspection", "Quality"), ("Finished Goods", "Inventory"),
]

DEFAULT_EXPENSE_CATEGORIES = [
    ("Fuel", False), ("Transportation", False), ("Staff Expenses", False), ("Electricity", False), ("Water", False),
    ("Repairs", False), ("Raw Material Purchases", True), ("Packaging Expenses", True), ("Maintenance", False),
    ("Other Operational", False),
]

DEFAULT_PRODUCT_CATEGORIES = [("Bread", "finished"), ("Special Bread", "finished"), ("Raw Materials", "raw"), ("Packaging", "packaging")]
