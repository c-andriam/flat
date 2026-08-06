from app.workers.celery_app import app


@app.task(name="app.workers.writeback.mirror_to_sharepoint")
def mirror_to_sharepoint():
    """TODO: reporter les changements PostgreSQL vers SharePoint par ancre."""
    return {"status": "not_implemented"}
