from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


# --- Responsable (imbriqué dans Action) ---

class ResponsableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    email: str | None = None
    is_mapped: bool


# --- Action ---

class ActionBase(BaseModel):
    numero: str
    description: str
    progress: float = 0.0
    deadline: date | None = None


class ActionCreate(ActionBase):
    project_id: int
    responsable_names: list[str] = []  # noms bruts extraits d'Excel


class ActionUpdate(BaseModel):
    description: str | None = None
    progress: float | None = None
    deadline: date | None = None
    status: str | None = None


class ActionOut(ActionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
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


class ProjectOut(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
    last_synced_at: datetime | None = None


class ProjectWithActionsOut(ProjectOut):
    actions: list[ActionOut] = []
