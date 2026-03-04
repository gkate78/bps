from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

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
    account: str = ""
    biller: str = ""
    customer_name: str = ""
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
    account: Optional[str] = None
    biller: Optional[str] = None
    customer_name: Optional[str] = None
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
    id: Optional[int] = None

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
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        "admin_records.html",
        {"request": request, "current_user": current_user},
    )


@router.get("/entry/form", response_class=HTMLResponse, include_in_schema=False)
async def entry_form_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)
    if current_user.role not in ("admin", "encoder"):
        return RedirectResponse(url="/dashboard", status_code=303)
    billers = await get_distinct_billers(db)
    biller_charges = get_biller_charges()
    biller_late_charges = get_biller_late_charges()
    return templates.TemplateResponse(
        "entry_form.html",
        {
            "request": request,
            "current_user": current_user,
            "billers": billers,
            "biller_charges": biller_charges,
            "biller_late_charges": biller_late_charges,
        },
    )


@router.get("/api/records/datatable")
async def records_datatable(
    request: Request,
    biller: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    due_status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    params = request.query_params
    draw = int(params.get("draw", 0))
    start = int(params.get("start", 0))
    length = int(params.get("length", 10))
    search = params.get("search[value]", "") or ""
    order_col_idx = int(params.get("order[0][column]", 0))
    order_dir = params.get("order[0][dir]", "desc")
    columns = ["txn_datetime", "txn_date", "account", "biller", "customer_name", "cp_number", "bill_amt", "charge", "total", "cash", "change_amt", "due_date", "reference", "id"]
    order_column = columns[order_col_idx] if order_col_idx < len(columns) else "txn_datetime"
    return await datatable_query(
        db, draw, start, length, search, order_column, order_dir,
        biller=biller, from_date=from_date, to_date=to_date, due_status=due_status,
    )


@router.get("/api/records/billers")
async def billers_list(
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    return await get_distinct_billers(db)


@router.get("/api/records/lookup")
async def lookup_record(
    account: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    record = await find_latest_by_account(db, account)
    if not record:
        return None
    return {
        "id": record.id,
        "account": record.account,
        "biller": record.biller,
        "customer_name": record.customer_name,
        "cp_number": record.cp_number,
    }


@router.post("/api/records", response_model=RecordResponse)
async def create_record_endpoint(
    payload: RecordCreate,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    data = payload.model_dump(mode="python", exclude_none=True)
    record = await create_record(db, data)
    return record


@router.get("/api/records/{record_id}", response_model=RecordResponse)
async def get_record_endpoint(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    return await get_record(db, record_id)


@router.patch("/api/records/{record_id}", response_model=RecordResponse)
async def update_record_endpoint(
    record_id: int,
    payload: RecordUpdate,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    updates = payload.model_dump(exclude_none=True)
    return await update_record(db, record_id, updates)


@router.delete("/api/records/{record_id}")
async def delete_record_endpoint(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    await delete_record(db, record_id)
    return {"ok": True}


@router.post("/api/records/import")
async def import_csv_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    content = await file.read()
    return await import_csv_records(db, content)
