import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import ActionStatus


class ActionSummaryOut(BaseModel):
    """Compteurs par vue, pour un bandeau de tableau de bord."""

    generated_at: datetime = Field(..., description="Horodatage du calcul (UTC).")
    counts: dict[str, int] = Field(
        ...,
        description="Nombre d'actions par vue métier (`overdue`, `today`, `blocked`, …).",
    )
    overdue_ratio: float = Field(
        ...,
        description=(
            "Part des actions ouvertes qui sont en retard, en pourcentage. "
            "Un projet sain reste sous 10 %."
        ),
    )


class ActionDigestOut(BaseModel):
    """Action réduite à ce qui compte dans un rapport ou un email."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero: str
    description: str
    project_code: str | None = None
    project_name: str | None = None
    status: ActionStatus
    progress: float
    deadline: date | None = None
    days_left: int | None = Field(
        None,
        description=(
            "Jours restants avant l'échéance. Négatif si l'échéance est "
            "dépassée, `null` si l'action n'a pas de date cible."
        ),
    )
    resp_suivi: str | None = None
    responsables: list[str] = Field(default_factory=list, description="Noms affichés.")


class ProjectReportOut(BaseModel):
    """Indicateurs consolidés d'un projet."""

    project_id: uuid.UUID
    code: str
    name: str
    is_active: bool
    last_synced_at: datetime | None = None

    total_actions: int
    done: int
    open: int
    overdue: int
    blocked: int
    due_soon: int
    unassigned: int
    no_deadline: int

    progress_avg: float = Field(
        ..., description="Avancement moyen des actions, en pourcentage."
    )
    completion_rate: float = Field(
        ..., description="Part des actions terminées, en pourcentage."
    )
    overdue_rate: float = Field(
        ..., description="Part des actions ouvertes en retard, en pourcentage."
    )
    spi_avg: float = Field(..., description="SPI moyen des actions du projet.")
    otd_avg: float = Field(..., description="OTD moyen des actions du projet.")
    charges_hj_total: float = Field(
        ..., description="Somme des charges estimées, en homme/jour."
    )
    health: str = Field(
        ...,
        description=(
            "Synthèse : `ok` (aucun retard), `attention` (jusqu'à 20 % de "
            "retard ou au moins un blocage), `critique` (au-delà)."
        ),
    )


class PortfolioReportOut(BaseModel):
    """Vue portefeuille : tous les projets, plus les totaux."""

    generated_at: datetime
    scope: str = Field(..., description="`active` ou `all`, selon le filtre demandé.")
    project_count: int
    totals: ActionSummaryOut
    projects: list[ProjectReportOut]


class ResponsableReportOut(BaseModel):
    """Charge et ponctualité d'un responsable."""

    responsable_id: uuid.UUID
    display_name: str
    email: str | None = None
    is_mapped: bool

    total_actions: int
    open: int
    overdue: int
    due_soon: int
    blocked: int
    done: int
    progress_avg: float
    overdue_rate: float
    next_deadline: date | None = Field(
        None, description="Échéance ouverte la plus proche."
    )
    last_relance_at: datetime | None = Field(
        None, description="Date du dernier email de relance enregistré."
    )


class WorkloadReportOut(BaseModel):
    """Répartition de la charge entre responsables."""

    generated_at: datetime
    responsable_count: int
    unassigned_actions: int = Field(
        ...,
        description=(
            "Actions ouvertes que personne ne porte : invisibles de toute "
            "relance tant qu'un responsable ne leur est pas rattaché."
        ),
    )
    responsables: list[ResponsableReportOut]


class WeekBucketOut(BaseModel):
    """Un créneau hebdomadaire du plan de charge."""

    week_start: date
    week_end: date
    label: str = Field(..., description="Libellé lisible, ex. « semaine du 24/08 ».")
    action_count: int
    charges_hj: float
    actions: list[ActionDigestOut] = Field(default_factory=list)


class ForecastReportOut(BaseModel):
    """Échéances à venir, semaine par semaine."""

    generated_at: datetime
    weeks: list[WeekBucketOut]
    overdue_backlog: int = Field(
        ...,
        description=(
            "Actions déjà en retard, hors créneaux : elles pèsent sur la "
            "capacité des semaines à venir sans y apparaître."
        ),
    )
