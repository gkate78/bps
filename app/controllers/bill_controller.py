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

BILLER_CHARGES = {
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

_BILLER_LATE_CHARGES = {
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
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _parse_float(value: str | None) -> float:
    if not value:
        return 0.0

    cleaned = str(value).replace(",", "").strip()
    if cleaned == "":
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _normalized_amount(payload: dict) -> float:
    total = float(payload.get("total", 0) or 0)
    bill_amt = float(payload.get("bill_amt", 0) or 0)
    return round(total if total > 0 else bill_amt, 2)


def _normalize_text_fields(payload: dict) -> dict:
    for key in ("account", "biller", "customer_name", "cp_number", "reference"):
        value = payload.get(key)
        if value is None:
            continue
        payload[key] = str(value).strip().upper()
    return payload


def get_biller_charges() -> dict[str, float]:
    return dict(BILLER_CHARGES)


def get_biller_late_charges() -> dict[str, float]:
    return dict(_BILLER_LATE_CHARGES)


def _compute_charge(biller: str, bill_amount: float) -> float:
    if not biller or bill_amount <= 0:
        return 0.0

    predefined_charge = BILLER_CHARGES.get(biller.strip().upper())
    if predefined_charge is None:
        return 0.0

    if bill_amount <= 3300:
        return round(max(predefined_charge, 15.0), 2)

    computed = math.ceil((bill_amount - 3300) / 1000) * 10 + 15
    return round(float(computed), 2)


def _compute_late_charge(biller: str, due_date: Optional[date]) -> float:
    if due_date is None:
        return 0.0
    if due_date >= date.today():
        return 0.0
    return round(float(_BILLER_LATE_CHARGES.get(biller.strip().upper(), 0.0)), 2)


def _apply_computations(payload: dict) -> dict:
    bill_amt = round(float(payload.get("bill_amt", 0) or 0), 2)
    due_date = payload.get("due_date")
    late_charge = _compute_late_charge(str(payload.get("biller", "") or ""), due_date)
    cash = round(float(payload.get("cash", 0) or 0), 2)
    biller = str(payload.get("biller", "") or "").strip()

    charge = _compute_charge(biller, bill_amt)
    total = round(bill_amt + late_charge + charge, 2)
    change_amt = round(cash - total, 2)

    payload["bill_amt"] = bill_amt
    payload["amt2"] = late_charge
    payload["charge"] = charge
    payload["total"] = total
    payload["cash"] = cash
    payload["change_amt"] = change_amt
    return payload


async def _is_duplicate_record(
    db: AsyncSession,
    *,
    txn_date: date,
    account: str,
    biller: str,
    amount: float,
    exclude_id: Optional[int] = None,
) -> bool:
    rounded_amount = round(amount, 2)
    amount_filter = or_(
        func.round(BillRecord.total, 2) == rounded_amount,
        func.round(BillRecord.bill_amt, 2) == rounded_amount,
    )
    stmt = select(BillRecord.id).where(
        and_(
            BillRecord.txn_date == txn_date,
            BillRecord.account == account,
            BillRecord.biller == biller,
            amount_filter,
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(BillRecord.id != exclude_id)

    result = await db.execute(stmt.limit(1))
    return result.scalar_one_or_none() is not None


async def _generate_reference(db: AsyncSession, txn_date: date) -> str:
    date_part = txn_date.strftime("%Y%m%d")
    for _ in range(10):
        candidate = f"REF-{date_part}-{secrets.token_hex(3).upper()}"
        exists = await db.execute(select(BillRecord.id).where(BillRecord.reference == candidate).limit(1))
        if exists.scalar_one_or_none() is None:
            return candidate

    return f"REF-{date_part}-{secrets.token_hex(6).upper()}"


async def create_record(db: AsyncSession, payload: dict) -> BillRecord:
    txn_datetime = payload.get("txn_datetime") or datetime.utcnow()
    txn_date = payload.get("txn_date") or txn_datetime.date()
    payload["txn_datetime"] = txn_datetime
    payload["txn_date"] = txn_date

    payload = _normalize_text_fields(payload)
    payload = _apply_computations(payload)

    amount = _normalized_amount(payload)
    if await _is_duplicate_record(
        db,
        txn_date=txn_date,
        account=payload["account"],
        biller=payload["biller"],
        amount=amount,
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
        customer_name=payload["customer_name"],
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


async def update_record(db: AsyncSession, record_id: int, updates: dict) -> BillRecord:
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
    if due_date is None:
        raise HTTPException(status_code=400, detail="Due date is required")

    is_duplicate = await _is_duplicate_record(
        db,
        txn_date=merged["txn_date"],
        account=merged["account"],
        biller=merged["biller"],
        amount=amount,
        exclude_id=record_id,
    )
    if is_duplicate:
        raise HTTPException(
            status_code=409,
            detail="Duplicate detected: same date, account, biller, and amount already exists",
        )

    updates = _normalize_text_fields(
        {
            "txn_date": updates.get("txn_date", record.txn_date),
            "account": updates.get("account", record.account),
            "biller": updates.get("biller", record.biller),
            "customer_name": updates.get("customer_name", record.customer_name),
            "cp_number": updates.get("cp_number", record.cp_number),
            "bill_amt": updates.get("bill_amt", record.bill_amt),
            "amt2": updates.get("amt2", record.amt2),
            "charge": updates.get("charge", record.charge),
            "total": updates.get("total", record.total),
            "cash": updates.get("cash", record.cash),
            "change_amt": updates.get("change_amt", record.change_amt),
            "due_date": updates.get("due_date", record.due_date),
            "notes": updates.get("notes", record.notes),
            "reference": updates.get("reference", record.reference),
        }
    )
    updates = _apply_computations(
        {
            **updates
        }
    )

    for key, value in updates.items():
        setattr(record, key, value)

    if not record.reference:
        record.reference = await _generate_reference(db, record.txn_date)

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
    result = await db.execute(select(BillRecord.biller).distinct().order_by(BillRecord.biller.asc()))
    return [row[0] for row in result.all() if row[0]]


async def find_latest_by_account(db: AsyncSession, account: str) -> Optional[BillRecord]:
    stmt = (
        select(BillRecord)
        .where(BillRecord.account == account)
        .order_by(BillRecord.txn_datetime.desc(), BillRecord.id.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def datatable_query(
    db: AsyncSession,
    *,
    draw: int,
    start: int,
    length: int,
    search: str,
    order_column: str,
    order_dir: str,
    biller: Optional[str],
    from_date: Optional[date],
    to_date: Optional[date],
    due_status: Optional[str],
) -> dict:
    base_filters = []

    if biller:
        base_filters.append(BillRecord.biller == biller)
    if from_date:
        base_filters.append(func.date(BillRecord.txn_datetime) >= from_date)
    if to_date:
        base_filters.append(func.date(BillRecord.txn_datetime) <= to_date)

    if due_status == "overdue":
        base_filters.append(BillRecord.due_date.is_not(None))
        base_filters.append(BillRecord.due_date < date.today())
    elif due_status == "due_today":
        base_filters.append(BillRecord.due_date == date.today())
    elif due_status == "upcoming":
        base_filters.append(BillRecord.due_date.is_not(None))
        base_filters.append(BillRecord.due_date > date.today())
    elif due_status == "no_due_date":
        base_filters.append(BillRecord.due_date.is_(None))

    total_stmt = select(func.count()).select_from(BillRecord)
    total_count = (await db.execute(total_stmt)).scalar_one()

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
    filtered_count = (await db.execute(filtered_stmt)).scalar_one()

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

    data_stmt = data_stmt.order_by(sort, BillRecord.id.desc()).offset(start).limit(length)
    rows = (await db.execute(data_stmt)).scalars().all()

    data = [
        {
            "id": r.id,
            "txn_datetime": r.txn_datetime.isoformat(timespec="seconds") if r.txn_datetime else "",
            "txn_date": r.txn_date.isoformat(),
            "account": r.account,
            "biller": r.biller,
            "customer_name": r.customer_name,
            "cp_number": r.cp_number,
            "bill_amt": r.bill_amt,
            "amt2": r.amt2,
            "charge": r.charge,
            "total": r.total,
            "cash": r.cash,
            "change_amt": r.change_amt,
            "due_date": r.due_date.isoformat() if r.due_date else "",
            "notes": r.notes or "",
            "reference": r.reference or "",
        }
        for r in rows
    ]

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
        if txn_date is None:
            skipped += 1
            continue
        txn_datetime = _parse_datetime(row.get("DATE/TIME")) or datetime.combine(txn_date, datetime.min.time())

        payload = {
            "txn_datetime": txn_datetime,
            "txn_date": txn_date,
            "account": (row.get("ACCOUNT") or "").strip(),
            "biller": (row.get("BILLER") or "").strip(),
            "customer_name": (row.get("NAME") or "").strip(),
            "cp_number": (row.get("NUMBER") or row.get("CP NUM") or "").strip(),
            "bill_amt": _parse_float(row.get("AMT") or row.get("BILL AMT")),
            "amt2": _parse_float(row.get("AMT2")),
            "charge": _parse_float(row.get("CHARGE") or row.get("LATE CHARGE")),
            "total": _parse_float(row.get("TOTAL")),
            "cash": _parse_float(row.get("CASH")),
            "change_amt": _parse_float(row.get("CHANGE")),
            "due_date": _parse_date(row.get("DUE DATE")),
            "notes": (row.get("NOTES") or "").strip() or None,
            "reference": (row.get("REFERENCE") or "").strip() or None,
        }
        payload = _normalize_text_fields(payload)

        if not payload["account"] or not payload["customer_name"]:
            skipped += 1
            continue

        payload = _apply_computations(payload)

        amount = _normalized_amount(payload)
        is_duplicate = await _is_duplicate_record(
            db,
            txn_date=payload["txn_date"],
            account=payload["account"],
            biller=payload["biller"],
            amount=amount,
        )
        if is_duplicate:
            duplicates += 1
            continue

        if not payload.get("reference"):
            payload["reference"] = await _generate_reference(db, payload["txn_date"])

        db.add(BillRecord(**payload))
        created += 1

    await db.commit()
    return {"created": created, "skipped": skipped, "duplicates": duplicates}
