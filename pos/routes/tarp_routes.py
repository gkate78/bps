"""Tarpaulin jobs page: the designer's own jobs, or all of them for admins."""
from typing import Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pos.auth_adapter import User, page_user
from pos.controllers import tarp_controller as tarp
from pos.database import get_db
from pos.templating import templates

router = APIRouter(prefix="/pos/tarp-jobs")


def _back(request: Request, back: str, message: str = "", error: str = "") -> RedirectResponse:
    request.session["pos_flash"] = {"message": message, "error": error}
    # Only our own page's filters come back here.
    query = back if back.startswith("?") and "//" not in back else ""
    return RedirectResponse(url=f"/pos/tarp-jobs{query}", status_code=303)


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def tarp_jobs_page(
    request: Request,
    show: str = Query("open"),
    designer: str = Query(""),
    user: User = Depends(page_user),
    db: AsyncSession = Depends(get_db),
):
    flash = request.session.pop("pos_flash", None) or {}
    show = show if show in ("open", "claimed", "all") else "open"
    designer_id: Optional[int] = int(designer) if designer.isdigit() else None
    return templates.TemplateResponse(
        request,
        "pos/tarp_jobs.html",
        {
            "user": user,
            "active": "tarp",
            "rows": await tarp.list_jobs(db, user, show, designer_id if user.role == "admin" else None),
            "steps": tarp.STEPS,
            "show": show,
            "designer": designer,
            "staff": await tarp.staff(db) if user.role == "admin" else [],
            "back": str(request.url.query and f"?{request.url.query}" or ""),
            "message": flash.get("message"),
            "error": flash.get("error"),
        },
    )


@router.post("/{job_id}/status", include_in_schema=False)
async def set_status(
    request: Request, job_id: int, status: str = Form(""), back: str = Form(""),
    user: User = Depends(page_user), db: AsyncSession = Depends(get_db),
):
    try:
        await tarp.set_status(db, job_id, status, user)
    except tarp.TarpError as exc:
        return _back(request, back, error=str(exc))
    return _back(request, back, message=f"Marked {tarp.STEPS[status].lower()}")


@router.post("/{job_id}/notes", include_in_schema=False)
async def set_notes(
    request: Request, job_id: int, notes: str = Form(""), back: str = Form(""),
    user: User = Depends(page_user), db: AsyncSession = Depends(get_db),
):
    try:
        await tarp.set_notes(db, job_id, notes, user)
    except tarp.TarpError as exc:
        return _back(request, back, error=str(exc))
    return _back(request, back, message="Notes saved")


@router.post("/{job_id}/specs", include_in_schema=False)
async def set_specs(
    request: Request, job_id: int, specs: str = Form(""), back: str = Form(""),
    user: User = Depends(page_user), db: AsyncSession = Depends(get_db),
):
    try:
        await tarp.set_specs(db, job_id, specs, user)
    except tarp.TarpError as exc:
        return _back(request, back, error=str(exc))
    return _back(request, back, message="Customer specs saved")


@router.post("/{job_id}/assign", include_in_schema=False)
async def assign(
    request: Request, job_id: int, designer: str = Form(""), back: str = Form(""),
    user: User = Depends(page_user), db: AsyncSession = Depends(get_db),
):
    try:
        await tarp.assign(db, job_id, int(designer) if designer.isdigit() else None, user)
    except tarp.TarpError as exc:
        return _back(request, back, error=str(exc))
    return _back(request, back, message="Job reassigned")
