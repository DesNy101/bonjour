from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field, EmailStr, field_validator, ConfigDict


class Base(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class LoginIn(Base):
    email: str
    password: str = Field(min_length=1, max_length=200)


class RegisterIn(Base):
    name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=40)
    password: str = Field(min_length=8, max_length=200)


class PasswordChangeIn(Base):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


class ForgotIn(Base):
    email: EmailStr


class ResetIn(Base):
    token: str
    new_password: str = Field(min_length=8, max_length=200)


class ProfileIn(Base):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    phone: Optional[str] = Field(None, max_length=40)
    preferred_branch_id: Optional[int] = None


class AddressIn(Base):
    label: str = "Home"
    address: str = Field(min_length=5, max_length=300)
    lga: str = ""
    is_default: bool = False


class BranchIn(Base):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    address: str = ""
    state: str = "Bayelsa"
    lga: str = ""
    phone: str = ""
    manager_id: Optional[int] = None
    is_active: bool = True
    opened_on: Optional[date] = None
    accepts_online_orders: bool = True


class StaffIn(Base):
    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: str = ""
    employee_id: Optional[str] = None
    role_key: str
    branch_id: Optional[int] = None
    extra_branch_ids: list[int] = []
    department: str = ""
    job_title: str = ""
    password: Optional[str] = None
    work_schedule: str = ""
    license_no: str = ""


class StaffUpdate(Base):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    employee_id: Optional[str] = None
    role_key: Optional[str] = None
    branch_id: Optional[int] = None
    extra_branch_ids: Optional[list[int]] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    is_active: Optional[bool] = None
    work_schedule: Optional[str] = None
    permission_overrides: Optional[dict[str, bool]] = None  # perm key -> granted


class RolePermsIn(Base):
    permissions: list[str]


class CategoryIn(Base):
    name: str = Field(min_length=2, max_length=100)
    kind: str = "finished"


class ProductIn(Base):
    sku: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=150)
    kind: str = "finished"
    category_id: Optional[int] = None
    size_label: str = ""
    unit: str = "pcs"
    description: str = ""
    image_url: str = ""
    price_kobo: int = Field(0, ge=0)
    wholesale_price_kobo: int = Field(0, ge=0)
    cost_kobo: int = Field(0, ge=0)
    reorder_level: float = Field(0, ge=0)
    is_active: bool = True
    is_sellable: Optional[bool] = None
    opening_stock: float = Field(0, ge=0)
    opening_branch_id: Optional[int] = None


class CustomerIn(Base):
    name: str = Field(min_length=2, max_length=150)
    phone: str = ""
    email: str = ""
    customer_type: str = "retail"
    preferred_branch_id: Optional[int] = None
    notes: str = ""
    address: Optional[str] = None


class SettingsIn(Base):
    values: dict


class OrderLine(Base):
    product_id: int
    quantity: int = Field(ge=1, le=100000)


class OrderIn(Base):
    branch_id: int
    order_type: str = Field(pattern="^(delivery|pickup)$")
    contact_name: str = Field(min_length=2, max_length=150)
    contact_phone: str = Field(min_length=7, max_length=40)
    contact_email: str = ""
    delivery_address: str = ""
    delivery_lga: str = ""
    delivery_instructions: str = ""
    preferred_date: Optional[date] = None
    preferred_time: str = ""
    notes: str = ""
    payment_method: str = Field(pattern="^(cash_on_delivery|cash_at_pickup|bank_transfer|paystack)$")
    items: list[OrderLine]


class StaffOrderIn(OrderIn):
    customer_id: Optional[int] = None
    channel: str = Field("staff", pattern="^(walk_in|wholesale|bulk|staff)$")
    payment_method: str = Field(pattern="^(cash_on_delivery|cash_at_pickup|bank_transfer|paystack|cash|pos)$")
    contact_phone: str = Field("", max_length=40)
    contact_name: str = Field(min_length=2, max_length=150)
    amount_paid_kobo: int = Field(0, ge=0)


class StatusIn(Base):
    status: str
    note: str = ""


class OrderEditIn(Base):
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    delivery_address: Optional[str] = None
    delivery_instructions: Optional[str] = None
    preferred_date: Optional[date] = None
    preferred_time: Optional[str] = None
    notes: Optional[str] = None


class PaymentIn(Base):
    method: str
    amount_kobo: int = Field(gt=0)
    reference_note: str = ""


class ProofIn(Base):
    transfer_reference: str = Field(min_length=3, max_length=120)
    note: str = ""


class VerifyIn(Base):
    approve: bool
    note: str = ""


class StockMoveIn(Base):
    product_id: int
    branch_id: int
    movement_type: str
    quantity: float
    reason: str = Field(min_length=3, max_length=300)


class TransferIn(Base):
    product_id: int
    from_branch_id: int
    to_branch_id: int
    quantity: float = Field(gt=0)
    note: str = ""


class IngredientIn(Base):
    material_id: int
    quantity: float = Field(gt=0)


