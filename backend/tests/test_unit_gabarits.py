"""
Tests unitaires de l'application d'un gabarit : champs autorisés, politique de
saisie et actions type. Aucune base de données ni stack démarrée n'est
nécessaire — le service ne fait aucun accès aux données, c'est précisément ce
qui le rend testable ici.
"""
import os
from datetime import date

import pytest

os.environ.setdefault("POSTGRES_USER", "unit-test")
os.environ.setdefault("POSTGRES_PASSWORD", "unit-test")
os.environ.setdefault("POSTGRES_DB", "unit-test")
os.environ.setdefault("POSTGRES_HOST", "localhost")

import pydantic  # noqa: E402

from app.models.gabarit import Gabarit, GabaritAction, GabaritEntite  # noqa: E402
from app.schemas.parametrage_schema import (  # noqa: E402
    ActionDepuisGabarit,
    GabaritCreate,
    ProjetDepuisGabarit,
    ReferentielCreate,
    ReferentielUpdate,
)
from app.services.gabarits import (  # noqa: E402
    CHAMP_DELAI,
    CLES_POLITIQUE,
    GabaritError,
    TypeChamp,
    appliquer,
    champs_autorises,
    decrire_champs,
    payloads_actions,
    valider_politique,
    valider_valeurs,
)

LUNDI = date(2026, 9, 7)


def _gabarit(entite=GabaritEntite.PROJET, *, valeurs=None, politique=None, actions=()):
    """Gabarit en mémoire — jamais rattaché à une session."""
    gabarit = Gabarit(
        entite=entite,
        nom="Projet infrastructure",
        valeurs=valeurs or {},
        politique=politique or {},
    )
    gabarit.actions = list(actions)
    return gabarit


# --- Champs autorisés ------------------------------------------------------

def test_champs_lus_sur_le_schema_de_creation():
    """Une liste recopiée aurait divergé au premier champ ajouté, et le
    gabarit se serait mis à porter des valeurs que la création ignore."""
    champs = champs_autorises(GabaritEntite.PROJET)
    assert "name" in champs
    assert "source_file_path" in champs
    assert "type_id" in champs


def test_le_code_projet_n_est_pas_preremplissable():
    """Le préremplir ferait échouer en conflit toutes les créations sauf la
    première : le code identifie le projet."""
    assert "code" not in champs_autorises(GabaritEntite.PROJET)


def test_une_action_porte_un_delai_et_non_une_date():
    """Une échéance absolue dans un gabarit serait périmée dès le deuxième
    usage, et `ActionCreate` exige pourtant une échéance."""
    champs = champs_autorises(GabaritEntite.ACTION)
    assert CHAMP_DELAI in champs
    assert "deadline" not in champs


# --- Types de champ exposés à l'interface ----------------------------------

def _type_de(entite, nom):
    return next(c["type"] for c in decrire_champs(entite) if c["nom"] == nom)


def test_une_liste_n_est_pas_un_champ_texte():
    """`get_args` répond aussi sur `list[str]`, dont le premier argument est
    `str` : déballer sans distinguer les unions faisait passer la liste des
    responsables pour un champ texte, et l'écran d'administration proposait
    une ligne de saisie au lieu d'une liste."""
    assert _type_de(GabaritEntite.ACTION, "responsable_names") is TypeChamp.LISTE_TEXTE


def test_optionnel_deballe_vers_le_type_utile():
    """`str | None` doit donner « texte », pas « union »."""
    assert _type_de(GabaritEntite.ACTION, "resp_suivi") is TypeChamp.TEXTE


def test_types_scalaires_reconnus():
    assert _type_de(GabaritEntite.PROJET, "has_phases") is TypeChamp.BOOLEEN
    assert _type_de(GabaritEntite.ACTION, "progress") is TypeChamp.NOMBRE
    assert _type_de(GabaritEntite.ACTION, "date_realisation") is TypeChamp.DATE


def test_champ_long_distingue_du_champ_court():
    """Une description tient sur un paragraphe, un nom de phase sur une ligne."""
    assert _type_de(GabaritEntite.ACTION, "description") is TypeChamp.TEXTE_LONG
    assert _type_de(GabaritEntite.ACTION, "phase") is TypeChamp.TEXTE


def test_champ_de_referentiel_nomme_sa_liste():
    """Sans cette correspondance, l'interface afficherait une saisie d'UUID
    là où elle doit afficher une liste déroulante."""
    champ = next(
        c for c in decrire_champs(GabaritEntite.ACTION) if c["nom"] == "categorie_id"
    )
    assert champ["type"] is TypeChamp.REFERENTIEL
    assert champ["referentiel"] == "categorie_action"


