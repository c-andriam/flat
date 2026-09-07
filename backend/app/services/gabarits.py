"""
Application d'un gabarit à une création : valeurs, politique, actions type.

Aucun accès à la base ici. Le module reçoit un gabarit et ce que l'appelant a
saisi, et renvoie le dictionnaire de création résultant — ou refuse en
expliquant pourquoi. C'est ce qui permet aux routes de projet et d'action de
partager exactement les mêmes règles, et de les tester sans infrastructure.

Les champs autorisés ne sont pas listés à la main : ils sont lus sur les
schémas de création eux-mêmes. Une liste recopiée aurait divergé au premier
champ ajouté, et un gabarit se serait alors mis à porter des valeurs que la
création ignore en silence.
"""

import uuid
from datetime import date, timedelta
from enum import Enum
from types import UnionType
from typing import Union, get_args, get_origin

from app.models.gabarit import Gabarit, GabaritEntite
from app.models.referentiel import ReferentielType
from app.services.action_rules import today_utc

#: Clés reconnues dans la politique d'un champ.
#:
#: `masque` vaut `verrouille` du point de vue du serveur : un champ que
#: l'utilisateur ne voit pas ne peut pas non plus être saisi par lui. La
#: distinction n'existe que pour l'affichage — masqué disparaît du formulaire,
#: verrouillé y reste visible mais grisé, ce qui n'est pas la même
#: information pour celui qui remplit.
CLES_POLITIQUE = frozenset({"obligatoire", "masque", "verrouille"})

#: Champ virtuel accepté dans les valeurs d'un gabarit d'action : l'échéance
#: exprimée en jours à partir d'aujourd'hui. Une `deadline` absolue dans un
#: gabarit serait périmée dès le deuxième usage, et `ActionCreate` exige
#: pourtant une échéance — sans ce champ, aucun gabarit d'action ne serait
#: utilisable plus d'une journée.
CHAMP_DELAI = "delai_jours"

#: Champs qu'un gabarit ne doit pas préremplir, bien qu'ils existent au
#: schéma. `code` identifie un projet de façon unique : le préremplir ferait
#: échouer en conflit toutes les créations sauf la première.
_CHAMPS_EXCLUS: dict[GabaritEntite, frozenset[str]] = {
    GabaritEntite.PROJET: frozenset({"code"}),
    GabaritEntite.ACTION: frozenset(),
}


class GabaritError(ValueError):
    """Gabarit mal formé, ou saisie qui contredit sa politique."""


def _schema_creation(entite: GabaritEntite):
    # Import différé : `schemas.project_schema` importe des services, et une
    # importation au niveau du module refermerait le cycle.
    from app.schemas.project_schema import ActionCreate, ProjectCreate

    return ProjectCreate if entite is GabaritEntite.PROJET else ActionCreate


def champs_autorises(entite: GabaritEntite) -> frozenset[str]:
    """Champs qu'un gabarit de cette entité peut préremplir ou contraindre."""
    champs = set(_schema_creation(entite).model_fields) - _CHAMPS_EXCLUS[entite]
    if entite is GabaritEntite.ACTION:
        # L'échéance relative remplace l'absolue, elle ne s'y ajoute pas :
        # accepter les deux laisserait un gabarit se contredire.
        champs.discard("deadline")
        champs.add(CHAMP_DELAI)
    return frozenset(champs)


#: Champs qui désignent une valeur de référentiel, et laquelle. Sans cette
#: correspondance, l'écran d'administration afficherait un champ de saisie
#: d'UUID là où il doit afficher une liste déroulante.
_REFERENTIEL_DU_CHAMP: dict[str, ReferentielType] = {
    "type_id": ReferentielType.TYPE_PROJET,
    "categorie_id": ReferentielType.CATEGORIE_ACTION,
}


class TypeChamp(str, Enum):
    """Nature d'un champ, telle que l'interface doit la présenter."""

    TEXTE = "texte"
    TEXTE_LONG = "texte_long"
    NOMBRE = "nombre"
    BOOLEEN = "booleen"
    DATE = "date"
    LISTE_TEXTE = "liste_texte"
    #: Une valeur de référentiel : l'interface affiche la liste déroulante
    #: correspondante plutôt qu'un champ libre.
    REFERENTIEL = "referentiel"
    #: Un projet existant : l'interface affiche la liste des projets.
    PROJET = "projet"


#: Champs dont le contenu est un paragraphe, pas une ligne.
_CHAMPS_LONGS = frozenset({"description", "commentaire"})


