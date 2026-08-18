"""
Envoi des emails via Microsoft Graph (Outlook).

Le worker de relance journalisait « Notification générée » et enregistrait un
`RelanceLog` en `sent_simulated` : rien ne partait réellement. Cette couche
fait l'envoi quand la configuration Azure le permet, et bascule sinon en mode
simulation explicite plutôt que d'échouer — un projet dont le SSO n'est pas
encore déclaré doit pouvoir tourner et produire des aperçus.

Prérequis côté Entra ID pour l'envoi réel :
  - permission d'application `Mail.Send` accordée par un administrateur ;
  - `GRAPH_SENDER_UPN` : la boîte d'envoi (ex. suivi-dsi@trimetagroup.mg).
"""

import logging
import os
from dataclasses import dataclass
from enum import Enum

import msal
import requests

from app.config import settings

logger = logging.getLogger("dsio.outlook")

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
TIMEOUT_SECONDS = 20


class SendMode(str, Enum):
    GRAPH = "graph"
    DRY_RUN = "dry_run"


class SendStatus(str, Enum):
    SENT = "sent"
    SIMULATED = "simulated"
    FAILED = "failed"
    SKIPPED_NO_EMAIL = "skipped_no_email"


@dataclass(frozen=True)
class SendResult:
    status: SendStatus
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in (SendStatus.SENT, SendStatus.SIMULATED)


def sender_upn() -> str | None:
    return (os.getenv("GRAPH_SENDER_UPN") or "").strip() or None


def send_mode() -> SendMode:
    """Envoi réel seulement si tout le nécessaire est présent.

    Mieux vaut un mode simulation assumé et visible dans les journaux qu'un
    envoi qui échoue silencieusement une fois par jour à 8 h.
    """
    if os.getenv("EMAIL_DRY_RUN", "").strip().lower() in ("1", "true", "yes"):
        return SendMode.DRY_RUN
    try:
        _ = settings.azure_client_id, settings.azure_tenant_id, settings.azure_client_secret
    except Exception:
        return SendMode.DRY_RUN
    return SendMode.GRAPH if sender_upn() else SendMode.DRY_RUN


def mode_explanation() -> str:
    """Phrase affichable dans l'API pour expliquer le mode courant."""
    if send_mode() is SendMode.GRAPH:
        return f"Envoi réel via Microsoft Graph depuis {sender_upn()}."
    manquants = []
    try:
        _ = settings.azure_client_id
    except Exception:
        manquants.append("AZURE_CLIENT_ID")
    try:
        _ = settings.azure_tenant_id
    except Exception:
        manquants.append("AZURE_TENANT_ID")
    try:
        _ = settings.azure_client_secret
    except Exception:
        manquants.append("AZURE_CLIENT_SECRET")
    if not sender_upn():
        manquants.append("GRAPH_SENDER_UPN")
    if os.getenv("EMAIL_DRY_RUN", "").strip().lower() in ("1", "true", "yes"):
        return "Simulation forcée par EMAIL_DRY_RUN."
    return (
        "Simulation : aucun email ne part réellement. Variables manquantes : "
        + ", ".join(manquants)
        + ". La permission d'application Mail.Send doit également être accordée "
        "dans Entra ID."
    )


_app_cache: msal.ConfidentialClientApplication | None = None


def _client() -> msal.ConfidentialClientApplication:
    global _app_cache
    if _app_cache is None:
        _app_cache = msal.ConfidentialClientApplication(
            client_id=settings.azure_client_id,
            client_credential=settings.azure_client_secret,
            authority=f"https://login.microsoftonline.com/{settings.azure_tenant_id}",
        )
    return _app_cache


def _access_token() -> str:
    # MSAL met le jeton en cache et ne rappelle Entra ID qu'à son expiration.
    result = _client().acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in result:
        raise RuntimeError(
            f"Jeton Graph refusé ({result.get('error')}): "
            f"{result.get('error_description', '')[:200]}"
        )
    return result["access_token"]


def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    *,
    reply_to: str | None = None,
) -> SendResult:
    """Envoie un email, ou le simule si la configuration est incomplète."""
    if not to:
        return SendResult(SendStatus.SKIPPED_NO_EMAIL, "Aucune adresse destinataire.")

    if send_mode() is SendMode.DRY_RUN:
        logger.info(
            "[SIMULATION] Email non envoyé à %s — sujet : %s (%d caractères de corps)",
            to, subject, len(html_body),
        )
        return SendResult(SendStatus.SIMULATED, mode_explanation())

    message = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        # Conserver une trace dans la boîte d'envoi : sans elle, impossible de
        # prouver a posteriori qu'une relance est bien partie.
        "saveToSentItems": True,
    }
    if reply_to:
        message["message"]["replyTo"] = [{"emailAddress": {"address": reply_to}}]

    try:
        response = requests.post(
            f"{GRAPH_ENDPOINT}/users/{sender_upn()}/sendMail",
            json=message,
            headers={"Authorization": f"Bearer {_access_token()}"},
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.exception("Appel Graph impossible pour %s", to)
        return SendResult(SendStatus.FAILED, f"{exc.__class__.__name__}: {exc}")

    if response.status_code == 202:
        logger.info("Email envoyé à %s — %s", to, subject)
        return SendResult(SendStatus.SENT)

    detail = response.text[:300]
    logger.error("Graph a refusé l'envoi à %s : %s %s", to, response.status_code, detail)
    return SendResult(SendStatus.FAILED, f"HTTP {response.status_code}: {detail}")
