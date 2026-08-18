"""
Service de parsing des fichiers Excel de suivi de projets DSIO.

Chaque fichier Excel respecte le format suivant (colonnes B à L) :
    B : Numéro d'action (ex: P01-01 ou P01-01-01)
    C : Description
    D : Responsable(s) réalisation (séparés par « / »)
    E : Responsable suivi
    F : Avancement (%) — 0 à 100
    G : SPI
    H : OTD
    I : Date cible (deadline)
    J : Date réalisation
    K : Charges (h/j)
    L : Commentaire

Les fichiers réels commencent par un bloc de titre (équipe projet, légende
KPI) : la ligne d'en-tête n'est donc pas la ligne 1. Le parseur détecte
automatiquement la première ligne de données à partir du motif des numéros
d'action, au lieu de supposer `data_start_row=2`.
"""

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter

logger = logging.getLogger("excel-parser")

# Un numéro d'action est fait de segments séparés par des tirets, dont le
# dernier est numérique : « P01-01 », « P01-02-05 », « Po1 -02- 05 » dans les
# fichiers saisis à la main.
_NUMERO_RE = re.compile(r"^[A-Za-z0-9]+(?:\s*-\s*[A-Za-z0-9]+)+$")

# Nombre de lignes explorées pour trouver le début du tableau avant d'abandonner.
_MAX_HEADER_SCAN = 60


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    """Convertit une valeur en float, retourne default en cas d'erreur."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _percent(cell) -> float:
    """Avancement en pourcentage sur une échelle 0-100.

    Excel stocke une cellule affichée « 100 % » sous la forme du nombre 1.0 :
    lue telle quelle, une action terminée arrivait en base avec progress=1.0,
    soit 1 % — toutes les actions closes ressortaient donc « à faire », et les
    relances partaient sur des actions déjà livrées.
    """
    value = _safe_float(cell.value if cell is not None else None)
    if value is None:
        return 0.0
    number_format = getattr(cell, "number_format", "") or ""
    if "%" in number_format:
        value *= 100.0
    return max(0.0, min(100.0, value))


def _ratio(cell) -> float:
    """SPI / OTD : mêmes cellules en format pourcentage, même normalisation."""
    value = _safe_float(cell.value if cell is not None else None) or 0.0
    number_format = getattr(cell, "number_format", "") or ""
    if "%" in number_format:
        value *= 100.0
    return value


def _safe_date(value: Any) -> date | None:
    """Convertit une valeur en date, retourne None en cas d'erreur."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Les fichiers mélangent les saisies manuelles : 11/6/2023 (US, tel que
    # rendu par Excel en locale EN) et 11/06/2023 (FR). On tente les deux,
    # ordre US d'abord car c'est ce que produit l'export observé.
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    logger.warning("Date non reconnue, ignorée : %r", text)
    return None


def _parse_responsables(value: Any) -> list[str]:
    """Extrait la liste des responsables (séparés par '/', ',' ou '&')."""
    if not value:
        return []
    text = str(value).strip()
    parts = re.split(r"[/,&]|\bet\b", text)
    names = []
    for part in parts:
        part = part.strip()
        if part and part not in names:
            names.append(part)
    return names


def normalize_numero(raw: Any) -> str:
    """Normalise un numéro d'action saisi à la main.

    « Po1 -02- 05 » et « P01-02-05 » désignent la même action ; sans
    normalisation la resynchronisation créait un doublon à chaque import.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    return "-".join(segment.strip() for segment in text.split("-") if segment.strip())


def split_phase(numero: str) -> str | None:
    """Phase encodée dans un numéro d'action à trois segments (P01-02-05)."""
    segments = numero.split("-")
    if len(segments) >= 3:
        return segments[-2]
    return None


def _cell_value(cells: dict, letter: str):
    cell = cells.get(letter)
    return cell.value if cell is not None else None


def _looks_like_action_row(cells: dict) -> bool:
    numero = normalize_numero(_cell_value(cells, "B"))
    description = str(_cell_value(cells, "C") or "").strip()
    return bool(numero and description and _NUMERO_RE.match(numero))