def _sans_optionnel(annotation):
    """Retire le `None` d'un `X | None`, et rien d'autre.

    Le déballage doit être réservé aux unions : `get_args` répond aussi sur
    `list[str]`, dont le premier argument est `str`. Déballer sans distinction
    aurait fait passer une liste de noms pour un champ texte.
    """
    if get_origin(annotation) not in (Union, UnionType):
        return annotation
    membres = [a for a in get_args(annotation) if a is not type(None)]
    return membres[0] if len(membres) == 1 else annotation


def _type_du_champ(nom: str, annotation) -> TypeChamp:
    """Déduit le type d'affichage de l'annotation du schéma de création.

    Lu sur le schéma plutôt que déclaré à part : une table de correspondance
    tenue à la main se serait désynchronisée au premier champ ajouté, et
    l'écran d'administration aurait proposé le mauvais contrôle — un champ
    texte pour une case à cocher, par exemple, dont la valeur « true » aurait
    ensuite été refusée à chaque création.
    """
    if nom in _REFERENTIEL_DU_CHAMP:
        return TypeChamp.REFERENTIEL
    if nom == "project_id":
        return TypeChamp.PROJET

    reel = _sans_optionnel(annotation)

    # Le test sur l'origine précède ceux sur le type : `list[str]` n'est pas
    # `str`, et déballer une liste comme on déballe un `str | None` ferait
    # passer « responsable_names » pour un champ texte.
    if get_origin(reel) in (list, set, tuple):
        return TypeChamp.LISTE_TEXTE
    if reel is bool:
        return TypeChamp.BOOLEEN
    if reel in (int, float):
        return TypeChamp.NOMBRE
    if reel is date:
        return TypeChamp.DATE
    if reel is uuid.UUID:
        return TypeChamp.REFERENTIEL
    if nom in _CHAMPS_LONGS:
        return TypeChamp.TEXTE_LONG
    return TypeChamp.TEXTE


def decrire_champs(entite: GabaritEntite) -> list[dict]:
    """Champs préremplissables, avec de quoi construire le bon contrôle."""
    schema = _schema_creation(entite)
    autorises = champs_autorises(entite)

    decrits = []
    for nom in sorted(autorises):
        info = schema.model_fields.get(nom)
        if nom == CHAMP_DELAI:
            decrits.append(
                {
                    "nom": nom,
                    "type": TypeChamp.NOMBRE,
                    "description": (
                        "Échéance en jours à partir de la création. Une date "
                        "absolue serait périmée dès le deuxième usage."
                    ),
                    "referentiel": None,
                }
            )
            continue
        decrits.append(
            {
                "nom": nom,
                "type": _type_du_champ(nom, info.annotation if info else None),
                "description": info.description if info else None,
                "referentiel": (
                    _REFERENTIEL_DU_CHAMP[nom].value
                    if nom in _REFERENTIEL_DU_CHAMP
                    else None
                ),
            }
        )
    return decrits


def valider_valeurs(entite: GabaritEntite, valeurs: dict | None) -> dict:
    """Refuse les champs qu'une création n'accepte pas.

    Sans ce contrôle, une faute de frappe dans un gabarit — `respsuivi` pour
    `resp_suivi` — serait acceptée à l'enregistrement et resterait sans effet
    à chaque utilisation, sans que rien ne le signale.
    """
    valeurs = valeurs or {}
    autorises = champs_autorises(entite)
    inconnus = sorted(set(valeurs) - autorises)
    if inconnus:
        raise GabaritError(
            f"Champ(s) inconnu(s) pour un gabarit de {entite.value} : "
            f"{', '.join(inconnus)}. Champs acceptés : "
            f"{', '.join(sorted(autorises))}."
        )
    return dict(valeurs)


def valider_politique(entite: GabaritEntite, politique: dict | None) -> dict:
    """Même contrôle sur la politique, plus la forme de chaque règle."""
    politique = politique or {}
    autorises = champs_autorises(entite)

    inconnus = sorted(set(politique) - autorises)
    if inconnus:
        raise GabaritError(
            f"Champ(s) inconnu(s) dans la politique : {', '.join(inconnus)}."
        )

    propre: dict[str, dict] = {}
    for champ, regle in politique.items():
        if not isinstance(regle, dict):
            raise GabaritError(
                f"La règle du champ « {champ} » doit être un objet, par exemple "
                '{"obligatoire": true}.'
            )
        cles_inconnues = sorted(set(regle) - CLES_POLITIQUE)
        if cles_inconnues:
            raise GabaritError(
                f"Règle inconnue sur « {champ} » : {', '.join(cles_inconnues)}. "
                f"Attendu : {', '.join(sorted(CLES_POLITIQUE))}."
            )
        # Les règles fausses sont retirées plutôt que stockées : une politique
        # ne doit contenir que ce qu'elle impose réellement, sinon l'interface
        # doit distinguer « pas de règle » de « règle à faux » sans que la
        # différence ait un sens.
        retenue = {cle: bool(valeur) for cle, valeur in regle.items() if valeur}
        if retenue:
            propre[champ] = retenue
    return propre


