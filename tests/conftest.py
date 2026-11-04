"""
Test setup: the BPS app (with the shop register on) against a temporary database per test.
Staff accounts and records are added with a plain SQLModel session on the same file.
"""
import os
from datetime import datetime

os.environ.setdefault("POS_ENABLED", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlmodel import Session, create_engine  # noqa: E402

from app import database as app_database  # noqa: E402
from app.auth import hash_pin  # noqa: E402
from app.models import BusinessProfile, UserAccount  # noqa: E402

ADMIN_PHONE, ADMIN_PIN = "09171234567", "8642"
ENCODER_PHONE, ENCODER_PIN = "09170000001", "1357"
CUSTOMER_PHONE, CUSTOMER_PIN = "09170000002", "2468"


class Shop:
    """Test helper: a client plus direct database access."""

    def __init__(self, client: TestClient, db_url: str):
        self.client = client
        self.engine = create_engine(db_url)

    def add(self, *rows):
        with Session(self.engine) as session:
            for row in rows:
                session.add(row)
            session.commit()
            for row in rows:
                session.refresh(row)
        return rows[0] if len(rows) == 1 else rows

    def add_user(self, phone: str, pin: str, role: str, first_name: str):
        pin_hash, pin_salt = hash_pin(pin)
        return self.add(UserAccount(first_name=first_name, last_name="TEST", phone=phone, pin_hash=pin_hash, pin_salt=pin_salt, role=role))

    def sign_in(self, phone: str, pin: str):
        self.client.post("/auth/logout")
        r = self.client.post("/auth/signin", data={"phone": phone, "pin": pin}, follow_redirects=False)
        assert r.status_code == 303, r.text
        return r


@pytest.fixture()
def shop(tmp_path, monkeypatch):
    path = tmp_path / "bills_admin.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    monkeypatch.setattr(app_database, "engine", engine)
    monkeypatch.setattr(app_database, "AsyncSessionLocal", async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))
    from main import app

    with TestClient(app) as client:
        s = Shop(client, f"sqlite:///{path}")
        admin = s.add_user(ADMIN_PHONE, ADMIN_PIN, "admin", "KATE")
        s.add(
            BusinessProfile(
                admin_user_id=admin.id,
                business_name="DITTO DIGITAL PRINTSHOP",
                business_address="SAMPLE ADDRESS",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        s.sign_in(ADMIN_PHONE, ADMIN_PIN)
        yield s
