import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.project import ActionStatus, SyncStatus
from app.services.names import contient_separateur_fort, dedupe, split_personnes

# Validation d'email volontairement permissive : elle rejette les fautes de
# frappe évidentes (« jean.dupont@ », « trimeta.mg ») sans embarquer la
# dépendance `email-validator` ni refuser un domaine interne exotique.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def _validate_email(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _EMAIL_RE.match(value):
        raise ValueError(f"Adresse email invalide : {value!r}")
    return value.lower()


#: Champs entièrement dérivés de l'avancement et des dates. Les accepter en
#: écriture laisserait croire à une saisie possible, alors que le prochain
#: enregistrement les recalculerait — une valeur qui ne « tient » pas est pire
#: qu'une valeur refusée.
CHAMPS_CALCULES = {
    "spi": "il suit l'avancement (`progress`)",
    "otd": "il vaut 100 si l'action est livrée au plus tard à son échéance, 0 sinon",
    "numero": "il est généré à partir du code projet et de la phase",
    "created_at": "il est horodaté par le serveur",
    "updated_at": "il est horodaté par le serveur",
}


class RefuseChampsCalcules(BaseModel):
    """Rejette explicitement les champs dérivés, avec le motif.

    `extra="forbid"` seul renverrait « Extra inputs are not permitted », sans
    dire pourquoi ce champ précis est refusé ni comment obtenir l'effet voulu.
    """

    @model_validator(mode="before")
    @classmethod
    def _refuser_les_champs_calcules(cls, data):
        if not isinstance(data, dict):
            return data
        interdits = [c for c in CHAMPS_CALCULES if c in data]
        if interdits:
            details = "; ".join(f"`{c}` : {CHAMPS_CALCULES[c]}" for c in interdits)
            raise ValueError(
                f"Champ(s) calculé(s) automatiquement, non modifiable(s) — {details}. "
                "Modifier `progress`, `deadline` ou `date_realisation` pour les faire évoluer."
            )
        return data


