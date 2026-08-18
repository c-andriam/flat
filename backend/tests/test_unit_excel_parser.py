"""
Tests unitaires du parseur Excel — ils ne nécessitent ni base de données ni
stack démarrée, contrairement au reste de la suite qui est intégralement en
intégration HTTP.
"""
from datetime import date

import openpyxl
import pytest

from app.services.excel_parser import (
    _parse_responsables,
    _safe_date,
    normalize_numero,
    parse_excel_file,
    split_phase,
)


def test_normalize_numero_tolere_les_espaces():
    # Les fichiers réels contiennent « Po1 -02- 05 » (saisie manuelle).
    assert normalize_numero("P01 -02- 05") == "P01-02-05"
    assert normalize_numero("  P01-01  ") == "P01-01"
    assert normalize_numero(None) == ""


def test_split_phase():
    assert split_phase("P01-02-05") == "02"
    assert split_phase("P01-05") is None


def test_parse_responsables_separateurs():
    assert _parse_responsables("Meylis / Xavier") == ["Meylis", "Xavier"]
    assert _parse_responsables("Andry II, Xavier") == ["Andry II", "Xavier"]
    assert _parse_responsables("Meylis") == ["Meylis"]
    assert _parse_responsables(None) == []


def test_parse_responsables_dedoublonne():
    assert _parse_responsables("Xavier / Xavier") == ["Xavier"]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("11/6/2023", date(2023, 11, 6)),
        ("2026-06-18", date(2026, 6, 18)),
        ("", None),
        ("pas une date", None),
    ],
)
def test_safe_date(value, expected):
    assert _safe_date(value) == expected


def _build_workbook(path, *, percent_format=True):
    wb = openpyxl.Workbook()
    ws = wb.active

    # Bloc de titre : les fichiers réels ne commencent pas le tableau ligne 1.
    ws["B1"] = "P01 - Cantine"
    ws["B2"] = "Equipe Projet"
    ws["B4"] = "Projets"
    ws["C4"] = "Actions"

    ws["B5"] = "P01 -02- 01"
    ws["C5"] = "Recueillir les besoins"
    ws["D5"] = "Meylis / Xavier"
    ws["E5"] = "Hassen"
    ws["F5"] = 1.0 if percent_format else 100.0
    ws["G5"] = 1.0 if percent_format else 100.0
    ws["H5"] = 0.0
    ws["I5"] = date(2026, 2, 10)
    ws["J5"] = date(2026, 2, 12)
    ws["K5"] = 1.5
    ws["L5"] = "RAS"
    if percent_format:
        for col in ("F", "G", "H"):
            ws[f"{col}5"].number_format = "0%"

    ws["B6"] = "P01-02-02"
    ws["C6"] = "Rediger le cahier des charges"
    ws["D6"] = "Meylis"
    ws["F6"] = 0.5 if percent_format else 50.0
    ws["I6"] = date(2026, 12, 31)
    if percent_format:
        ws["F6"].number_format = "0%"

    # Ligne de total en bas de tableau, à ignorer.
    ws["B8"] = "P01 - Cantine"
    ws["C8"] = ""

    wb.save(path)


def test_parse_excel_normalise_les_pourcentages(tmp_path):
    """Une cellule affichée « 100 % » vaut 1.0 dans le fichier.

    Sans normalisation, une action terminée arrivait en base à progress=1.0,
    soit 1 % : elle restait comptée comme à faire et déclenchait des relances.
    """
    path = tmp_path / "p01.xlsx"
    _build_workbook(path, percent_format=True)

    actions = parse_excel_file(path)

    assert len(actions) == 2
    first = actions[0]
    assert first["numero"] == "P01-02-01"
    assert first["phase"] == "02"
    assert first["progress"] == 100.0
    assert first["spi"] == 100.0
    assert first["responsable_names"] == ["Meylis", "Xavier"]
    assert first["resp_suivi"] == "Hassen"
    assert first["deadline"] == date(2026, 2, 10)
    assert first["date_realisation"] == date(2026, 2, 12)
    assert first["charges_hj"] == 1.5
    assert actions[1]["progress"] == 50.0


def test_parse_excel_valeurs_deja_en_centiemes(tmp_path):
    path = tmp_path / "p01_brut.xlsx"
    _build_workbook(path, percent_format=False)

    actions = parse_excel_file(path)

    assert actions[0]["progress"] == 100.0
    assert actions[1]["progress"] == 50.0


def test_parse_excel_detecte_le_debut_du_tableau(tmp_path):
    """Le tableau commence ligne 5 : l'ancien `data_start_row=2` codé en dur
    aurait tenté de lire le bloc de titre comme des actions."""
    path = tmp_path / "p01.xlsx"
    _build_workbook(path)

    actions = parse_excel_file(path)

    numeros = [a["numero"] for a in actions]
    assert numeros == ["P01-02-01", "P01-02-02"]


def test_parse_excel_refuse_un_format_non_supporte(tmp_path):
    path = tmp_path / "fichier.csv"
    path.write_text("a,b,c", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_excel_file(path)


def test_parse_excel_fichier_absent(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_excel_file(tmp_path / "inexistant.xlsx")
