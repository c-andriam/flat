from app.workers.celery_app import app


@app.task(name="app.workers.ingestion.sync_sharepoint")
def sync_sharepoint():
    """TODO: lire les fichiers Excel/SharePoint et synchroniser vers PostgreSQL."""
    return {"status": "not_implemented"}
