from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth import get_current_user_optional, require_admin, require_data_entry_access
from app.controllers.bill_controller import (
    create_record,
    datatable_query,
    delete_record,
    find_latest_by_account,
    get_biller_charges,
    get_biller_late_charges,
    get_distinct_billers,
    get_record,
    import_csv_records,
    update_record,
)
from app.database import get_db
from app.models import UserAccount

router = APIRouter(tags=["bills"])
templates = Jinja2Templates(directory="app/templates")


class RecordCreate(BaseModel):
    txn_datetime: Optional[datetime] = None
    txn_date: Optional[date] = None
    account: str = Field(min_length=1, max_length=64)
    biller: str = Field(min_length=1, max_length=120)
    customer_name: str = Field(min_length=1, max_length=160)
    cp_number: str = ""
    bill_amt: float = 0
    amt2: float = 0
    charge: float = 0
    total: float = 0
    cash: float = 0
    change_amt: float = 0
    due_date: Optional[date] = None
    notes: Optional[str] = None
    reference: Optional[str] = None


class RecordUpdate(BaseModel):
    txn_datetime: Optional[datetime] = None
    txn_date: Optional[date] = None
    account: Optional[str] = Field(default=None, min_length=1, max_length=64)
    biller: Optional[str] = Field(default=None, min_length=1, max_length=120)
    customer_name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    cp_number: Optional[str] = None
    bill_amt: Optional[float] = None
    amt2: Optional[float] = None
    charge: Optional[float] = None
    total: Optional[float] = None
    cash: Optional[float] = None
    change_amt: Optional[float] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    reference: Optional[str] = None


class RecordResponse(RecordCreate):
    id: int

    model_config = {"from_attributes": True}


@router.get("/admin/records", response_class=HTMLResponse, include_in_schema=False)
async def admin_records_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)
    if current_user.role != "admin":
        return RedirectResponse(url="/customer/dashboard", status_code=303)

    billers = await get_distinct_billers(db)
    return templates.TemplateResponse(
        "records.html",
        {
            "request": request,
            "billers": billers,
            "biller_charges": get_biller_charges(),
            "biller_late_charges": get_biller_late_charges(),
            "current_user": current_user,
        },
    )


@router.get("/entry/form", response_class=HTMLResponse, include_in_schema=False)
async def entry_form_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)
    if current_user.role not in {"admin", "encoder"}:
        return RedirectResponse(url="/customer/dashboard", status_code=303)

    billers = await get_distinct_billers(db)
    return templates.TemplateResponse(
        "entry_form.html",
        {
            "request": request,
            "billers": billers,
            "biller_charges": get_biller_charges(),
            "biller_late_charges": get_biller_late_charges(),
            "current_user": current_user,
        },
    )


@router.get("/api/records/datatable")
async def records_datatable(
    request: Request,
    biller: Optional[str] = Query(default=None),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    due_status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    params = request.query_params

    draw = int(params.get("draw", 1))
    start = int(params.get("start", 0))
    length = int(params.get("length", 10))

    search = params.get("search[value]", "").strip()
    order_col_index = params.get("order[0][column]", "0")
    order_dir = params.get("order[0][dir]", "asc")

    col_data_key = params.get(f"columns[{order_col_index}][data]", "txn_date")

    if length > 200:
        length = 200

    return await datatable_query(
        db,
        draw=draw,
        start=start,
        length=length,
        search=search,
        order_column=col_data_key,
        order_dir=order_dir,
        biller=biller,
        from_date=from_date,
        to_date=to_date,
        due_status=due_status,
    )


@router.get("/api/records/billers")
async def list_billers(db: AsyncSession = Depends(get_db), _: UserAccount = Depends(require_admin)):
    return {"billers": await get_distinct_billers(db)}


@router.get("/api/admin/users")
async def list_users(db: AsyncSession = Depends(get_db), _: UserAccount = Depends(require_admin)):
    result = await db.execute(select(UserAccount).order_by(UserAccount.created_at.desc(), UserAccount.id.desc()))
    users = result.scalars().all()
    return {
        "users": [
            {
                "id": u.id,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "phone": u.phone,
                "role": u.role,
                "created_at": u.created_at.isoformat() if u.created_at else "",
            }
            for u in users
        ]
    }


@router.get("/api/records/biller-charges")
async def list_biller_charges(_: UserAccount = Depends(require_data_entry_access)):
    return {"biller_charges": get_biller_charges()}


@router.get("/api/records/by-account/{account}")
async def lookup_by_account(
    account: str,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    record = await find_latest_by_account(db, account.strip())
    if not record:
        raise HTTPException(status_code=404, detail="Account not found")

    return {
        "account": record.account,
        "biller": record.biller,
        "customer_name": record.customer_name,
        "cp_number": record.cp_number,
        "due_date": record.due_date.isoformat() if record.due_date else "",
    }


@router.get("/api/records/{record_id}", response_model=RecordResponse)
async def get_record_endpoint(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    return await get_record(db, record_id)


@router.get("/api/records/{record_id}/receipt", response_class=HTMLResponse)
async def receipt_page(
    record_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    record = await get_record(db, record_id)
    return templates.TemplateResponse(
        "receipt.html",
        {
            "request": request,
            "record": record,
        },
    )


@router.post("/api/records", response_model=RecordResponse, status_code=201)
async def create_record_endpoint(
    payload: RecordCreate,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    if payload.txn_datetime is None:
        payload.txn_datetime = datetime.utcnow()
    if payload.txn_date is None:
        payload.txn_date = payload.txn_datetime.date()

    if payload.due_date is None:
        raise HTTPException(status_code=400, detail="Due date is required")

    if payload.bill_amt <= 0:
        raise HTTPException(status_code=400, detail="Bill amount is required")

    record = await create_record(db, payload.model_dump())
    return record


@router.put("/api/records/{record_id}", response_model=RecordResponse)
async def update_record_endpoint(
    record_id: int,
    payload: RecordUpdate,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "due_date" in updates and updates["due_date"] is None:
        raise HTTPException(status_code=400, detail="Due date is required")

    record = await update_record(db, record_id, updates)
    return record


@router.delete("/api/records/{record_id}", status_code=204)
async def delete_record_endpoint(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    await delete_record(db, record_id)
    return None


@router.post("/api/records/import-csv")
async def import_csv_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")

    file_bytes = await file.read()
    result = await import_csv_records(db, file_bytes)
    return result