def test_le_projet_n_est_pas_un_referentiel():
    """`project_id` est un UUID lui aussi, mais il désigne un projet : la
    liste déroulante à afficher n'est pas la même."""
    assert _type_de(GabaritEntite.ACTION, "project_id") is TypeChamp.PROJET


def test_le_delai_est_decrit_meme_s_il_est_virtuel():
    """Il ne figure pas au schéma de création : sans description explicite, il
    serait absent de l'écran d'administration."""
    champ = next(
        c for c in decrire_champs(GabaritEntite.ACTION) if c["nom"] == CHAMP_DELAI
    )
    assert champ["type"] is TypeChamp.NOMBRE
    assert champ["description"]


def test_tous_les_champs_autorises_sont_decrits():
    for entite in GabaritEntite:
        assert {c["nom"] for c in decrire_champs(entite)} == champs_autorises(entite)


# --- Validation du contenu d'un gabarit ------------------------------------

def test_champ_inconnu_refuse_a_l_enregistrement():
    """Sans ce contrôle, `respsuivi` pour `resp_suivi` serait accepté et
    resterait sans effet à chaque utilisation, sans rien signaler."""
    with pytest.raises(GabaritError, match="respsuivi"):
        valider_valeurs(GabaritEntite.ACTION, {"respsuivi": "Xavier"})


def test_message_d_erreur_liste_les_champs_acceptes():
    with pytest.raises(GabaritError, match="Champs acceptés"):
        valider_valeurs(GabaritEntite.PROJET, {"inexistant": 1})


def test_politique_sur_champ_inconnu_refusee():
    with pytest.raises(GabaritError, match="politique"):
        valider_politique(GabaritEntite.PROJET, {"inexistant": {"obligatoire": True}})


def test_regle_inconnue_refusee():
    with pytest.raises(GabaritError, match="Règle inconnue"):
        valider_politique(GabaritEntite.PROJET, {"name": {"requis": True}})


def test_regle_doit_etre_un_objet():
    with pytest.raises(GabaritError, match="doit être un objet"):
        valider_politique(GabaritEntite.PROJET, {"name": True})


def test_regles_fausses_retirees():
    """Une politique ne doit contenir que ce qu'elle impose : sinon
    l'interface doit distinguer « pas de règle » de « règle à faux »."""
    assert valider_politique(GabaritEntite.PROJET, {"name": {"obligatoire": False}}) == {}


def test_cles_de_politique_exposees():
    assert CLES_POLITIQUE == {"obligatoire", "masque", "verrouille"}


# --- Application : fusion --------------------------------------------------

def test_sans_gabarit_la_saisie_passe_telle_quelle():
    assert appliquer(None, {"name": "Refonte"}) == {"name": "Refonte"}


def test_le_gabarit_complete_ce_qui_manque():
    gabarit = _gabarit(valeurs={"source_file_path": "/suivi/infra.xlsx", "has_phases": True})
    resultat = appliquer(gabarit, {"code": "P42", "name": "Refonte"})
    assert resultat["source_file_path"] == "/suivi/infra.xlsx"
    assert resultat["has_phases"] is True
    assert resultat["name"] == "Refonte"


def test_la_saisie_prime_sur_le_gabarit():
    """Une valeur préremplie est une proposition, pas une contrainte — sauf
    politique contraire."""
    gabarit = _gabarit(valeurs={"name": "Projet type"})
    assert appliquer(gabarit, {"name": "Le vrai nom"})["name"] == "Le vrai nom"


def test_un_champ_transmis_a_null_est_un_effacement_explicite():
    """La distinction entre « absent » et « null » compte : le second est une
    intention, il ne doit pas être écrasé par le gabarit."""
    gabarit = _gabarit(valeurs={"description": "Par défaut"})
    assert appliquer(gabarit, {"description": None})["description"] is None


# --- Application : politique ----------------------------------------------

def test_champ_obligatoire_manquant_refuse():
    gabarit = _gabarit(politique={"source_file_path": {"obligatoire": True}})
    with pytest.raises(GabaritError, match="source_file_path"):
        appliquer(gabarit, {"code": "P42", "name": "Refonte"})


def test_champ_obligatoire_satisfait_par_le_gabarit():
    """C'est le cas d'usage principal : le gabarit fournit la valeur *et*
    l'exige, la saisie n'a rien à faire."""
    gabarit = _gabarit(
        valeurs={"source_file_path": "/suivi/infra.xlsx"},
        politique={"source_file_path": {"obligatoire": True}},
    )
    assert appliquer(gabarit, {"code": "P42"})["source_file_path"] == "/suivi/infra.xlsx"


