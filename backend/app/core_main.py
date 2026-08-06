from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.routers import core as core_router
from app.routers import users as users_router

app = FastAPI(title="DSIO - Project Management Core API")
app.include_router(core_router.router, prefix="/api/v1")
app.include_router(users_router.router, prefix="/api/v1")


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Vérifie que l'API tourne et que PostgreSQL répond aux requêtes."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"unreachable ({str(e)})"

    return {
        "status": "ok",
        "service": "core-api",
        "database": db_status
    }
