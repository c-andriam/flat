from fastapi import FastAPI

from app.routers import auth as auth_router

app = FastAPI(title="DSIO - Auth & Identity API")
app.include_router(auth_router.router, prefix="/api/v1")


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "auth-api"}
