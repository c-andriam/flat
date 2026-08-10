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
"""

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl

logger = logging.getLogger("excel-parser")


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convertit une valeur en float, retourne default en cas d'erreur."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_date(value: Any) -> date | None:
    """Convertit une valeur en date, retourne None en cas d'erreur."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return None


def _parse_responsables(value: Any) -> list[str]:
    """Extrait la liste des responsables (séparés par '/' ou ',')."""
    if not value:
        return []
    text = str(value).strip()
    # Séparer par "/" ou ","
    if "/" in text:
        names = text.split("/")
    elif "," in text:
        names = text.split(",")
    else:
        names = [text]
    return [n.strip() for n in names if n.strip()]


def parse_excel_file(
    file_path: str | Path,
    sheet_name: str | None = None,
    header_row: int = 1,
    data_start_row: int = 2,
) -> list[dict]:
    """
    Parse un fichier Excel de suivi et retourne une liste de dictionnaires,
    un par ligne d'action valide.

    Args:
        file_path: Chemin vers le fichier .xlsx
        sheet_name: Nom de la feuille (None = feuille active)
        header_row: Ligne contenant les en-têtes (1-indexed)
        data_start_row: Première ligne de données (1-indexed)

    Returns:
        Liste de dicts avec les clés :
            numero, description, responsable_names, resp_suivi,
            progress, spi, otd, deadline, date_realisation,
            charges_hj, commentaire
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    if not path.suffix.lower() in (".xlsx", ".xlsm"):
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

        actions = []
        skipped = 0

        for row in ws.iter_rows(min_row=data_start_row, values_only=False):
            # Colonnes B(1) à L(11) — index 0-based dans la ligne
            cells = {cell.column_letter: cell.value for cell in row}

            numero = str(cells.get("B", "") or "").strip()
            description = str(cells.get("C", "") or "").strip()

            # Ignorer les lignes vides (pas de numéro ni de description)
            if not numero and not description:
                skipped += 1
                continue

            if not description:
                logger.warning("Ligne %s ignorée : numéro '%s' sans description", row[0].row, numero)
                skipped += 1
                continue

            action = {
                "numero": numero,
                "description": description,
                "responsable_names": _parse_responsables(cells.get("D")),
                "resp_suivi": str(cells.get("E", "") or "").strip() or None,
                "progress": _safe_float(cells.get("F")),
                "spi": _safe_float(cells.get("G")),
                "otd": _safe_float(cells.get("H")),
                "deadline": _safe_date(cells.get("I")),
                "date_realisation": _safe_date(cells.get("J")),
                "charges_hj": _safe_float(cells.get("K"), default=None),
                "commentaire": str(cells.get("L", "") or "").strip() or None,
            }
            actions.append(action)

        logger.info(
            "Fichier '%s' parsé : %d actions extraites, %d lignes ignorées",
            path.name, len(actions), skipped,
        )
        return actions
    finally:
        wb.close()
