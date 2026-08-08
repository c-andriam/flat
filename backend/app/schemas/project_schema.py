import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# --- Responsable ---

class ResponsableBase(BaseModel):
    display_name: str


class ResponsableCreate(ResponsableBase):
    email: str | None = None


class ResponsableUpdate(BaseModel):
    email: str | None = None


class ResponsableOut(ResponsableBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None = None
    is_mapped: bool


# --- Action ---

class ActionBase(BaseModel):
    description: str
    resp_suivi: str | None = None
    progress: float = Field(0.0, ge=0.0, le=100.0)
    spi: float = 0.0
    otd: float = 0.0
    deadline: date | None = None
    date_realisation: date | None = None  # rempli seulement quand l'action est terminée
    charges_hj: float | None = None
    commentaire: str | None = None


class ActionCreate(ActionBase):
    # Contraintes strictes à la création : un suivi sans responsable ni
    # échéance n'est pas exploitable. ActionOut reste nullable pour ne pas
    # casser la lecture des actions existantes créées avant cette règle.
    resp_suivi: str
    deadline: date
    project_id: uuid.UUID
    responsable_names: list[str] = Field(..., min_length=1)
    phase: str | None = None  # requis seulement si le projet a has_phases=True


class ActionUpdate(BaseModel):
    description: str | None = None
    resp_suivi: str | None = None
    progress: float | None = Field(None, ge=0.0, le=100.0)
    spi: float | None = None
    otd: float | None = None
    deadline: date | None = None
    date_realisation: date | None = None
    charges_hj: float | None = None
    commentaire: str | None = None
    status: str | None = None
    phase: str | None = None


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
    code: str
    name: str
    source_file_path: str
    has_phases: bool = False


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = None
    source_file_path: str | None = None
    is_active: bool | None = None
    has_phases: bool | None = None


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