def _row_cells(row) -> dict:
    """Indexe les cellules d'une ligne par lettre de colonne.

    En mode `read_only`, openpyxl bouche les trous d'une ligne creuse avec des
    `EmptyCell`, qui n'exposent ni `column_letter` ni `column` — l'ancien
    `{cell.column_letter: cell for cell in row}` levait donc un AttributeError
    dès qu'une ligne comportait une cellule vide en début de plage, c'est-à-dire
    sur la quasi-totalité des fichiers réels. On se repère à la position.
    """
    return {get_column_letter(index): cell for index, cell in enumerate(row, start=1)}


def parse_excel_file(
    file_path: str | Path,
    sheet_name: str | None = None,
    data_start_row: int | None = None,
) -> list[dict]:
    """
    Parse un fichier Excel de suivi et retourne une liste de dictionnaires,
    un par ligne d'action valide.

    Args:
        file_path: Chemin vers le fichier .xlsx
        sheet_name: Nom de la feuille (None = feuille active)
        data_start_row: Première ligne de données (1-indexed). None = détection
            automatique du début du tableau.

    Returns:
        Liste de dicts avec les clés :
            numero, phase, description, responsable_names, resp_suivi,
            progress, spi, otd, deadline, date_realisation,
            charges_hj, commentaire
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError(f"Format non supporté : {path.suffix} (attendu .xlsx ou .xlsm)")
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError(f"Impossible de lire le fichier Excel {path.name}: {exc}") from exc

    try:
        if sheet_name is not None:
            if sheet_name not in wb.sheetnames:
                raise ValueError(f"Feuille introuvable: {sheet_name}")
            ws = wb[sheet_name]
        else:
            ws = wb.active

        actions: list[dict] = []
        skipped = 0
        started = data_start_row is not None
        first_data_row = data_start_row

        for row in ws.iter_rows(min_row=data_start_row or 1):
            if not row:
                continue
            cells = _row_cells(row)
            row_index = next(
                (cell.row for cell in row if getattr(cell, "row", None) is not None),
                None,
            )
            if row_index is None:
                continue

            if not started:
                # Bloc de titre / légende : on avance jusqu'à la première
                # ligne qui ressemble vraiment à une action.
                if not _looks_like_action_row(cells):
                    if row_index > _MAX_HEADER_SCAN:
                        break
                    continue
                started = True
                first_data_row = row_index

            numero = normalize_numero(_cell_value(cells, "B"))
            description = str(_cell_value(cells, "C") or "").strip()

            # Ignorer les lignes vides (pas de numéro ni de description)
            if not numero and not description:
                skipped += 1
                continue

            if not numero or not description:
                logger.warning(
                    "Ligne %s ignorée dans '%s' : numéro=%r description=%r incomplets",
                    row_index, path.name, numero, description,
                )
                skipped += 1
                continue

            # Ligne de total ou de sous-total en bas de tableau ("P01 - Cantine")
            if not _NUMERO_RE.match(numero):
                skipped += 1
                continue

            actions.append(
                {
                    "numero": numero,
                    "phase": split_phase(numero),
                    "description": description,
                    "responsable_names": _parse_responsables(_cell_value(cells, "D")),
                    "resp_suivi": str(_cell_value(cells, "E") or "").strip() or None,
                    "progress": _percent(cells.get("F")),
                    "spi": _ratio(cells.get("G")),
                    "otd": _ratio(cells.get("H")),
                    "deadline": _safe_date(_cell_value(cells, "I")),
                    "date_realisation": _safe_date(_cell_value(cells, "J")),
                    "charges_hj": _safe_float(_cell_value(cells, "K"), default=None),
                    "commentaire": str(_cell_value(cells, "L") or "").strip() or None,
                }
            )

        if not actions:
            logger.warning(
                "Aucune action reconnue dans '%s' : vérifier que le tableau "
                "commence bien en colonne B avec des numéros de type P01-01.",
                path.name,
            )
        else:
            logger.info(
                "Fichier '%s' parsé (tableau à partir de la ligne %s) : "
                "%d actions extraites, %d lignes ignorées",
                path.name, first_data_row, len(actions), skipped,
            )
        return actions
    finally:
        wb.close()
