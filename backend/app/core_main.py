from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import Base, engine, get_db
from app import models  # noqa: F401  (nécessaire pour enregistrer tous les modèles sur Base.metadata)

app = FastAPI(title="DSIO - Project Management Core API")


@app.on_event("startup")
def on_startup():
    # TODO: remplacer par des migrations Alembic avant la mise en production.
    # Suffisant pour le POC : crée les tables si elles n'existent pas encore.
    Base.metadata.create_all(bind=engine)


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
