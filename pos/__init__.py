"""
Shop register (Ditto Digital PrintShop): shop sales, loading, GCash/Maya cash-in/cash-out,
job orders, and the combined end-of-day count with bills. Plugged into BPS from main.py:

    register_pos(app)            # routes under /pos, static files under /pos/static
    await pos.database.init_db() # in the lifespan, after BPS's init_db()

Turned on with POS_ENABLED=1 (set by scripts/run_local.sh), so the online deployment stays bills-only.
"""
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from pos.auth_adapter import NotSignedIn

# Shown in BPS's Database View (Admin → Database), after the bills tables.
DATABASE_VIEW_TABLES = {
    "pos_sales": "Shop Sales",
    "pos_sale_lines": "Shop Sale Lines",
    "pos_sale_payments": "Shop Job Order Payments",
    "pos_wallet_txns": "Shop GCash/Maya Cash-in/out",
    "pos_parked_txns": "Shop Parked (unpaid)",
    "pos_drafts": "Shop Unsaved (being rung up)",
    "pos_day_closes": "End of Day",
    "pos_day_wallets": "End of Day GCash/Maya",
    "pos_cash_movements": "Cash Movements",
    "pos_services": "Shop Services",
    "pos_networks": "Load Networks",
    "pos_wallets": "GCash/Maya Accounts",
    "pos_fee_brackets": "Fee Brackets",
    "pos_settings": "Shop Settings",
    "pos_audit_log": "Shop Audit Log",
}


def pos_enabled() -> bool:
    return os.getenv("POS_ENABLED", "").strip().lower() in ("1", "true", "yes")


def register_pos(app: FastAPI) -> None:
    from app.routes.auth_routes import templates as bps_auth_templates
    from app.routes import bill_routes
    from app.routes.bill_routes import templates as bps_bill_templates
    from pos.routes.eod_routes import router as eod_router
    from pos.routes.register_routes import router as register_router
    from pos.routes.settings_routes import router as settings_router

    app.mount("/pos/static", StaticFiles(directory=str(Path(__file__).parent / "static" / "pos")), name="pos_static")
    app.include_router(register_router)
    app.include_router(eod_router)
    app.include_router(settings_router)

    # BPS pages show the Bills / Shop switch when the register is on.
    for bps_templates in (bps_auth_templates, bps_bill_templates):
        bps_templates.env.globals["pos_enabled"] = True
    bill_routes.DATABASE_VIEW_TABLES.update(DATABASE_VIEW_TABLES)

    @app.exception_handler(NotSignedIn)
    async def _not_signed_in(request: Request, exc: NotSignedIn):
        return RedirectResponse(url="/auth/signin", status_code=303)