def test_chaine_vide_ne_satisfait_pas_une_obligation():
    gabarit = _gabarit(politique={"name": {"obligatoire": True}})
    with pytest.raises(GabaritError, match="name"):
        appliquer(gabarit, {"name": "   "})


def test_liste_vide_ne_satisfait_pas_une_obligation():
    gabarit = _gabarit(
        GabaritEntite.ACTION, politique={"responsable_names": {"obligatoire": True}}
    )
    with pytest.raises(GabaritError, match="responsable_names"):
        appliquer(gabarit, {"responsable_names": []})


def test_champ_verrouille_ne_peut_pas_etre_contredit():
    """L'interface grise déjà ces champs : un appel qui en envoie une autre
    valeur est un défaut d'appel, pas une intention."""
    gabarit = _gabarit(
        valeurs={"has_phases": True}, politique={"has_phases": {"verrouille": True}}
    )
    with pytest.raises(GabaritError, match="imposé"):
        appliquer(gabarit, {"has_phases": False})


def test_champ_verrouille_accepte_la_meme_valeur():
    """Un formulaire qui renvoie tous ses champs, y compris grisés, ne doit
    pas être refusé pour autant."""
    gabarit = _gabarit(
        valeurs={"has_phases": True}, politique={"has_phases": {"verrouille": True}}
    )
    assert appliquer(gabarit, {"has_phases": True})["has_phases"] is True


def test_champ_masque_est_impose_comme_un_champ_verrouille():
    """Un champ que l'utilisateur ne voit pas ne peut pas être saisi par lui."""
    gabarit = _gabarit(
        valeurs={"has_phases": True}, politique={"has_phases": {"masque": True}}
    )
    with pytest.raises(GabaritError, match="imposé"):
        appliquer(gabarit, {"has_phases": False})


# --- Application : échéance relative --------------------------------------

def test_le_delai_devient_une_date_a_la_creation():
    gabarit = _gabarit(GabaritEntite.ACTION, valeurs={CHAMP_DELAI: 14})
    resultat = appliquer(gabarit, {"description": "Chiffrage"}, today=LUNDI)
    assert resultat["deadline"] == date(2026, 9, 21)
    # Le champ virtuel ne doit pas se retrouver dans la charge de création :
    # `ActionCreate` le refuserait.
    assert CHAMP_DELAI not in resultat


def test_delai_nul_donne_le_jour_meme():
    gabarit = _gabarit(GabaritEntite.ACTION, valeurs={CHAMP_DELAI: 0})
    assert appliquer(gabarit, {}, today=LUNDI)["deadline"] == LUNDI


def test_delai_obligatoire_verifie_sur_la_date_resultante():
    """La politique porte sur `delai_jours`, la valeur sur `deadline` : sans
    cette correspondance, l'obligation serait toujours en défaut."""
    gabarit = _gabarit(
        GabaritEntite.ACTION,
        valeurs={CHAMP_DELAI: 7},
        politique={CHAMP_DELAI: {"obligatoire": True}},
    )
    assert appliquer(gabarit, {}, today=LUNDI)["deadline"] == date(2026, 9, 14)


def test_delai_obligatoire_mais_absent_refuse():
    gabarit = _gabarit(
        GabaritEntite.ACTION, politique={CHAMP_DELAI: {"obligatoire": True}}
    )
    with pytest.raises(GabaritError, match=CHAMP_DELAI):
        appliquer(gabarit, {}, today=LUNDI)


# --- Actions type ----------------------------------------------------------

def test_actions_type_instanciees_dans_l_ordre():
    gabarit = _gabarit(
        actions=[
            GabaritAction(position=0, description="Cadrage", delai_jours=7),
            GabaritAction(position=1, description="Chiffrage", delai_jours=14),
        ]
    )
    payloads = payloads_actions(gabarit, today=LUNDI)
    assert [p["description"] for p in payloads] == ["Cadrage", "Chiffrage"]
    assert payloads[0]["deadline"] == date(2026, 9, 14)
    assert payloads[1]["deadline"] == date(2026, 9, 21)


def test_action_type_sans_delai_reste_sans_echeance():
    gabarit = _gabarit(actions=[GabaritAction(position=0, description="Recette")])
    assert payloads_actions(gabarit, today=LUNDI)[0]["deadline"] is None


def test_responsables_d_une_action_type_decoupes():
    """Stockés au format même de la cellule Excel dont ils sortent."""
    gabarit = _gabarit(
        actions=[
            GabaritAction(
                position=0, description="Cadrage", responsable_names="Andry, Xavier"
            )
        ]
    )
    assert payloads_actions(gabarit)[0]["responsable_names"] == ["Andry", "Xavier"]


