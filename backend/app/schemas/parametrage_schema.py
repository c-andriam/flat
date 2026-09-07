"""Schémas des référentiels et des gabarits — le paramétrage de l'application."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from app.models.gabarit import GabaritEntite
from app.models.referentiel import ReferentielType
from app.services.gabarits import TypeChamp
from app.schemas.project_schema import ActionCreate, PartialUpdate, ProjectCreate

#: Une couleur de badge, en hexadécimal court ou long.
_COULEUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

#: Le code sert d'identifiant stable : on le restreint à ce qui reste lisible
#: dans une URL et dans un fichier de configuration.
_CODE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _valider_couleur(valeur: str | None) -> str | None:
    if valeur is None:
        return None
    valeur = valeur.strip()
    if not valeur:
        return None
    if not _COULEUR.match(valeur):
        raise ValueError(
            f"Couleur invalide : {valeur!r}. Attendu un hexadécimal, « #1F4E9C »."
        )
    return valeur.lower()


def _valider_code(valeur: str) -> str:
    valeur = valeur.strip().lower()
    if not _CODE.match(valeur):
        raise ValueError(
            f"Code invalide : {valeur!r}. Minuscules, chiffres, tiret et "
            "souligné seulement, en commençant par une lettre ou un chiffre."
        )
    return valeur


# ---------------------------------------------------------------------------
# Référentiels
# ---------------------------------------------------------------------------

class ReferentielBase(BaseModel):
    label: str = Field(
        ..., min_length=1, max_length=255, description="Libellé affiché à l'utilisateur."
    )
    description: str | None = Field(
        None, description="Précision facultative, affichée en aide de saisie."
    )
    color: str | None = Field(
        None, description="Couleur du badge en hexadécimal, ex. `#1F4E9C`."
    )
    position: int = Field(
        0,
        ge=0,
        description=(
            "Ordre d'affichage. L'ordre alphabétique ne convient pas à une "
            "liste métier : « Critique » doit précéder « Faible »."
        ),
    )
    parent_id: uuid.UUID | None = Field(
        None, description="Valeur parente, pour les listes à deux niveaux."
    )
    attributs: dict | None = Field(
        None,
        description=(
            "Propriétés propres à la valeur : `{\"capacite\": 12}` pour une "
            "salle. Réservé à ce qui n'a de sens que pour ce type de liste."
        ),
    )

    _couleur = field_validator("color")(_valider_couleur)


class ReferentielCreate(ReferentielBase):
    model_config = ConfigDict(extra="forbid")

    type: ReferentielType = Field(..., description="Liste à laquelle la valeur appartient.")
    code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description=(
            "Identifiant stable, insensible au renommage. C'est lui qu'un "
            "gabarit référence : renommer « Infra » en « Infrastructure » ne "
            "doit pas casser ce qui s'y référait."
        ),
    )

    _code = field_validator("code")(_valider_code)


class ReferentielUpdate(PartialUpdate):
    label: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    color: str | None = None
    position: int | None = Field(None, ge=0)
    parent_id: uuid.UUID | None = None
    attributs: dict | None = None
    is_active: bool | None = Field(
        None,
        description=(
            "Désactiver plutôt que supprimer : une valeur retirée reste "
            "référencée par les objets passés. Inactive, elle disparaît des "
            "formulaires mais reste lisible sur l'historique."
        ),
    )

    # Ni `type` ni `code` : déplacer une valeur d'une liste à l'autre, ou
    # renommer son identifiant, romprait les rattachements existants sans
    # qu'aucun d'eux ne le signale. Créer une nouvelle valeur est explicite.

    _couleur = field_validator("color")(_valider_couleur)


class ReferentielOut(ReferentielBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    code: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ReferentielListeOut(BaseModel):
    """Une liste administrable et ses valeurs."""

    type: ReferentielType
    label: str = Field(..., description="Nom de la liste, ex. « Salles de réunion ».")
    values: list[ReferentielOut]


# ---------------------------------------------------------------------------
# Gabarits
# ---------------------------------------------------------------------------

class GabaritActionBase(BaseModel):
    """Une action que le gabarit crée avec le projet.

    Les contraintes reprennent celles de `ActionCreate` : responsable de
    suivi, échéance et au moins un réalisateur. Elles sont vérifiées ici, à
    l'enregistrement du gabarit, plutôt qu'à son utilisation — sinon un
    gabarit incomplet serait accepté puis ferait échouer chaque création de
    projet, à un moment où l'utilisateur n'a plus la main sur la cause.
    """

    description: str = Field(..., min_length=1, description="Intitulé de l'action à créer.")
    position: int = Field(0, ge=0, description="Ordre de création.")
    phase: str | None = Field(None, max_length=10)
    resp_suivi: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description=(
            "Responsable du suivi. Obligatoire : sans lui, l'action créée ne "
            "déclencherait aucune relance."
        ),
    )
    responsable_names: list[str] = Field(
        ...,
        min_length=1,
        description="Responsables de réalisation, résolus en fiches à la création.",
    )
    delai_jours: int = Field(
        ...,
        ge=0,
        le=3650,
        description=(
            "Échéance en jours à partir de la création du projet. Obligatoire, "
            "une action sans date cible n'étant pas exploitable ; relative, "
            "une date absolue étant périmée dès le deuxième usage du gabarit."
        ),
    )
    charges_hj: float | None = Field(None, ge=0.0)
    categorie_id: uuid.UUID | None = Field(
        None, description="Catégorie d'action, prise dans le référentiel."
    )


class GabaritActionOut(GabaritActionBase):
    """Lecture d'une action type.

    Les contraintes sont relâchées en sortie : une ligne enregistrée avant que
    la règle n'existe doit rester lisible, quitte à être signalée. Refuser de
    l'afficher empêcherait précisément de la corriger.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resp_suivi: str | None = None
    responsable_names: list[str] = Field(default_factory=list)
    delai_jours: int | None = None

    @field_validator("responsable_names", mode="before")
    @classmethod
    def _depuis_texte(cls, valeur):
        # Stocké en une colonne texte séparée par des virgules, au format même
        # de la cellule Excel dont ces noms sortent d'habitude.
        if isinstance(valeur, str):
            return [nom.strip() for nom in valeur.split(",") if nom.strip()]
        return valeur or []


