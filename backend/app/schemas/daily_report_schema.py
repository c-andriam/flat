import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.daily_report import ReportItemSource


class ReportItemIn(BaseModel):
    """Une ligne telle que l'envoie le client."""

    #: Absent pour une ligne créée à l'instant ; renseigné pour une modification.
    id: uuid.UUID | None = None
    action_id: uuid.UUID | None = Field(
        None, description="Action reprise, si la ligne vient d'une suggestion."
    )
    label: str = Field(..., min_length=1, max_length=500)
    done: bool = False

    @field_validator("label")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Le libellé ne peut pas être vide.")
        return value


class ReportItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action_id: uuid.UUID | None = None
    source: ReportItemSource
    label: str
    done: bool
    position: int


class DailyReportIn(BaseModel):
    """Contenu complet du rapport d'une journée.

    L'envoi est intégral et non incrémental : le client possède déjà la liste
    à l'écran, et un protocole d'ajouts/suppressions ligne à ligne se
    désynchronise dès qu'une requête se perd.
    """

    items: list[ReportItemIn] = Field(default_factory=list, max_length=100)
    note: str | None = Field(None, max_length=4000)


class DailyReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    user_display_name: str | None = None
    report_date: date
    note: str | None = None
    submitted_at: datetime | None = None
    items: list[ReportItemOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @property
    def is_started(self) -> bool:
        return bool(self.items) or bool(self.note)


class SuggestionReason(BaseModel):
    """Pourquoi une action est proposée — affiché tel quel dans l'interface."""

    code: str = Field(
        ..., description="`deadline_today`, `touched_today` ou `carry_over`."
    )
    label: str


class ReportSuggestionOut(BaseModel):
    """Action proposée à la déclaration du jour."""

    action_id: uuid.UUID
    numero: str
    description: str
    project_code: str | None = None
    progress: float
    deadline: date | None = None
    reasons: list[SuggestionReason] = Field(default_factory=list)
    #: Vrai si la ligne figure déjà dans le rapport — elle ne doit pas être
    #: proposée une seconde fois.
    already_added: bool = False


class TodayReportOut(BaseModel):
    """Réponse de l'écran du jour : le rapport et ses suggestions.

    Les deux en un seul appel : sur une base distante, deux allers-retours
    séquentiels se voient à l'ouverture de l'écran.
    """

    report_date: date
    report: DailyReportOut | None = None
    suggestions: list[ReportSuggestionOut] = Field(default_factory=list)
    #: Le rapport contient au moins une ligne ou une note — c'est ce qui fait
    #: disparaître le rappel.
    has_content: bool = False
