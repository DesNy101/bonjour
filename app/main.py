import os
import threading
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.config import get_settings
from app.database import SessionLocal, engine
from app.middleware.security import SecurityHeaders
from app.routers import auth, public, staff, admin, catalog, orders, production, procurement, dispatch, tasks, finance, reports, dashboard
from app import bootstrap
from app.utils.uploads import upload_root

logging.basicConfig(level=logging.INFO)
cfg = get_settings()
ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"


def _initialise():
    """Idempotent reference-data/admin bootstrap. Runs in the background so the web server answers
    health checks immediately (on small hosts with a remote database this can take many seconds).
    A Postgres advisory lock stops multiple workers from running it at once."""
    log = logging.getLogger("bonjour")
    try:
        with SessionLocal() as db:
            if not db.execute(text("SELECT pg_try_advisory_lock(727001)")).scalar():
                return
            try:
                bootstrap.init(db)
            finally:
                db.execute(text("SELECT pg_advisory_unlock(727001)"))
                db.commit()
    except Exception as e:  # schema not migrated yet
        log.error("Startup initialisation failed (did you run 'alembic upgrade head'?): %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if cfg.is_production and cfg.secret_key.startswith("dev-only"):
        logging.getLogger("bonjour").warning("SECRET_KEY is the development default - set a real secret in production.")
    if os.environ.get("BOOTSTRAP_SYNC"):
        _initialise()  # tests need roles/admin ready before the first request
    else:
        threading.Thread(target=_initialise, name="bootstrap", daemon=True).start()
    yield


app = FastAPI(title="Bonjour Bakery Management System", version="1.0.0", lifespan=lifespan,
              docs_url="/docs" if not cfg.is_production else "/docs", description="REST API for the Bonjour Bakery platform.")
app.add_middleware(SecurityHeaders)

for r in (auth, public, staff, admin, catalog, orders, production, procurement, dispatch, tasks, finance, reports, dashboard):
    app.include_router(r.router)


@app.get("/health", tags=["System"])
def health():
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return {"status": "ok", "database": "up"}
    except Exception:
        return JSONResponse({"status": "degraded", "database": "down"}, status_code=503)


@app.exception_handler(StarletteHTTPException)
async def http_exc(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api/") or request.url.path in ("/health",):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))
    if exc.status_code == 404:
        return FileResponse(PUBLIC / "index.html")  # SPA fallback
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


app.mount("/uploads", StaticFiles(directory=str(upload_root())), name="uploads")
app.mount("/assets", StaticFiles(directory=str(PUBLIC / "assets")), name="assets")
app.mount("/js", StaticFiles(directory=str(PUBLIC / "js"), check_dir=False), name="js")


@app.get("/sw.js", include_in_schema=False)
def sw():
    return FileResponse(PUBLIC / "sw.js", media_type="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(PUBLIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/styles.css", include_in_schema=False)
def css():
    return FileResponse(PUBLIC / "styles.css", media_type="text/css", headers={"Cache-Control": "no-cache"})


@app.get("/app.js", include_in_schema=False)
def appjs():
    return FileResponse(PUBLIC / "app.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(PUBLIC / "index.html", headers={"Cache-Control": "no-cache"})
