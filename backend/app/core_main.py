from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db

app = FastAPI(title="DSIO - Project Management Core API")

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Vérifie que l'API tourne et que PostgreSQL répond aux requêtes."""
    try:
        # Exécution d'une requête simple pour valider la liaison avec la base de données
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"unreachable ({str(e)})"

    return {
        "status": "ok",
        "service": "core-api",
        "database": db_status
    }
