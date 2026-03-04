import csv
import io
import math
import secrets
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, asc, desc, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.bill_record import BillRecord

BILLER_CHARGES: dict[str, float] = {
    "MERALCO": 15.0,
    "CONVERGE": 25.0,
    "PLDT FIBER": 25.0,
    "SSS": 30.0,
    "GLOBE AT HOME": 25.0,
    "STA MARIA WATER": 15.0,
    "PLDT": 25.0,
    "SMART POSTPAID": 25.0,
    "BPICC": 25.0,
    "PSA": 30.0,
    "PRIME WATER": 25.0,
    "GLOBE POSTPAID": 25.0,
    "EASY TRIP": 25.0,
    "AUTO SWEEP RFID": 25.0,
    "SUN POSTPAID": 25.0,
    "NORZAGARAY WATER DISTRICT": 25.0,
}

_BILLER_LATE_CHARGES: dict[str, float] = {
    "MERALCO": 35.0,
}


def _parse_date(value: str | None) -> Optional[date]:
    if not value:
        return None
    cleaned = value.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _parse_datetime(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    cleaned = value.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _parse_float(value: str | None) -> float:
    if not value:
        return 0.0
    cleaned = value.strip().replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _normalized_amount(payload: dict) -> float:
    bill_amt = payload.get("bill_amt") or 0
    amt2 = payload.get("amt2") or 0
    charge = payload.get("charge") or 0
    total = payload.get("total") or 0
    return max(
        float(bill_amt) if bill_amt else 0,
        float(amt2) if amt2 else 0,
        float(charge) if charge else 0,
        float(total) if total else 0,
    )


def _normalize_text_fields(payload: dict) -> dict:
    result = {}
    for k, v in payload.items():
        if isinstance(v, str):
            result[k] = v.strip().upper() if v else ""
        else:
            result[k] = v
    return result


def get_biller_charges() -> dict[str, float]:
    return BILLER_CHARGES.copy()


def get_biller_late_charges() -> dict[str, float]:
    return _BILLER_LATE_CHARGES.copy()


def _compute_charge(biller: str, bill_amount: float) -> float:
    charges = get_biller_charges()
    rate = charges.get(biller.upper(), 0)
    return round(rate * math.ceil(bill_amount / 100), 2)


def _compute_late_charge(biller: str, due_date: Optional[date]) -> float:
    if not due_date:
        return 0.0
    late_charges = get_biller_late_charges()
    rate = late_charges.get(biller.upper(), 0)
    return rate if due_date < date.today() else 0.0


def _apply_computations(payload: dict) -> dict:
    payload = payload.copy()
    bill_amt = float(payload.get("bill_amt") or 0)
    customer_name = (payload.get("customer_name") or "").strip()
    account = (payload.get("account") or "").strip()
    biller = (payload.get("biller") or "").strip().upper()

    charge = _compute_charge(biller, bill_amt)
    due_date = payload.get("due_date")
    if isinstance(due_date, str):
        due_date = _parse_date(due_date)
    late_charge = _compute_late_charge(biller, due_date)

    total = bill_amt + charge + late_charge
    cash = float(payload.get("cash") or 0)
    change_amt = cash - total if cash >= total else 0

    payload["charge"] = charge
    payload["total"] = round(total, 2)
    payload["change_amt"] = round(change_amt, 2)
    return payload


async def _is_duplicate_record(
    db: AsyncSession,
    txn_date: date,
    account: str,
    biller: str,
    amount: float,
    exclude_id: Optional[int] = None,
) -> bool:
    stmt = select(BillRecord).where(
        and_(
            BillRecord.txn_date == txn_date,
            BillRecord.account == account,
            BillRecord.biller == biller,
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(BillRecord.id != exclude_id)

    result = await db.execute(stmt)
    for row in result.scalars().all():
        row_total = (row.bill_amt or 0) + (row.charge or 0)
        if abs(row_total - amount) < 0.01:
            return True
    return False


async def _generate_reference(db: AsyncSession, txn_date: date) -> str:
    date_part = txn_date.strftime("%Y%m%d")
    for _ in range(100):
        candidate = f"REF-{date_part}-{secrets.token_hex(6).upper()}"
        result = await db.execute(
            select(BillRecord.id).where(BillRecord.reference == candidate).limit(1)
        )
        if result.scalar_one_or_none() is None:
            return candidate
    return f"REF-{date_part}-{secrets.token_hex(6).upper()}"


async def create_record(db: AsyncSession, payload: dict) -> BillRecord:
    txn_datetime = payload.get("txn_datetime") or datetime.utcnow()
    txn_date = payload.get("txn_date") or (txn_datetime.date() if hasattr(txn_datetime, "date") else txn_datetime)
    payload["txn_datetime"] = txn_datetime
    payload["txn_date"] = txn_date

    payload = _normalize_text_fields(payload)
    payload = _apply_computations(payload)
    amount = _normalized_amount(payload)

    if await _is_duplicate_record(
        db, txn_date, payload["account"], payload["biller"], amount
    ):
        raise HTTPException(
            status_code=409,
            detail="Duplicate detected: same date, account, biller, and amount already exists",
        )

    reference = payload.get("reference")
    if not reference:
        reference = await _generate_reference(db, txn_date)

    record = BillRecord(
        txn_datetime=payload["txn_datetime"],
        txn_date=payload["txn_date"],
        account=payload["account"],
        biller=payload["biller"],
        customer_name=payload.get("customer_name", ""),
        cp_number=payload.get("cp_number", ""),
        bill_amt=payload.get("bill_amt", 0),
        amt2=payload.get("amt2", 0),
        charge=payload.get("charge", 0),
        total=payload.get("total", 0),
        cash=payload.get("cash", 0),
        change_amt=payload.get("change_amt", 0),
        due_date=payload.get("due_date"),
        notes=payload.get("notes"),
        reference=reference,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def get_record(db: AsyncSession, record_id: int) -> BillRecord:
    result = await db.execute(select(BillRecord).where(BillRecord.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


async def update_record(
    db: AsyncSession, record_id: int, updates: dict
) -> BillRecord:
    record = await get_record(db, record_id)

    merged = {
        "txn_date": updates.get("txn_date", record.txn_date),
        "account": updates.get("account", record.account),
        "biller": updates.get("biller", record.biller),
        "bill_amt": updates.get("bill_amt", record.bill_amt),
        "total": updates.get("total", record.total),
    }
    merged = _normalize_text_fields(merged)
    merged = _apply_computations(merged)
    amount = _normalized_amount(merged)

    if float(merged.get("bill_amt", 0) or 0) <= 0:
        raise HTTPException(status_code=400, detail="Bill amount is required")

    due_date = updates.get("due_date", record.due_date)
    if not due_date:
        raise HTTPException(status_code=400, detail="Due date is required")

    if await _is_duplicate_record(
        db,
        merged["txn_date"],
        merged["account"],
        merged["biller"],
        amount,
        exclude_id=record_id,
    ):
        raise HTTPException(
            status_code=409,
            detail="Duplicate detected: same date, account, biller, and amount already exists",
        )

    record.txn_date = merged["txn_date"]
    record.account = merged["account"]
    record.biller = merged["biller"]
    record.bill_amt = merged.get("bill_amt", 0)
    record.charge = merged.get("charge", 0)
    record.total = merged.get("total", 0)
    record.due_date = due_date
    record.updated_at = datetime.utcnow()

    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def delete_record(db: AsyncSession, record_id: int) -> None:
    record = await get_record(db, record_id)
    await db.delete(record)
    await db.commit()


async def get_distinct_billers(db: AsyncSession) -> list[str]:
    result = await db.execute(select(BillRecord.biller).distinct())
    return sorted(row[0] for row in result.all() if row[0])


async def find_latest_by_account(
    db: AsyncSession, account: str
) -> Optional[BillRecord]:
    stmt = (
        select(BillRecord)
        .where(BillRecord.account == account)
        .order_by(desc(BillRecord.txn_datetime), desc(BillRecord.id))
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def datatable_query(
    db: AsyncSession,
    draw: int,
    start: int,
    length: int,
    search: str,
    order_column: str,
    order_dir: str,
    biller: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    due_status: Optional[str] = None,
) -> dict:
    base_filters = []

    if biller:
        base_filters.append(BillRecord.biller == biller)
    if from_date:
        base_filters.append(func.date(BillRecord.txn_datetime) >= from_date)
    if to_date:
        base_filters.append(func.date(BillRecord.txn_datetime) <= to_date)
    if due_status == "overdue":
        base_filters.append(BillRecord.due_date.isnot(None))
        base_filters.append(BillRecord.due_date < date.today())
    elif due_status == "due_today":
        base_filters.append(BillRecord.due_date == date.today())
    elif due_status == "upcoming":
        base_filters.append(BillRecord.due_date.isnot(None))
        base_filters.append(BillRecord.due_date > date.today())
    elif due_status == "no_due_date":
        base_filters.append(BillRecord.due_date.is_(None))

    total_stmt = select(func.count()).select_from(BillRecord)
    total_result = await db.execute(total_stmt)
    total_count = total_result.scalar_one()

    filtered_filters = list(base_filters)
    if search:
        like = f"%{search}%"
        filtered_filters.append(
            or_(
                BillRecord.account.ilike(like),
                BillRecord.biller.ilike(like),
                BillRecord.customer_name.ilike(like),
                BillRecord.cp_number.ilike(like),
                BillRecord.reference.ilike(like),
            )
        )

    filtered_stmt = select(func.count()).select_from(BillRecord)
    if filtered_filters:
        filtered_stmt = filtered_stmt.where(*filtered_filters)
    filtered_result = await db.execute(filtered_stmt)
    filtered_count = filtered_result.scalar_one()

    order_map = {
        "txn_datetime": BillRecord.txn_datetime,
        "txn_date": BillRecord.txn_date,
        "account": BillRecord.account,
        "biller": BillRecord.biller,
        "customer_name": BillRecord.customer_name,
        "cp_number": BillRecord.cp_number,
        "bill_amt": BillRecord.bill_amt,
        "charge": BillRecord.charge,
        "total": BillRecord.total,
        "cash": BillRecord.cash,
        "change_amt": BillRecord.change_amt,
        "due_date": BillRecord.due_date,
        "reference": BillRecord.reference,
        "id": BillRecord.id,
    }
    sort_col = order_map.get(order_column, BillRecord.txn_datetime)
    sort = desc(sort_col) if order_dir == "desc" else asc(sort_col)

    data_stmt = select(BillRecord)
    if filtered_filters:
        data_stmt = data_stmt.where(*filtered_filters)
    data_stmt = (
        data_stmt.order_by(sort, desc(BillRecord.id))
        .offset(start)
        .limit(length)
    )
    result = await db.execute(data_stmt)
    rows = result.scalars().all()

    data = []
    for r in rows:
        data.append({
            "id": r.id,
            "txn_datetime": r.txn_datetime.isoformat(timespec="seconds") if r.txn_datetime else "",
            "txn_date": r.txn_date.isoformat() if r.txn_date else "",
            "account": r.account or "",
            "biller": r.biller or "",
            "customer_name": r.customer_name or "",
            "cp_number": r.cp_number or "",
            "bill_amt": r.bill_amt or 0,
            "amt2": r.amt2 or 0,
            "charge": r.charge or 0,
            "total": r.total or 0,
            "cash": r.cash or 0,
            "change_amt": r.change_amt or 0,
            "due_date": r.due_date.isoformat() if r.due_date else "",
            "notes": r.notes or "",
            "reference": r.reference or "",
        })

    return {
        "draw": draw,
        "recordsTotal": total_count,
        "recordsFiltered": filtered_count,
        "data": data,
    }


async def import_csv_records(db: AsyncSession, file_bytes: bytes) -> dict:
    text = file_bytes.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))

    created = 0
    skipped = 0
    duplicates = 0

    for row in reader:
        txn_date = _parse_date(row.get("DATE") or row.get("DATE/TIME"))
        if not txn_date:
            skipped += 1
            continue

        txn_datetime = _parse_datetime(row.get("DATE/TIME"))
        if not txn_datetime:
            txn_datetime = datetime.combine(txn_date, datetime.min.time())

        account = (row.get("ACCOUNT") or "").strip()
        biller = (row.get("BILLER") or "").strip()
        customer_name = (row.get("NAME") or "").strip()
        cp_number = (row.get("NUMBER") or row.get("CP NUM") or "").strip()

        bill_amt = _parse_float(row.get("AMT") or row.get("BILL AMT"))
        amt2 = _parse_float(row.get("AMT2"))
        charge = _parse_float(row.get("CHARGE") or row.get("LATE CHARGE"))
        total = _parse_float(row.get("TOTAL"))
        cash = _parse_float(row.get("CASH"))
        change_amt = _parse_float(row.get("CHANGE"))
        due_date = _parse_date(row.get("DUE DATE"))
        notes = (row.get("NOTES") or "").strip() or None
        reference = (row.get("REFERENCE") or "").strip() or None

        payload = {
            "txn_datetime": txn_datetime,
            "txn_date": txn_date,
            "account": account,
            "biller": biller,
            "customer_name": customer_name,
            "cp_number": cp_number,
            "bill_amt": bill_amt,
            "amt2": amt2,
            "charge": charge,
            "total": total,
            "cash": cash,
            "change_amt": change_amt,
            "due_date": due_date,
            "notes": notes,
            "reference": reference,
        }
        payload = _normalize_text_fields(payload)

        if not payload["account"] or not payload["customer_name"]:
            skipped += 1
            continue

        payload = _apply_computations(payload)
        amount = _normalized_amount(payload)

        if await _is_duplicate_record(
            db, txn_date, payload["account"], payload["biller"], amount
        ):
            duplicates += 1
            continue

        if not payload.get("reference"):
            payload["reference"] = await _generate_reference(db, txn_date)

        db.add(BillRecord(**payload))
        created += 1

    await db.commit()

    return {"created": created, "skipped": skipped, "duplicates": duplicates}
