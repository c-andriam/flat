import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


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
    numero: str
    description: str
    progress: float = 0.0
    deadline: date | None = None


class ActionCreate(ActionBase):
    project_id: uuid.UUID
    responsable_names: list[str] = []  # noms bruts extraits d'Excel


class ActionUpdate(BaseModel):
    description: str | None = None
    progress: float | None = None
    deadline: date | None = None
    status: str | None = None


class ActionOut(ActionBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
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


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = None
    source_file_path: str | None = None
    is_active: bool | None = None


class ProjectOut(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    created_at: datetime
    last_synced_at: datetime | None = None


class ProjectWithActionsOut(ProjectOut):
    actions: list[ActionOut] = []