class RecipeIn(Base):
    product_id: int
    name: str = Field(min_length=2, max_length=150)
    yield_qty: float = Field(gt=0)
    instructions: str = ""
    ingredients: list[IngredientIn]


class StageIn(Base):
    name: str = Field(min_length=2, max_length=80)
    sequence: int = 0
    department: str = "Production"
    is_active: bool = True


class BatchLine(Base):
    product_id: int
    planned_qty: float = Field(gt=0)
    order_id: Optional[int] = None


class PlanIn(Base):
    branch_id: int
    plan_date: date
    start_time: Optional[datetime] = None
    expected_end: Optional[datetime] = None
    supervisor_id: Optional[int] = None
    notes: str = ""
    batches: list[BatchLine]


class StageAdvanceIn(Base):
    notes: str = ""


class StageAssignIn(Base):
    stage_log_id: int
    user_id: Optional[int] = None


class BatchCompleteIn(Base):
    actual_qty: float = Field(ge=0)
    rejected_qty: float = Field(0, ge=0)
    wastage_qty: float = Field(0, ge=0)
    actual_consumption: dict[str, float] = {}
    notes: str = ""


class SupplierIn(Base):
    name: str = Field(min_length=2, max_length=150)
    contact_person: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    materials_supplied: str = ""
    is_active: bool = True


class PRLine(Base):
    product_id: int
    quantity: float = Field(gt=0)
    est_unit_cost_kobo: int = Field(0, ge=0)


class PurchaseRequestIn(Base):
    branch_id: int
    reason: str = ""
    items: list[PRLine]
    submit: bool = True


class DecisionIn(Base):
    approve: bool
    note: str = ""


class POLine(Base):
    product_id: int
    quantity: float = Field(gt=0)
    unit_cost_kobo: int = Field(ge=0)


class PurchaseOrderIn(Base):
    supplier_id: int
    branch_id: int
    request_id: Optional[int] = None
    notes: str = ""
    items: list[POLine]


class ReceiptLine(Base):
    product_id: int
    quantity: float = Field(gt=0)


class ReceiptIn(Base):
    delivery_note: str = ""
    items: list[ReceiptLine]


class SupplierInvoiceIn(Base):
    supplier_id: int
    po_id: Optional[int] = None
    invoice_number: str = Field(min_length=1, max_length=60)
    amount_kobo: int = Field(gt=0)
    due_date: Optional[date] = None


class SupplierPaymentIn(Base):
    invoice_id: int
    amount_kobo: int = Field(gt=0)
    method: str = "bank_transfer"
    reference: str = ""


class DriverIn(Base):
    user_id: int
    license_no: str = ""
    phone: str = ""
    branch_id: Optional[int] = None
    status: str = "available"
    is_active: bool = True


class VehicleIn(Base):
    plate_number: str = Field(min_length=3, max_length=30)
    vehicle_type: str = "Van"
    capacity_units: int = Field(500, gt=0)
    branch_id: Optional[int] = None
    status: str = "available"
    notes: str = ""
    is_active: bool = True


class RunIn(Base):
    branch_id: int
    driver_id: int
    vehicle_id: int
    scheduled_departure: datetime
    expected_return: datetime
    order_ids: list[int]
    notes: str = ""


class DeliveryDoneIn(Base):
    received_by_name: str = ""
    customer_confirmed: bool = True
    notes: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    cash_collected_kobo: int = Field(0, ge=0)


class DeliveryFailIn(Base):
    reason: str = Field(min_length=3, max_length=300)
    notes: str = ""


class VehicleIssueIn(Base):
    vehicle_id: int
    description: str = Field(min_length=3)


class TaskIn(Base):
    title: str = Field(min_length=2, max_length=200)
    instructions: str = ""
    priority: str = Field("normal", pattern="^(low|normal|high|urgent)$")
    assigned_to: Optional[int] = None
    department: str = ""
    branch_id: Optional[int] = None
    due_at: Optional[datetime] = None


class TaskUpdateIn(Base):
    status: Optional[str] = None
    completion_notes: Optional[str] = None
    problem_report: Optional[str] = None
    review_note: Optional[str] = None


class ExpenseIn(Base):
    category_id: int
    description: str = Field(min_length=3, max_length=300)
    amount_kobo: int = Field(gt=0)
    branch_id: int
    expense_date: Optional[date] = None
    supporting_ref: str = ""


class ExpenseCategoryIn(Base):
    name: str = Field(min_length=2, max_length=100)
    counts_in_cogs: bool = False
    is_active: bool = True


class AdjustmentIn(Base):
    direction: str = Field(pattern="^(in|out)$")
    amount_kobo: int = Field(gt=0)
    branch_id: int
    reason: str = Field(min_length=5, max_length=300)


class RegisterCloseIn(Base):
    branch_id: int
    close_date: Optional[date] = None
    opening_kobo: int = Field(0, ge=0)
    counted_kobo: int = Field(ge=0)
    notes: str = ""
