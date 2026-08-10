import os

import msal

AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", "http://localhost:8080/api/v1/auth/callback")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variable d'environnement manquante: {name}")
    return value

SCOPES = ["User.Read"]


def _msal_app() -> msal.ConfidentialClientApplication:
    azure_client_id = _required_env("AZURE_CLIENT_ID")
    azure_tenant_id = _required_env("AZURE_TENANT_ID")
    azure_client_secret = _required_env("AZURE_CLIENT_SECRET")
    authority = f"https://login.microsoftonline.com/{azure_tenant_id}"

    return msal.ConfidentialClientApplication(
        client_id=azure_client_id,
        client_credential=azure_client_secret,
        authority=authority,
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
