import csv
import io
import math
import os
import secrets
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, asc, desc, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.biller_rule import BillerRule
from app.models.bill_record import BillRecord
from app.models.customer import Customer

ROUTING_URGENT_WINDOW_DAYS = max(0, int(os.getenv("ROUTING_URGENT_WINDOW_DAYS", "3")))


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
    for fmt in (
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _csv_cell(row: dict, *names: str) -> str:
    """First non-empty value for any header alias (exact key, then case-insensitive)."""
    for name in names:
        if not name:
            continue
        if name in row:
            v = row.get(name)
            if v is not None and str(v).strip():
                return str(v).strip()
    lowered = {(k or "").strip().lower(): v for k, v in row.items()}
    for name in names:
        lk = (name or "").strip().lower()
        if lk in lowered:
            v = lowered[lk]
            if v is not None and str(v).strip():
                return str(v).strip()
    return ""


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
    for key in ("account", "biller", "customer_name", "cp_number", "reference", "notes", "payment_channel"):
        value = payload.get(key)
        if value is None:
            continue
        payload[key] = str(value).strip().upper()
    return payload


def _normalized_biller_key(value: str) -> str:
    return str(value or "").strip().upper()


async def _get_biller_rule_maps(db: AsyncSession) -> tuple[dict[str, float], dict[str, float]]:
    result = await db.execute(select(BillerRule).where(BillerRule.is_active == True))  # noqa: E712
    rules = result.scalars().all()

    charge_map = {
        str(item.biller or "").strip().upper(): round(float(item.service_charge or 0), 2)
        for item in rules
        if str(item.biller or "").strip()
    }
    late_map = {
        str(item.biller or "").strip().upper(): round(float(item.late_charge or 0), 2)
        for item in rules
        if str(item.biller or "").strip()
    }
    return charge_map, late_map


def _normalized_payment_method(value: Optional[str]) -> str:
    key = str(value or "").strip().upper().replace("-", "_")
    aliases = {
        "BPI CREDIT CARD": "BPI_CC",
        "BPICC": "BPI_CC",
    }
    return aliases.get(key, key)


async def _get_biller_system_charge_maps(db: AsyncSession) -> dict[str, dict[str, float]]:
    result = await db.execute(select(BillerRule).where(BillerRule.is_active == True))  # noqa: E712
    rules = result.scalars().all()
    maps: dict[str, dict[str, float]] = {}
    for item in rules:
        key = _normalized_biller_key(item.biller)
        if not key:
            continue
        maps[key] = {
            "CASH": round(float(item.system_charge_cash or 0), 2),
            "GCASH": round(float(item.system_charge_gcash or 0), 2),
            "MAYA": round(float(item.system_charge_maya or 0), 2),
            "BAYAD": round(float(item.system_charge_bayad or 0), 2),
            "BPI_CC": round(float(item.system_charge_bpi_cc or 0), 2),
            "BPI": round(float(item.system_charge_bpi or 0), 2),
        }
    return maps


def _record_total_charges(record: BillRecord, system_maps: dict[str, dict[str, float]]) -> float:
    base = round(float(record.charge or 0) + float(record.amt2 or 0), 2)
    biller_key = _normalized_biller_key(record.biller)
    method_key = _normalized_payment_method(record.payment_method)
    system_charge = round(float(system_maps.get(biller_key, {}).get(method_key, 0)), 2)
    adjusted = base + system_charge if method_key == "BAYAD" else base - system_charge
    return round(adjusted, 2)


async def get_biller_charges(db: AsyncSession) -> dict[str, float]:
    charge_map, _ = await _get_biller_rule_maps(db)
    return charge_map


async def get_biller_late_charges(db: AsyncSession) -> dict[str, float]:
    _, late_map = await _get_biller_rule_maps(db)
    return late_map


async def get_biller_account_digits(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(select(BillerRule).where(BillerRule.is_active == True))  # noqa: E712
    rules = result.scalars().all()
    return {
        _normalized_biller_key(item.biller): int(item.account_digits)
        for item in rules
        if item.account_digits is not None and int(item.account_digits) > 0
    }


async def has_active_biller_rule(db: AsyncSession, biller: str) -> bool:
    key = _normalized_biller_key(biller)
    if not key:
        return False
    result = await db.execute(
        select(BillerRule.id)
        .where(BillerRule.biller == key)
        .where(BillerRule.is_active == True)  # noqa: E712
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def decide_payment_channel(
    db: AsyncSession,
    *,
    biller: str,
    total: float,
    due_date: Optional[date],
    online_available: bool = True,
) -> dict:
    """
    Decide suggested payment channel (ONLINE or BRANCH_MANUAL) using:
    - active biller rule as routing prerequisite
    - urgency window (due within N days, including overdue) with online priority
    - non-urgent default to branch/manual
    """
    key = _normalized_biller_key(biller)
    if not key or not await has_active_biller_rule(db, key):
        return {"channel": "BRANCH_MANUAL", "reason": "NO_ACTIVE_BILLER_RULE", "policy": None}
    if not online_available:
        return {"channel": "BRANCH_MANUAL", "reason": "ONLINE_UNAVAILABLE", "policy": None}

    today = date.today()
    if due_date is not None:
        urgent_until = today + timedelta(days=ROUTING_URGENT_WINDOW_DAYS)
        if due_date <= urgent_until:
            return {"channel": "ONLINE", "reason": "URGENT_DUE_DATE_ONLINE_PRIORITY", "policy": None}

    return {"channel": "BRANCH_MANUAL", "reason": "NON_URGENT_DEFAULT_BRANCH", "policy": None}


def _compute_charge(biller: str, bill_amount: float, charge_map: dict[str, float]) -> float:
    if not biller or bill_amount <= 0:
        return 0.0

    predefined_charge = charge_map.get(biller.strip().upper())
    if predefined_charge is None:
        return 0.0

    if bill_amount <= 3300:
        return round(max(predefined_charge, 15.0), 2)

    computed = math.ceil((bill_amount - 3300) / 1000) * 10 + 15
    return round(float(computed), 2)


def _compute_late_charge(
    biller: str,
    due_date: Optional[date],
    late_map: dict[str, float],
    ref_date: Optional[date] = None,
) -> float:
    if due_date is None:
        return 0.0
    basis_date = ref_date or date.today()
    if due_date >= basis_date:
        return 0.0
    return round(float(late_map.get(biller.strip().upper(), 0.0)), 2)


def _apply_computations(payload: dict, charge_map: dict[str, float], late_map: dict[str, float]) -> dict:
    bill_amt = round(float(payload.get("bill_amt", 0) or 0), 2)
    due_date = payload.get("due_date")
    txn_date = payload.get("txn_date")
    late_charge = _compute_late_charge(str(payload.get("biller", "") or ""), due_date, late_map, txn_date)
    cash = round(float(payload.get("cash", 0) or 0), 2)
    biller = str(payload.get("biller", "") or "").strip()

    charge = _compute_charge(biller, bill_amt, charge_map)
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
    txn_datetime = payload.get("txn_datetime") or datetime.now()
    txn_date = payload.get("txn_date") or txn_datetime.date()
    payload["txn_datetime"] = txn_datetime
    payload["txn_date"] = txn_date

    payload = _normalize_text_fields(payload)
    charge_map, late_map = await _get_biller_rule_maps(db)
    payload = _apply_computations(payload, charge_map, late_map)

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
        payment_reference=payload.get("payment_reference"),
        payment_method=payload.get("payment_method"),
        payment_channel=payload.get("payment_channel"),
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
    charge_map, late_map = await _get_biller_rule_maps(db)
    merged = _apply_computations(merged, charge_map, late_map)
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
            "payment_reference": updates.get("payment_reference", record.payment_reference),
            "payment_method": updates.get("payment_method", record.payment_method),
            "payment_channel": updates.get("payment_channel", record.payment_channel),
        }
    )
    updates = _apply_computations(
        {
            **updates
        },
        charge_map,
        late_map,
    )

    for key, value in updates.items():
        setattr(record, key, value)

    if not record.reference:
        record.reference = await _generate_reference(db, record.txn_date)

    record.updated_at = datetime.now()

    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def delete_record(db: AsyncSession, record_id: int) -> None:
    record = await get_record(db, record_id)
    await db.delete(record)
    await db.commit()


async def get_distinct_billers(db: AsyncSession) -> list[str]:
    records_result = await db.execute(select(BillRecord.biller).distinct().order_by(BillRecord.biller.asc()))
    record_billers = {row[0] for row in records_result.all() if row[0]}

    rules_result = await db.execute(select(BillerRule.biller).where(BillerRule.is_active == True))  # noqa: E712
    rule_billers = {row[0] for row in rules_result.all() if row[0]}
    return sorted(record_billers | rule_billers)


async def find_latest_by_account(db: AsyncSession, account: str) -> Optional[BillRecord]:
    stmt = (
        select(BillRecord)
        .where(BillRecord.account == account)
        .order_by(BillRecord.txn_datetime.desc(), BillRecord.id.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_customer_by_account(db: AsyncSession, account: str) -> Optional[Customer]:
    """Return the customer for this account (account is unique). Used to prefill form when user enters account."""
    stmt = select(Customer).where(Customer.account == account.strip())
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_customers(
    db: AsyncSession,
    *,
    biller: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 50,
) -> list[Customer]:
    """List known customer accounts, optionally filtered by biller and search term."""
    safe_limit = max(1, min(int(limit or 50), 200))
    stmt = select(Customer)

    if biller and biller.strip():
        stmt = stmt.where(func.upper(Customer.biller) == biller.strip().upper())

    if query and query.strip():
        like = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                Customer.account.ilike(like),
                Customer.customer_name.ilike(like),
                Customer.phone.ilike(like),
            )
        )

    stmt = stmt.order_by(asc(Customer.customer_name), asc(Customer.account)).limit(safe_limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def upsert_customer_from_record(
    db: AsyncSession,
    *,
    account: str,
    biller: str,
    customer_name: str,
    phone: str,
) -> Customer:
    """Insert or update customer_accounts by account (unique). New accounts saved so next entry can auto-fill."""
    account = account.strip()
    biller = (biller or "").strip()
    customer_name = (customer_name or "").strip()
    phone = (phone or "").strip()[:11]
    existing = await get_customer_by_account(db, account)
    if existing:
        existing.biller = biller or existing.biller
        existing.customer_name = customer_name or existing.customer_name
        existing.phone = phone or existing.phone
        existing.updated_at = datetime.utcnow()
        db.add(existing)
        await db.commit()
        await db.refresh(existing)
        return existing
    customer = Customer(
        account=account,
        biller=biller,
        customer_name=customer_name,
        phone=phone,
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return customer


async def reconciliation_summary(
    db: AsyncSession,
    for_date: date,
    *,
    cash_on_hand: Optional[float] = None,
) -> dict:
    """EOD summary with optional cash-on-hand variance check."""
    rows = (
        await db.execute(
            select(BillRecord).where(BillRecord.txn_date == for_date).order_by(BillRecord.id.asc())
        )
    ).scalars().all()
    system_maps = await _get_biller_system_charge_maps(db)

    collected = 0.0
    processed = 0.0
    record_count = 0
    processed_count = 0
    total_charges = 0.0
    for row in rows:
        row_total = round(float(row.total or 0), 2)
        collected += row_total
        total_charges += _record_total_charges(row, system_maps)
        record_count += 1
        if row.payment_reference is not None and str(row.payment_reference).strip() != "":
            processed += row_total
            processed_count += 1
    collected = round(collected, 2)
    processed = round(processed, 2)
    total_charges = round(total_charges, 2)

    pending = round(collected - processed, 2)
    if abs(processed - collected) < 0.01:
        flag = "match"
    elif processed > collected:
        flag = "short"
    else:
        flag = "pending"
    result = {
        "date": for_date.isoformat(),
        "collected": collected,
        "processed": processed,
        "pending": pending,
        "total_charges": total_charges,
        "record_count": record_count,
        "processed_count": processed_count,
        "flag": flag,
    }

    if cash_on_hand is not None:
        cash_value = round(float(cash_on_hand), 2)
        cash_variance = round(cash_value - collected, 2)
        if abs(cash_variance) < 0.01:
            cash_flag = "match"
        elif cash_variance < 0:
            cash_flag = "short"
        else:
            cash_flag = "over"
        result.update(
            {
                "cash_on_hand": cash_value,
                "cash_variance": cash_variance,
                "cash_flag": cash_flag,
            }
        )

    return result


async def reconciliation_report_summary(
    db: AsyncSession,
    *,
    period: str,
    reference_date: date,
) -> dict:
    """
    Aggregate reconciliation metrics by period bucket:
    - daily: each day in reference month
    - monthly: each month in reference year
    - yearly: each year across all data
    """
    normalized = (period or "daily").strip().lower()
    if normalized not in {"daily", "monthly", "yearly"}:
        normalized = "daily"

    filters = []
    if normalized == "daily":
        month_start = reference_date.replace(day=1)
        if month_start.month == 12:
            month_end = date(month_start.year + 1, 1, 1)
        else:
            month_end = date(month_start.year, month_start.month + 1, 1)
        filters.extend([BillRecord.txn_date >= month_start, BillRecord.txn_date < month_end])
    elif normalized == "monthly":
        year_start = date(reference_date.year, 1, 1)
        year_end = date(reference_date.year + 1, 1, 1)
        filters.extend([BillRecord.txn_date >= year_start, BillRecord.txn_date < year_end])

    stmt = select(BillRecord).order_by(BillRecord.txn_date.asc(), BillRecord.id.asc())
    if filters:
        stmt = stmt.where(*filters)
    rows = (await db.execute(stmt)).scalars().all()
    system_maps = await _get_biller_system_charge_maps(db)

    def bucket_label(txn_date: date) -> str:
        if normalized == "daily":
            return txn_date.isoformat()
        if normalized == "monthly":
            return txn_date.strftime("%Y-%m")
        return txn_date.strftime("%Y")

    bucket_map: dict[str, dict] = {}
    for row in rows:
        label = bucket_label(row.txn_date)
        current = bucket_map.setdefault(
            label,
            {
                "period_label": label,
                "collected": 0.0,
                "processed": 0.0,
                "pending": 0.0,
                "total_charges": 0.0,
                "record_count": 0,
                "processed_count": 0,
                "flag": "pending",
            },
        )
        row_total = round(float(row.total or 0), 2)
        current["collected"] += row_total
        current["record_count"] += 1
        current["total_charges"] += _record_total_charges(row, system_maps)
        if row.payment_reference is not None and str(row.payment_reference).strip() != "":
            current["processed"] += row_total
            current["processed_count"] += 1

    for item in bucket_map.values():
        item["collected"] = round(float(item["collected"]), 2)
        item["processed"] = round(float(item["processed"]), 2)
        item["total_charges"] = round(float(item["total_charges"]), 2)
        item["pending"] = round(item["collected"] - item["processed"], 2)
        if abs(item["processed"] - item["collected"]) < 0.01:
            item["flag"] = "match"
        elif item["processed"] > item["collected"]:
            item["flag"] = "short"
        else:
            item["flag"] = "pending"

    items = []
    totals = {
        "collected": 0.0,
        "processed": 0.0,
        "pending": 0.0,
        "total_charges": 0.0,
        "record_count": 0,
        "processed_count": 0,
    }
    for item in sorted(bucket_map.values(), key=lambda x: x["period_label"]):
        items.append(item)
        totals["collected"] += float(item["collected"])
        totals["processed"] += float(item["processed"])
        totals["pending"] += float(item["pending"])
        totals["total_charges"] += float(item["total_charges"])
        totals["record_count"] += int(item["record_count"])
        totals["processed_count"] += int(item["processed_count"])

    totals["collected"] = round(float(totals["collected"]), 2)
    totals["processed"] = round(float(totals["processed"]), 2)
    totals["pending"] = round(float(totals["pending"]), 2)
    totals["total_charges"] = round(float(totals["total_charges"]), 2)

    return {
        "period": normalized,
        "reference_date": reference_date.isoformat(),
        "items": items,
        "totals": totals,
    }


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

    today = date.today()
    if due_status == "overdue":
        base_filters.append(BillRecord.due_date.is_not(None))
        base_filters.append(BillRecord.due_date < today)
    elif due_status == "due_today":
        base_filters.append(BillRecord.due_date == today)
    elif due_status == "upcoming":
        base_filters.append(BillRecord.due_date.is_not(None))
        base_filters.append(BillRecord.due_date > today)
    elif due_status == "urgent":
        # Urgent queue: overdue or due within the next 3 days.
        window_end = today + timedelta(days=3)
        base_filters.append(BillRecord.due_date.is_not(None))
        base_filters.append(BillRecord.due_date <= window_end)
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
        "payment_reference": BillRecord.payment_reference,
        "payment_method": BillRecord.payment_method,
        "payment_channel": BillRecord.payment_channel,
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
            "payment_reference": r.payment_reference or "",
            "payment_method": r.payment_method or "",
            "payment_channel": r.payment_channel or "",
            "processed_at": (
                r.updated_at.isoformat(timespec="seconds")
                if (r.payment_reference is not None and str(r.payment_reference).strip() != "" and r.updated_at)
                else ""
            ),
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
    charge_map, late_map = await _get_biller_rule_maps(db)

    created = 0
    skipped = 0
    duplicates = 0

    for row in reader:
        date_raw = _csv_cell(row, "DATE", "txn_date", "TXN_DATE")
        txn_date = _parse_date(date_raw)
        if txn_date is None:
            dt_probe = _parse_datetime(_csv_cell(row, "DATE/TIME", "txn_datetime", "TXN_DATETIME"))
            if dt_probe is not None:
                txn_date = dt_probe.date()
        if txn_date is None:
            skipped += 1
            continue

        dt_raw = _csv_cell(row, "DATE/TIME", "txn_datetime", "TXN_DATETIME")
        txn_datetime = _parse_datetime(dt_raw) or datetime.combine(txn_date, datetime.min.time())

        notes_raw = _csv_cell(row, "NOTES", "notes")
        ref_raw = _csv_cell(row, "REFERENCE", "reference")
        pay_ref = _csv_cell(row, "payment_reference", "PAYMENT_REFERENCE", "PAYMENT REFERENCE")
        pay_method = _csv_cell(row, "payment_method", "PAYMENT_METHOD", "PAYMENT METHOD")
        # Import compatibility: if processed biller ref is not explicitly provided,
        # fall back to REFERENCE from source CSV.
        resolved_payment_reference = pay_ref or ref_raw

        payload = {
            "txn_datetime": txn_datetime,
            "txn_date": txn_date,
            "account": _csv_cell(row, "ACCOUNT", "account"),
            "biller": _csv_cell(row, "BILLER", "biller"),
            "customer_name": _csv_cell(row, "NAME", "customer_name", "CUSTOMER_NAME"),
            "cp_number": _csv_cell(row, "NUMBER", "CP NUM", "cp_number", "CP_NUMBER"),
            "bill_amt": _parse_float(_csv_cell(row, "AMT", "BILL AMT", "bill_amt", "BILL_AMT")),
            "amt2": _parse_float(_csv_cell(row, "AMT2", "LATE CHARGE", "amt2")),
            "charge": _parse_float(_csv_cell(row, "CHARGE", "SERVICE CHARGE", "charge")),
            "total": _parse_float(_csv_cell(row, "TOTAL", "total")),
            "cash": _parse_float(_csv_cell(row, "CASH", "cash")),
            "change_amt": _parse_float(_csv_cell(row, "CHANGE", "change_amt", "CHANGE_AMT")),
            "due_date": _parse_date(_csv_cell(row, "DUE DATE", "due_date", "DUE_DATE")),
            "notes": notes_raw or None,
            "reference": ref_raw or None,
            "payment_reference": resolved_payment_reference or None,
            "payment_method": pay_method or None,
            "payment_channel": _csv_cell(row, "payment_channel", "PAYMENT_CHANNEL", "PAYMENT CHANNEL") or None,
        }
        payload = _normalize_text_fields(payload)

        if not payload["account"] or not payload["customer_name"]:
            skipped += 1
            continue

        if _normalized_biller_key(payload.get("biller", "")) not in charge_map:
            skipped += 1
            continue

        payload = _apply_computations(payload, charge_map, late_map)

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
        # Keep customer_accounts in sync so lookup can prefill for this account
        await upsert_customer_from_record(
            db,
            account=payload["account"],
            biller=payload["biller"],
            customer_name=payload["customer_name"],
            phone=payload.get("cp_number", ""),
        )

    await db.commit()
    return {"created": created, "skipped": skipped, "duplicates": duplicates}
