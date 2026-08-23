"""
Accès aux fichiers SharePoint via Microsoft Graph.

Couche de **lecture seule**. Elle résout le site et la bibliothèque de
documents, parcourt le dossier racine des projets et télécharge les classeurs
de suivi. Rien n'est écrit : la création de dossiers et l'écriture dans les
classeurs viendront après, une fois ce sens éprouvé.

Prérequis côté Entra ID : une permission **d'application** sur les fichiers.
`Sites.Selected`, accordée sur le seul site de la DSI, est préférable à
`Sites.ReadWrite.All` ou `Files.Read.All`, qui ouvrent l'ensemble des sites du
tenant à l'application.

Configuration absente, `is_configured()` renvoie faux et l'appelant retombe sur
l'import depuis un dossier local. Une intégration à moitié configurée qui
échoue à chaque tâche planifiée est pire qu'une intégration désactivée.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import msal
import requests

from app.config import settings

logger = logging.getLogger("dsio.graph_files")

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

#: Délai des appels Graph. Un téléchargement de classeur peut être lent, mais
#: une tâche planifiée bloquée indéfiniment est pire qu'une tâche en échec.
_TIMEOUT = 60

#: Dossier projet : « P01 - Cantine », « P06 _ Voix IP ». Même convention que
#: `scripts/import_folder.py`, pour que les deux chemins d'import s'accordent.
_CODE_RE = re.compile(r"^\s*(P\d+)", re.IGNORECASE)

#: Classeurs exploitables. Les fichiers `~$…` sont les verrous temporaires
#: qu'Excel laisse derrière lui : les lire produit une erreur de format.
_EXTENSIONS = (".xlsx", ".xlsm")


class GraphFilesError(RuntimeError):
    """Échec d'un appel Graph — le message est destiné aux journaux."""


@dataclass(frozen=True)
class DriveItem:
    """Élément d'une bibliothèque de documents."""

    id: str
    name: str
    is_folder: bool
    size: int
    last_modified: datetime | None
    web_url: str | None


@dataclass(frozen=True)
class ProjectFolder:
    """Dossier projet et son classeur de suivi."""

    code: str
    name: str
    folder: DriveItem
    workbook: DriveItem | None

    @property
    def has_workbook(self) -> bool:
        return self.workbook is not None


def is_configured() -> bool:
    """Vrai si l'accès fichiers peut être tenté."""
    if not settings.sharepoint_configured:
        return False
    try:
        _ = settings.azure_client_id, settings.azure_tenant_id, settings.azure_client_secret
    except Exception:
        return False
    return True


def configuration_explanation() -> str:
    """Phrase affichable expliquant pourquoi l'intégration est inactive."""
    manquants: list[str] = []
    if not settings.sharepoint_hostname:
        manquants.append("SHAREPOINT_HOSTNAME")
    for nom in ("AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_CLIENT_SECRET"):
        try:
            _ = getattr(settings, nom.lower())
        except Exception:
            manquants.append(nom)
    if manquants:
        return (
            "Intégration SharePoint inactive. Variables manquantes : "
            + ", ".join(manquants)
            + ". La permission d'application `Sites.Selected` doit également "
            "être accordée sur le site dans Entra ID."
        )
    return f"Intégration SharePoint active sur {settings.sharepoint_hostname}."


_app_cache: msal.ConfidentialClientApplication | None = None
#: Identifiants résolus une fois par process : ils ne changent pas.
_site_id: str | None = None
_drive_id: str | None = None


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
    token = result.get("access_token")
    if not token:
        raise GraphFilesError(
            f"Jeton Graph refusé ({result.get('error')}) : "
            f"{str(result.get('error_description', ''))[:200]}"
        )
    return token


def _get(url: str, *, stream: bool = False) -> requests.Response:
    reponse = requests.get(
        url if url.startswith("http") else f"{GRAPH_ROOT}{url}",
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=_TIMEOUT,
        stream=stream,
    )
    if reponse.status_code == 403:
        raise GraphFilesError(
            "Accès refusé par Graph. La permission d'application sur les "
            "fichiers (`Sites.Selected` accordée sur ce site, ou "
            "`Sites.Read.All`) n'est probablement pas en place."
        )
    if reponse.status_code == 404:
        raise GraphFilesError(f"Ressource SharePoint introuvable : {url}")
    if not reponse.ok:
        raise GraphFilesError(
            f"Graph a répondu {reponse.status_code} sur {url} : {reponse.text[:200]}"
        )
    return reponse


