import os
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from jose import jwt

app = FastAPI(title="DSIO - Auth & Identity API")

SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "auth-api"}


def create_access_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# TODO: brancher le flow SSO Microsoft (MSAL) et le endpoint /login réel.
# Squelette minimal pour valider que le service démarre correctement.
@app.post("/auth/token")
def issue_token_stub():
    raise HTTPException(status_code=501, detail="SSO Microsoft/MSAL non implémenté")