def test_aucun_responsable_donne_une_liste_vide():
    gabarit = _gabarit(actions=[GabaritAction(position=0, description="Cadrage")])
    assert payloads_actions(gabarit)[0]["responsable_names"] == []


# --- Schémas de saisie -----------------------------------------------------

def test_saisie_depuis_gabarit_entierement_facultative():
    """Le gabarit peut fournir des champs que la création exige : la saisie
    doit pouvoir les omettre."""
    assert ProjetDepuisGabarit().model_dump(exclude_unset=True) == {}


def test_saisie_depuis_gabarit_refuse_un_champ_inconnu():
    with pytest.raises(pydantic.ValidationError):
        ActionDepuisGabarit(descriptionn="faute de frappe")


def test_saisie_depuis_gabarit_couvre_le_schema_de_creation():
    """Les deux schémas sont engendrés, pas recopiés : ils ne peuvent pas
    diverger de la création."""
    from app.schemas.project_schema import ActionCreate, ProjectCreate

    assert set(ProjetDepuisGabarit.model_fields) == set(ProjectCreate.model_fields)
    assert set(ActionDepuisGabarit.model_fields) == set(ActionCreate.model_fields)


# --- Schémas de référentiel ------------------------------------------------

def test_code_normalise_en_minuscules():
    valeur = ReferentielCreate(type="type_projet", code="  Infra_2  ", label="Infra")
    assert valeur.code == "infra_2"


def test_code_avec_espace_refuse():
    with pytest.raises(pydantic.ValidationError, match="Code invalide"):
        ReferentielCreate(type="type_projet", code="type infra", label="Infra")


def test_couleur_invalide_refusee():
    with pytest.raises(pydantic.ValidationError, match="Couleur invalide"):
        ReferentielCreate(type="salle", code="a1", label="Salle A", color="bleu")


def test_couleur_hexadecimale_normalisee():
    valeur = ReferentielCreate(type="salle", code="a1", label="Salle A", color="#1F4E9C")
    assert valeur.color == "#1f4e9c"


def test_type_de_liste_ferme():
    """Ajouter une valeur est un acte d'administration ; ajouter un type est
    un développement, puisqu'il faut du code pour le consommer."""
    with pytest.raises(pydantic.ValidationError):
        ReferentielCreate(type="liste_inventee", code="x", label="X")


def test_le_type_et_le_code_ne_sont_pas_modifiables():
    """Les déplacer romprait les rattachements sans qu'aucun ne le signale."""
    with pytest.raises(pydantic.ValidationError):
        ReferentielUpdate(code="autre")
    with pytest.raises(pydantic.ValidationError):
        ReferentielUpdate(type="salle")


def test_modification_vide_refusee():
    with pytest.raises(pydantic.ValidationError):
        ReferentielUpdate()


# --- Schéma de gabarit -----------------------------------------------------

def test_gabarit_accepte_des_actions_type():
    gabarit = GabaritCreate(
        entite="projet",
        nom="Projet infra",
        actions=[
            {
                "description": "Cadrage",
                "delai_jours": 7,
                "resp_suivi": "Xavier",
                "responsable_names": ["Andry"],
            }
        ],
    )
    assert gabarit.actions[0].delai_jours == 7


def test_action_type_sans_echeance_refusee_a_l_enregistrement():
    """`ActionCreate` exige une échéance : accepter le gabarit ferait échouer
    chaque création de projet, à un moment où l'utilisateur n'a plus la main
    sur la cause."""
    with pytest.raises(pydantic.ValidationError, match="delai_jours"):
        GabaritCreate(
            entite="projet",
            nom="Projet infra",
            actions=[
                {
                    "description": "Cadrage",
                    "resp_suivi": "Xavier",
                    "responsable_names": ["Andry"],
                }
            ],
        )


def test_action_type_sans_responsable_refusee():
    with pytest.raises(pydantic.ValidationError, match="responsable_names"):
        GabaritCreate(
            entite="projet",
            nom="Projet infra",
            actions=[
                {
                    "description": "Cadrage",
                    "delai_jours": 7,
                    "resp_suivi": "Xavier",
                    "responsable_names": [],
                }
            ],
        )


def test_action_type_sans_responsable_de_suivi_refusee():
    """Sans lui, l'action créée ne déclencherait aucune relance."""
    with pytest.raises(pydantic.ValidationError, match="resp_suivi"):
        GabaritCreate(
            entite="projet",
            nom="Projet infra",
            actions=[
                {
                    "description": "Cadrage",
                    "delai_jours": 7,
                    "responsable_names": ["Andry"],
                }
            ],
        )


def test_gabarit_refuse_un_champ_inconnu():
    with pytest.raises(pydantic.ValidationError):
        GabaritCreate(entite="projet", nom="X", inconnu=1)