def _parse_date(valeur: str | None) -> datetime | None:
    if not valeur:
        return None
    try:
        return datetime.fromisoformat(valeur.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_item(donnees: dict) -> DriveItem:
    return DriveItem(
        id=donnees["id"],
        name=donnees.get("name", ""),
        is_folder="folder" in donnees,
        size=int(donnees.get("size") or 0),
        last_modified=_parse_date(donnees.get("lastModifiedDateTime")),
        web_url=donnees.get("webUrl"),
    )


def resolve_site_id() -> str:
    """Identifiant du site SharePoint, résolu depuis l'hôte et le chemin."""
    global _site_id
    if _site_id is not None:
        return _site_id

    hote = settings.sharepoint_hostname
    chemin = settings.sharepoint_site_path.strip("/")
    url = f"/sites/{hote}:/{chemin}" if chemin else f"/sites/{hote}"
    _site_id = _get(url).json()["id"]
    logger.info("Site SharePoint résolu : %s", _site_id)
    return _site_id


def resolve_drive_id() -> str:
    """Bibliothèque de documents à parcourir."""
    global _drive_id
    if _drive_id is not None:
        return _drive_id

    site = resolve_site_id()
    voulue = settings.sharepoint_drive_name
    if voulue:
        drives = _get(f"/sites/{site}/drives").json().get("value", [])
        for drive in drives:
            if drive.get("name", "").lower() == voulue.lower():
                _drive_id = drive["id"]
                break
        if _drive_id is None:
            disponibles = ", ".join(d.get("name", "?") for d in drives) or "aucune"
            raise GraphFilesError(
                f"Bibliothèque « {voulue} » introuvable. Disponibles : {disponibles}."
            )
    else:
        _drive_id = _get(f"/sites/{site}/drive").json()["id"]

    logger.info("Bibliothèque SharePoint résolue : %s", _drive_id)
    return _drive_id


def list_children(folder_path: str = "") -> list[DriveItem]:
    """Contenu d'un dossier, chemin relatif à la racine de la bibliothèque."""
    drive = resolve_drive_id()
    chemin = folder_path.strip("/")
    if chemin:
        url = f"/drives/{drive}/root:/{quote(chemin)}:/children"
    else:
        url = f"/drives/{drive}/root/children"

    elements: list[DriveItem] = []
    # Graph pagine à 200 éléments : sans suivre `@odata.nextLink`, un dossier
    # bien rempli serait tronqué en silence.
    while url:
        charge = _get(url).json()
        elements.extend(_to_item(entree) for entree in charge.get("value", []))
        url = charge.get("@odata.nextLink", "")
    return elements


def download_item(item: DriveItem, destination: Path) -> Path:
    """Télécharge un fichier vers `destination`."""
    drive = resolve_drive_id()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _get(f"/drives/{drive}/items/{item.id}/content", stream=True) as reponse:
        with destination.open("wb") as sortie:
            for morceau in reponse.iter_content(chunk_size=64 * 1024):
                if morceau:
                    sortie.write(morceau)
    return destination


def _classeur(enfants: list[DriveItem]) -> DriveItem | None:
    """Classeur de suivi d'un dossier projet.

    Même règle que l'import local : on écarte les verrous temporaires d'Excel
    et, en cas de fichiers multiples, on retient le plus récemment modifié.
    """
    candidats = [
        item
        for item in enfants
        if not item.is_folder
        and not item.name.startswith("~$")
        and item.name.lower().endswith(_EXTENSIONS)
    ]
    if not candidats:
        return None
    return max(candidats, key=lambda item: item.last_modified or datetime.min)


def _libelle(nom_dossier: str) -> str:
    """« P01 - Projet Cantine » -> « Projet Cantine »."""
    reste = re.sub(r"^\s*P\d+\s*[-_]\s*", "", nom_dossier, flags=re.IGNORECASE)
    return reste.strip() or nom_dossier.strip()


def list_project_folders(root_path: str | None = None) -> list[ProjectFolder]:
    """Dossiers projet de la racine, avec leur classeur de suivi."""
    racine = (root_path if root_path is not None else settings.sharepoint_root_folder_path).strip("/")
    dossiers: list[ProjectFolder] = []

    for enfant in list_children(racine):
        if not enfant.is_folder:
            continue
        correspondance = _CODE_RE.match(enfant.name)
        if not correspondance:
            # Un dossier hors convention n'est pas une erreur : la racine
            # contient aussi des archives et des documents transverses.
            logger.debug("Dossier ignoré (hors convention) : %s", enfant.name)
            continue

        chemin = f"{racine}/{enfant.name}" if racine else enfant.name
        dossiers.append(
            ProjectFolder(
                code=correspondance.group(1).upper(),
                name=_libelle(enfant.name),
                folder=enfant,
                workbook=_classeur(list_children(chemin)),
            )
        )

    dossiers.sort(key=lambda item: item.code)
    return dossiers


def check_access() -> dict:
    """Diagnostic : la configuration permet-elle réellement de lire ?"""
    if not is_configured():
        return {"ok": False, "detail": configuration_explanation()}
    try:
        site = resolve_site_id()
        drive = resolve_drive_id()
        dossiers = list_project_folders()
    except GraphFilesError as erreur:
        return {"ok": False, "detail": str(erreur)}

    return {
        "ok": True,
        "site_id": site,
        "drive_id": drive,
        "root_path": settings.sharepoint_root_folder_path,
        "project_folders": len(dossiers),
        "with_workbook": sum(1 for d in dossiers if d.has_workbook),
        "sample": [
            {"code": d.code, "name": d.name, "workbook": d.workbook.name if d.workbook else None}
            for d in dossiers[:5]
        ],
    }