def _est_impose(regle: dict) -> bool:
    """Le champ est-il soustrait à la saisie de l'utilisateur ?"""
    return bool(regle.get("verrouille") or regle.get("masque"))


def _est_vide(valeur) -> bool:
    if valeur is None:
        return True
    if isinstance(valeur, str):
        return not valeur.strip()
    if isinstance(valeur, (list, tuple, set, dict)):
        return not valeur
    return False


def appliquer(
    gabarit: Gabarit | None, fournis: dict, *, today: date | None = None
) -> dict:
    """Fusionne un gabarit et la saisie de l'utilisateur.

    Args:
        gabarit: le gabarit choisi, ou None — la création reste possible sans.
        fournis: les champs réellement transmis par l'appelant, c'est-à-dire
            `model_dump(exclude_unset=True)`. La distinction compte : un champ
            absent prend la valeur du gabarit, un champ transmis à `null` est
            un effacement explicite qu'on ne doit pas écraser.

    Returns:
        Le dictionnaire de création à passer au schéma.

    Raises:
        GabaritError: un champ obligatoire reste vide, ou un champ imposé a
            été forcé à une autre valeur.
    """
    if gabarit is None:
        return dict(fournis)

    valeurs = dict(gabarit.valeurs or {})
    politique = dict(gabarit.politique or {})

    # L'échéance relative devient une date à l'instant de la création, jamais
    # à l'enregistrement du gabarit.
    if CHAMP_DELAI in valeurs:
        delai = valeurs.pop(CHAMP_DELAI)
        if delai is not None:
            valeurs["deadline"] = (today or today_utc()) + timedelta(days=int(delai))

    # Un champ imposé par le gabarit ne peut pas être contredit. On refuse au
    # lieu d'écraser en silence : l'interface grise déjà ces champs, un appel
    # qui en envoie un autre valeur est un défaut d'appel, pas une intention.
    for champ, regle in politique.items():
        if not _est_impose(regle) or champ not in fournis:
            continue
        attendu = valeurs.get("deadline" if champ == CHAMP_DELAI else champ)
        if fournis[champ] != attendu:
            raise GabaritError(
                f"Le champ « {champ} » est imposé par le gabarit "
                f"« {gabarit.nom} » et ne peut pas être modifié."
            )

    resultat = {**valeurs, **fournis}

    manquants = [
        champ
        for champ, regle in politique.items()
        if regle.get("obligatoire")
        and _est_vide(resultat.get("deadline" if champ == CHAMP_DELAI else champ))
    ]
    if manquants:
        raise GabaritError(
            f"Le gabarit « {gabarit.nom} » rend obligatoire(s) : "
            f"{', '.join(sorted(manquants))}."
        )

    return resultat


def payloads_actions(gabarit: Gabarit, *, today: date | None = None) -> list[dict]:
    """Actions à créer avec le projet, dans l'ordre du gabarit.

    Renvoie des dictionnaires plutôt que des objets ORM : la génération du
    numéro d'action et le rattachement des responsables vivent dans le routeur,
    avec leurs propres garde-fous (unicité du numéro, rapprochement des noms).
    Les dupliquer ici aurait créé une deuxième façon de créer une action.
    """
    today = today or today_utc()
    payloads = []
    for modele in gabarit.actions:
        noms = [
            nom.strip()
            for nom in (modele.responsable_names or "").split(",")
            if nom.strip()
        ]
        payloads.append(
            {
                "description": modele.description,
                "phase": modele.phase,
                "resp_suivi": modele.resp_suivi,
                "responsable_names": noms,
                "deadline": (
                    today + timedelta(days=modele.delai_jours)
                    if modele.delai_jours is not None
                    else None
                ),
                "charges_hj": modele.charges_hj,
                "categorie_id": modele.categorie_id,
            }
        )
    return payloads
