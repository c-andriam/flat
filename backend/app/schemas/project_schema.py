import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.project import ActionStatus, SyncStatus

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


class PartialUpdate(BaseModel):
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
    spi: float = Field(0.0, description="Schedule Performance Index.")
    otd: float = Field(0.0, description="On-Time Delivery score.")
    deadline: date | None = Field(None, description="Date d'échéance cible de l'action.")
    date_realisation: date | None = Field(None, description="Date réelle de complétion.")
    charges_hj: float | None = Field(None, description="Charges estimées en Homme/Jour.")
    commentaire: str | None = Field(None, description="Commentaire libre.")


class ActionCreate(ActionBase):
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
        cleaned: list[str] = []
        vus: set[str] = set()
        for name in values:
            name = (name or "").strip()
            if name and name.casefold() not in vus:
                vus.add(name.casefold())
                cleaned.append(name)
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
    spi: float | None = Field(None, ge=0.0, description="Nouveau SPI.")
    otd: float | None = Field(None, ge=0.0, description="Nouveau OTD.")
    deadline: date | None = Field(None, description="Nouvelle échéance.")
    date_realisation: date | None = Field(None, description="Nouvelle date de réalisation.")
    charges_hj: float | None = Field(None, ge=0.0, description="Nouvelle estimation Homme/Jour.")
    commentaire: str | None = Field(None, description="Nouveau commentaire.")
    # Typé en énumération : la liste des valeurs acceptées apparaît dans Swagger
    # et une faute de frappe est rejetée en 422 par Pydantic, pas plus loin.
    status: ActionStatus | None = Field(
        None, description="Forcer le statut (sinon recalculé automatiquement)."
    )
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
        cleaned: list[str] = []
        vus: set[str] = set()
        for name in values:
            name = (name or "").strip()
            if name and name.casefold() not in vus:
                vus.add(name.casefold())
                cleaned.append(name)
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