class GabaritBase(BaseModel):
    nom: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    valeurs: dict = Field(
        default_factory=dict,
        description=(
            "Valeurs préremplies, par nom de champ du schéma de création. "
            "Elles restent modifiables à la saisie, sauf mention contraire "
            "dans `politique`."
        ),
    )
    politique: dict = Field(
        default_factory=dict,
        description=(
            "Contraintes de saisie, par champ : "
            '`{"resp_suivi": {"obligatoire": true}}`. Clés acceptées : '
            "`obligatoire`, `masque`, `verrouille`."
        ),
    )
    is_active: bool = True
    is_default: bool = Field(
        False,
        description=(
            "Proposé d'office à l'ouverture du formulaire. Au plus un par "
            "entité ; en désigner un second déplace la marque."
        ),
    )
    position: int = Field(0, ge=0)


class GabaritCreate(GabaritBase):
    model_config = ConfigDict(extra="forbid")

    entite: GabaritEntite = Field(..., description="Ce que le gabarit sait créer.")
    actions: list[GabaritActionBase] = Field(
        default_factory=list,
        description=(
            "Actions à instancier avec le projet. N'a de sens que sur un "
            "gabarit de projet — c'est la partie qui fait réellement gagner "
            "du temps."
        ),
    )


class GabaritUpdate(PartialUpdate):
    nom: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    valeurs: dict | None = None
    politique: dict | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    position: int | None = Field(None, ge=0)
    actions: list[GabaritActionBase] | None = Field(
        None,
        description=(
            "Remplace intégralement la liste des actions type. Absent, la "
            "liste actuelle est conservée."
        ),
    )

    # `entite` est absent volontairement : les champs autorisés en dépendent,
    # et basculer un gabarit de projet en gabarit d'action rendrait ses
    # valeurs et sa politique invalides d'un coup.


class GabaritOut(GabaritBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entite: GabaritEntite
    actions: list[GabaritActionOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ChampGabaritOut(BaseModel):
    """Un champ préremplissable, avec de quoi construire le bon contrôle."""

    nom: str
    type: TypeChamp = Field(
        ...,
        description=(
            "Nature du champ telle que l'interface doit la présenter. Déduite "
            "de l'annotation du schéma de création, jamais déclarée à part."
        ),
    )
    description: str | None = None
    referentiel: ReferentielType | None = Field(
        None,
        description=(
            "Liste dans laquelle puiser, quand le champ désigne une valeur de "
            "référentiel. L'interface affiche alors une liste déroulante "
            "plutôt qu'un champ de saisie d'identifiant."
        ),
    )


class ChampsGabaritOut(BaseModel):
    """Ce qu'un gabarit d'une entité donnée peut préremplir ou contraindre.

    Exposé pour que l'écran d'administration propose les bons champs et les
    bons contrôles au lieu de les recopier — une liste dupliquée dans
    l'interface aurait divergé au premier champ ajouté au schéma de création.
    """

    entite: GabaritEntite
    champs: list[ChampGabaritOut]
    cles_politique: list[str]


# ---------------------------------------------------------------------------
# Création à partir d'un gabarit
# ---------------------------------------------------------------------------
#
# Un gabarit peut fournir des champs que la création exige — le chemin du
# classeur source d'un projet, l'échéance d'une action. La saisie doit donc
# pouvoir les omettre, et la validation stricte n'intervenir qu'*après* la
# fusion. D'où ces variantes où tout est facultatif : elles ne contrôlent que
# la forme, le résultat fusionné étant ensuite validé par `ProjectCreate` ou
# `ActionCreate`, avec l'intégralité de leurs règles.


def _tout_optionnel(nom: str, base: type[BaseModel]) -> type[BaseModel]:
    """Copie d'un schéma de création dont tous les champs sont facultatifs.

    Engendrée plutôt que recopiée : une liste de champs écrite à la main aurait
    divergé du schéma réel au premier champ ajouté, et la création à partir
    d'un gabarit aurait alors silencieusement ignoré ce champ.
    """
    champs = {
        cle: (
            info.annotation | None,
            Field(None, description=info.description),
        )
        for cle, info in base.model_fields.items()
    }
    return create_model(
        nom,
        # Même exigence qu'à la création directe : un champ mal orthographié
        # doit produire un 422 qui le nomme, pas être ignoré en silence.
        __config__=ConfigDict(extra="forbid"),
        **champs,
    )


#: Saisie d'un projet créé depuis un gabarit. `code` reste en pratique
#: indispensable — il identifie le projet et aucun gabarit ne le fournit — mais
#: c'est `ProjectCreate` qui le réclamera, avec son propre message.
ProjetDepuisGabarit = _tout_optionnel("ProjetDepuisGabarit", ProjectCreate)

#: Saisie d'une action créée depuis un gabarit.
ActionDepuisGabarit = _tout_optionnel("ActionDepuisGabarit", ActionCreate)
