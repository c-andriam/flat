import logging
from functools import lru_cache

import msal

from app.config import settings

logger = logging.getLogger("dsio.microsoft")

SCOPES = ["User.Read"]


@lru_cache(maxsize=1)
def _msal_app() -> msal.ConfidentialClientApplication:
    """Client MSAL mis en cache pour la durée de vie du process.

    Instancier `ConfidentialClientApplication` déclenche la récupération du
    document de découverte OpenID de Microsoft. Le recréer à chaque appel
    ajoutait un aller-retour réseau à `/login` comme à `/callback`, et
    repartait d'un cache de jetons vide à chaque fois.
    """
    authority = f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
    return msal.ConfidentialClientApplication(
        client_id=settings.azure_client_id,
        client_credential=settings.azure_client_secret,
        authority=authority,
    )


def get_auth_url(state: str) -> str:
    """URL vers laquelle rediriger le navigateur pour lancer le login Microsoft."""
    return _msal_app().get_authorization_request_url(
        scopes=SCOPES,
        state=state,
        redirect_uri=settings.azure_redirect_uri,
    )


def acquire_token_by_code(code: str) -> dict:
    """
    Échange le code d'autorisation contre un token, avec les claims utilisateur
    (oid, preferred_username/email, name) dans id_token_claims.
    Lève une ValueError si Microsoft renvoie une erreur (code expiré, etc.).
    """
    result = _msal_app().acquire_token_by_authorization_code(
        code=code,
        scopes=SCOPES,
        redirect_uri=settings.azure_redirect_uri,
    )
    if "error" in result:
        # `error_description` de Microsoft contient le code d'erreur AADSTS
        # utile au diagnostic, mais aussi parfois l'identifiant de la requête :
        # on le journalise, on ne le renvoie pas tel quel au navigateur.
        logger.warning(
            "Échec acquire_token_by_authorization_code : %s — %s",
            result.get("error"),
            result.get("error_description"),
        )
        raise ValueError(
            f"Échec de l'échange du code d'autorisation ({result['error']}). "
            "Relancer la connexion depuis /api/v1/auth/login."
        )
    return result
