"""
Rapprochement des noms de responsables.

Les cas viennent des données réelles : les classeurs de suivi contenaient
« AndryII » et « Andry II » (82 actions à elles deux), « AndryI » et
« Andry I », et trois graphies de « Xavier-Hassen ». Chacune avait sa propre
fiche responsable, donc une charge de travail éclatée dans les rapports.
"""
import pytest

from app.services.names import _SEPARATEURS, dedupe, normalize_key, split_personnes


@pytest.mark.parametrize(
    "variante",
    ["AndryII", "Andry II", "andry II", "andryII", "ANDRY  II", "Andry-II", " Andry II "],
)
def test_variantes_d_un_meme_nom(variante):
    assert normalize_key(variante) == "andryii"


@pytest.mark.parametrize(
    "variante", ["Xavier -Hassen", "Xavier-Hassen", "Xavier- Hassen", "xavier hassen"]
)
def test_variantes_avec_ponctuation(variante):
    assert normalize_key(variante) == "xavierhassen"


def test_personnes_distinctes_non_confondues():
    """Le chiffre romain distingue deux personnes : la normalisation retire la
    ponctuation, jamais les lettres ni les chiffres."""
    assert normalize_key("Andry I") != normalize_key("Andry II")
    assert normalize_key("DPEN") != normalize_key("DPENN")
    assert normalize_key("Manoa") != normalize_key("Manda")


def test_accents_ignores():
    assert normalize_key("Hénintsoa") == normalize_key("Henintsoa")
    assert normalize_key("Noëlson") == normalize_key("Noelson")


def test_valeurs_vides():
    assert normalize_key(None) == ""
    assert normalize_key("   ") == ""
    assert normalize_key("---") == ""


def test_dedupe_conserve_la_premiere_graphie():
    """La fiche garde le nom tel qu'il a été saisi : la clé sert à comparer,
    pas à réécrire."""
    assert dedupe(["Xavier", "xavier", "XAVIER"]) == ["Xavier"]
    assert dedupe(["Andry II", "AndryII"]) == ["Andry II"]


def test_dedupe_conserve_l_ordre():
    assert dedupe(["Meylis", "Xavier", "Meylis", "Hassen"]) == ["Meylis", "Xavier", "Hassen"]


def test_dedupe_ecarte_les_vides():
    assert dedupe(["Meylis", "", "   ", None, "-"]) == ["Meylis"]


# --- Découpage des cellules à plusieurs personnes --------------------------

@pytest.mark.parametrize(
    "libelle,attendu",
    [
        ("Meylis-Hassen", ["Meylis", "Hassen"]),
        ("Xavier -Hassen", ["Xavier", "Hassen"]),
        ("Xavier-Hassen-MDC", ["Xavier", "Hassen", "MDC"]),
        ("Manda, Xavier", ["Manda", "Xavier"]),
        ("Meylis / Xavier", ["Meylis", "Xavier"]),
        ("Xavier et Manda", ["Xavier", "Manda"]),
        ("AndryII & Teknet", ["AndryII", "Teknet"]),
    ],
)
def test_split_personnes(libelle, attendu):
    assert split_personnes(libelle) == attendu


@pytest.mark.parametrize("nom", ["Teknet", "Peter", "Theodula", "Anatole", "Etienne"])
def test_le_et_ne_coupe_pas_a_l_interieur_d_un_nom(nom):
    """Régression : la limite de mot autour de « et » avait été perdue, et
    « Teknet » se retrouvait coupé en « Tekn »."""
    assert split_personnes(nom) == [nom]


def test_pas_de_caractere_de_controle_dans_le_motif():
    r"""Régression : un caractère backspace (0x08) s'était substitué à la
    séquence `\b` du motif — les deux s'écrivent pareil dans une chaîne Python
    non brute. Le motif ne coupait alors plus jamais sur « et », en silence."""
    assert r"\bet\b" in _SEPARATEURS.pattern
    assert not any(ord(c) < 32 for c in _SEPARATEURS.pattern)


def test_libelles_qui_ne_sont_pas_des_listes():
    """« ou » marque une incertitude, pas une seconde personne."""
    assert split_personnes("Teknet ou autre") == ["Teknet ou autre"]
    assert split_personnes("Equipe projet") == ["Equipe projet"]
    assert split_personnes("Andry II") == ["Andry II"]


def test_split_dedoublonne():
    assert split_personnes("Xavier / xavier") == ["Xavier"]
    assert split_personnes("") == []
