from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies.auth import require
from app.services import analytics

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("")
def dashboard(branch_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
              p=Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    from app.dependencies.auth import scope_branch
    scope_branch(p, branch_id)
    return analytics.overview(db, p, branch_id, date_from, date_to)
