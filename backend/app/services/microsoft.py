import os

import msal

AZURE_CLIENT_ID = os.environ["AZURE_CLIENT_ID"]
AZURE_TENANT_ID = os.environ["AZURE_TENANT_ID"]
AZURE_CLIENT_SECRET = os.environ["AZURE_CLIENT_SECRET"]
AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", "http://localhost:8080/api/v1/auth/callback")

AUTHORITY = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
SCOPES = ["User.Read"]


def _msal_app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=AZURE_CLIENT_ID,
        client_credential=AZURE_CLIENT_SECRET,
        authority=AUTHORITY,
    )


def get_auth_url(state: str) -> str:
    """URL vers laquelle rediriger le navigateur pour lancer le login Microsoft."""
    return _msal_app().get_authorization_request_url(
        scopes=SCOPES,
        state=state,
        redirect_uri=AZURE_REDIRECT_URI,
    )


def acquire_token_by_code(code: str) -> dict:
    """
    Échange le code d'autorisation contre un token, avec les claims utilisateur
    (oid, preferred_username/email, name) dans id_token_claims.
    Lève une exception si Microsoft renvoie une erreur (code expiré, etc.).
    """
    result = _msal_app().acquire_token_by_authorization_code(
        code=code,
        scopes=SCOPES,
        redirect_uri=AZURE_REDIRECT_URI,
    )
    if "error" in result:
        raise ValueError(f"{result['error']}: {result.get('error_description')}")
    return result
