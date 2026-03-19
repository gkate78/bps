import os
import inspect
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.database import init_db
from app.routes.auth_routes import router as auth_router
from app.routes.bill_routes import router as bills_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Bills Admin Dashboard",
    description="Admin dashboard to manage masked billing records",
    version="1.0.0",
    lifespan=lifespan,
)
_behind_https = os.getenv("BEHIND_HTTPS", "").strip().lower() in ("1", "true", "yes")
session_kwargs = {
    "secret_key": os.getenv("SESSION_SECRET", "dev-only-change-me"),
    "same_site": "lax",
}
# Backward-compatible: older Starlette may not support `https_only`.
if "https_only" in inspect.signature(SessionMiddleware.__init__).parameters:
    session_kwargs["https_only"] = _behind_https

app.add_middleware(SessionMiddleware, **session_kwargs)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(auth_router)
app.include_router(bills_router)


@app.get("/", include_in_schema=False)
async def root(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/auth/signin")


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
