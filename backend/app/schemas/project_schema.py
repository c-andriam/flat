import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# --- Responsable ---

class ResponsableBase(BaseModel):
    display_name: str = Field(..., description="Nom complet ou trigramme tel qu'il apparaît dans le fichier Excel.")


class ResponsableCreate(ResponsableBase):
    email: str | None = Field(None, description="Adresse email (optionnel, déclenche le flag is_mapped).")


class ResponsableUpdate(BaseModel):
    email: str | None = Field(None, description="Adresse email. Déclenche le flag is_mapped s'il est renseigné.")


class ResponsableOut(ResponsableBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None = None
    is_mapped: bool


# --- Action ---

class ActionBase(BaseModel):
    description: str = Field(..., description="Description ou titre de l'action.")
    resp_suivi: str | None = Field(None, description="Nom du responsable du suivi.")
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
    resp_suivi: str = Field(..., description="Nom du responsable du suivi (obligatoire à la création).")
    deadline: date = Field(..., description="Date d'échéance (obligatoire à la création).")
    project_id: uuid.UUID = Field(..., description="Identifiant du projet parent.")
    responsable_names: list[str] = Field(..., min_length=1, description="Liste des noms des responsables de réalisation.")
    phase: str | None = Field(None, description="Phase de l'action, obligatoire si le projet a has_phases=True.")


class ActionUpdate(BaseModel):
    description: str | None = Field(None, description="Nouvelle description de l'action.")
    resp_suivi: str | None = Field(None, description="Nouveau responsable de suivi.")
    progress: float | None = Field(None, ge=0.0, le=100.0, description="Nouvel avancement (0 à 100). À 100, le statut bascule à TERMINE.")
    spi: float | None = Field(None, description="Nouveau SPI.")
    otd: float | None = Field(None, description="Nouveau OTD.")
    deadline: date | None = Field(None, description="Nouvelle échéance.")
    date_realisation: date | None = Field(None, description="Nouvelle date de réalisation.")
    charges_hj: float | None = Field(None, description="Nouvelle estimation Homme/Jour.")
    commentaire: str | None = Field(None, description="Nouveau commentaire.")
    status: str | None = Field(None, description="Forcer le statut (ex: EN_COURS, TERMINE, EN_RETARD, ANNULE).")
    phase: str | None = Field(None, description="Changer la phase de l'action.")


class ActionOut(ActionBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero: str
    phase: str | None = None
    project_id: uuid.UUID
    status: str
    responsables: list[ResponsableOut] = []
    created_at: datetime
    updated_at: datetime


# --- Project ---

class ProjectBase(BaseModel):
    code: str = Field(..., description="Code unique du projet (ex: PRJ-001).")
    name: str = Field(..., description="Nom complet du projet.")
    source_file_path: str = Field(..., description="Chemin SharePoint ou système du fichier Excel source.")
    has_phases: bool = Field(False, description="Si vrai, les actions nécessitent le champ `phase` (ex: P01-01-05).")


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, description="Nom complet du projet.")
    source_file_path: str | None = Field(None, description="Chemin SharePoint ou système du fichier Excel source.")
    is_active: bool | None = Field(None, description="Désactiver le projet pour le masquer sans le supprimer.")
    has_phases: bool | None = Field(None, description="Activer/désactiver la gestion par phases.")


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
    id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    files_processed: int
    error_message: str | None = None


class RelanceLogOut(BaseModel):
    id: uuid.UUID
    responsable_id: uuid.UUID
    sent_at: datetime
    email_status: str