class PartialUpdate(RefuseChampsCalcules):
    """Socle des charges utiles de modification (PUT).

    `extra="forbid"` : un champ mal orthographié (`progres` au lieu de
    `progress`) était auparavant ignoré en silence — l'appel renvoyait 200 et
    rien n'avait changé. Il produit maintenant un 422 qui nomme le champ fautif.

    La charge utile doit aussi contenir au moins un champ : une requête vide
    n'exprime aucune intention de modification, et c'est presque toujours un
    bug côté client.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _au_moins_un_champ(self):
        if not self.model_fields_set:
            raise ValueError(
                "Charge utile vide : indiquer au moins un champ à modifier."
            )
        return self


# --- Responsable ---

class ResponsableBase(BaseModel):
    display_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Nom complet ou trigramme tel qu'il apparaît dans le fichier Excel.",
    )

    @field_validator("display_name")
    @classmethod
    def _strip_display_name(cls, v: str) -> str:
        # Les noms viennent d'Excel : «  Meylis » et « Meylis » créeraient deux
        # responsables distincts, donc deux relances au même agent.
        v = v.strip()
        if not v:
            raise ValueError("Le nom affiché ne peut pas être vide.")
        return v


class ResponsableCreate(ResponsableBase):
    email: str | None = Field(
        None, description="Adresse email (optionnel, déclenche le flag is_mapped)."
    )

    _check_email = field_validator("email")(_validate_email)


class ResponsableUpdate(PartialUpdate):
    display_name: str | None = Field(
        None, max_length=255, description="Renommer le responsable."
    )
    email: str | None = Field(
        None,
        description=(
            "Adresse email. Renseignée, elle marque le responsable comme mappé ; "
            "envoyer explicitement `null` le démappe."
        ),
    )

    _check_email = field_validator("email")(_validate_email)


class ResponsableOut(ResponsableBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None = None
    is_mapped: bool


# --- Action ---

class ActionBase(BaseModel):
    description: str = Field(..., min_length=1, description="Description ou titre de l'action.")
    resp_suivi: str | None = Field(None, max_length=255, description="Nom du responsable du suivi.")
    progress: float = Field(0.0, ge=0.0, le=100.0, description="Pourcentage d'avancement de 0 à 100.")
    deadline: date | None = Field(None, description="Date d'échéance cible de l'action.")
    date_realisation: date | None = Field(None, description="Date réelle de complétion.")
    charges_hj: float | None = Field(None, description="Charges estimées en Homme/Jour.")
    commentaire: str | None = Field(None, description="Commentaire libre.")


class ActionCreate(ActionBase, RefuseChampsCalcules):
    model_config = ConfigDict(extra="forbid")

    # Contraintes strictes à la création : un suivi sans responsable ni
    # échéance n'est pas exploitable. ActionOut reste nullable pour ne pas
    # casser la lecture des actions existantes créées avant cette règle.
    resp_suivi: str = Field(
        ..., min_length=1, max_length=255,
        description="Nom du responsable du suivi (obligatoire à la création).",
    )
    deadline: date = Field(..., description="Date d'échéance (obligatoire à la création).")
    project_id: uuid.UUID = Field(..., description="Identifiant du projet parent.")
    responsable_names: list[str] = Field(
        ..., min_length=1, description="Liste des noms des responsables de réalisation."
    )
    phase: str | None = Field(
        None, max_length=10,
        description="Phase de l'action, obligatoire si le projet a has_phases=True.",
    )

    @field_validator("responsable_names")
    @classmethod
    def _clean_names(cls, values: list[str]) -> list[str]:
        # Dédoublonnage insensible à la casse : « Xavier » et « xavier »
        # désignent la même personne, et deux fiches responsable signifient
        # deux relances pour la même action.
        # Seuls les séparateurs francs sont refusés. Le tiret ne l'est plus :
        # « Jean-Pierre » est un prénom, et trancher entre lui et
        # « karine - hassen » demande de consulter les emails connus — ce
        # qu'un validateur de schéma, exécuté avant tout accès aux données,
        # ne peut pas faire. L'arbitrage a lieu à la lecture des classeurs,
        # seul endroit où un libellé composite arrive vraiment.
        composites = [n for n in values if n and contient_separateur_fort(n)]
        if composites:
            # Ne pas découper en silence : la liste est explicite côté API, une
            # entrée composite est une erreur d'appel. Les classeurs Excel, eux,
            # n'ont qu'une cellule et sont découpés à l'import.
            exemple = split_personnes(composites[0])
            raise ValueError(
                f"Un responsable par entrée : {composites[0]!r} en contient "
                f"plusieurs. Envoyer {exemple} plutôt qu'une chaîne combinée."
            )
        cleaned = dedupe(values)
        if not cleaned:
            raise ValueError("Au moins un responsable de réalisation est requis.")
        return cleaned


class ActionUpdate(PartialUpdate):
    description: str | None = Field(None, min_length=1, description="Nouvelle description de l'action.")
    resp_suivi: str | None = Field(None, max_length=255, description="Nouveau responsable de suivi.")
    progress: float | None = Field(
        None, ge=0.0, le=100.0,
        description="Nouvel avancement (0 à 100). À 100, le statut bascule à TERMINE.",
    )
    deadline: date | None = Field(None, description="Nouvelle échéance.")
    date_realisation: date | None = Field(None, description="Nouvelle date de réalisation.")
    charges_hj: float | None = Field(None, ge=0.0, description="Nouvelle estimation Homme/Jour.")
    commentaire: str | None = Field(None, description="Nouveau commentaire.")
    # Seuls les statuts qui portent une information non déductible restent
    # imposables. `termine` et `en_retard` se déduisent de l'avancement et de
    # l'échéance : les forcer produirait une ligne incohérente (« terminée » à
    # 40 %) que le prochain enregistrement corrigerait de toute façon.
    status: ActionStatus | None = Field(
        None,
        description=(
            "Forcer le statut. Seuls `a_faire`, `en_cours` et `bloque` sont "
            "acceptés — `termine` s'obtient en passant `progress` à 100, et "
            "`en_retard` découle de l'échéance."
        ),
    )

    @field_validator("status")
    @classmethod
    def _statut_imposable(cls, v):
        if v in (ActionStatus.TERMINE, ActionStatus.EN_RETARD):
            raise ValueError(
                f"Le statut `{v.value}` est déduit automatiquement et ne peut pas "
                "être imposé : passer `progress` à 100 pour terminer une action, "
                "et l'échéance détermine le retard."
            )
        return v
    phase: str | None = Field(None, max_length=10, description="Changer la phase de l'action.")
    responsable_names: list[str] | None = Field(
        None,
        min_length=1,
        description=(
            "Remplace la liste des responsables de réalisation. Absent, la "
            "liste actuelle est conservée."
        ),
    )

    @field_validator("responsable_names")
    @classmethod
    def _clean_names(cls, values: list[str] | None) -> list[str] | None:
        # Même nettoyage qu'à la création : les noms viennent d'une saisie
        # manuelle, et « Meylis » et « Meylis  » créeraient deux fiches
        # responsable, donc deux relances pour la même action.
        if values is None:
            return None
        # Seuls les séparateurs francs sont refusés. Le tiret ne l'est plus :
        # « Jean-Pierre » est un prénom, et trancher entre lui et
        # « karine - hassen » demande de consulter les emails connus — ce
        # qu'un validateur de schéma, exécuté avant tout accès aux données,
        # ne peut pas faire. L'arbitrage a lieu à la lecture des classeurs,
        # seul endroit où un libellé composite arrive vraiment.
        composites = [n for n in values if n and contient_separateur_fort(n)]
        if composites:
            # Ne pas découper en silence : la liste est explicite côté API, une
            # entrée composite est une erreur d'appel. Les classeurs Excel, eux,
            # n'ont qu'une cellule et sont découpés à l'import.
            exemple = split_personnes(composites[0])
            raise ValueError(
                f"Un responsable par entrée : {composites[0]!r} en contient "
                f"plusieurs. Envoyer {exemple} plutôt qu'une chaîne combinée."
            )
        cleaned = dedupe(values)
        if not cleaned:
            raise ValueError("Au moins un responsable de réalisation est requis.")
        return cleaned


class ActionOut(ActionBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero: str
    phase: str | None = None
    project_id: uuid.UUID
    status: ActionStatus
    # Calculés par le serveur, jamais acceptés en écriture.
    spi: float = Field(..., description="Schedule Performance Index — suit l'avancement.")
    otd: float = Field(
        ...,
        description=(
            "Taux de respect de la deadline : 100 si l'action est livrée au "
            "plus tard à son échéance, 0 sinon ou tant qu'elle n'est pas livrée."
        ),
    )
    responsables: list[ResponsableOut] = []
    created_at: datetime
    updated_at: datetime


# --- Project ---

class ProjectBase(BaseModel):
    code: str = Field(
        ..., min_length=1, max_length=50, description="Code unique du projet (ex: P01)."
    )
    name: str = Field(..., min_length=1, max_length=255, description="Nom complet du projet.")
    source_file_path: str = Field(
        ..., min_length=1, max_length=1024,
        description="Chemin SharePoint ou système du fichier Excel source.",
    )
    has_phases: bool = Field(
        False, description="Si vrai, les actions nécessitent le champ `phase` (ex: P01-02-05)."
    )

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Le code projet ne peut pas être vide.")
        return v


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(PartialUpdate):
    name: str | None = Field(None, min_length=1, max_length=255, description="Nom complet du projet.")
    source_file_path: str | None = Field(
        None, min_length=1, max_length=1024,
        description="Chemin SharePoint ou système du fichier Excel source.",
    )
    is_active: bool | None = Field(
        None, description="Désactiver le projet pour le masquer sans le supprimer."
    )
    has_phases: bool | None = Field(
        None,
        description=(
            "Activer/désactiver la gestion par phases. Refusé (409) si le "
            "projet porte déjà des actions."
        ),
    )


class ProjectOut(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    created_at: datetime
    last_synced_at: datetime | None = None


class ProjectWithActionsOut(ProjectOut):
    actions: list[ActionOut] = []


# --- Logs (lecture seule) ---

class SyncLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None = None
    status: SyncStatus
    files_processed: int
    error_message: str | None = None


class RelanceLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    responsable_id: uuid.UUID
    sent_at: datetime
    email_status: str
