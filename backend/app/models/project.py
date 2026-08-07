import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.base import UUIDMixin

# ---------------------------------------------------------------------------
# Table d'association Action <-> Responsable (many-to-many)
# ---------------------------------------------------------------------------
action_responsables = Table(
    "action_responsables",
    Base.metadata,
    Column("action_id", UUID(as_uuid=True), ForeignKey("actions.id", ondelete="CASCADE"), primary_key=True),
    Column("responsable_id", UUID(as_uuid=True), ForeignKey("responsables.id", ondelete="CASCADE"), primary_key=True),
)


class Responsable(UUIDMixin, Base):
    """Personne responsable d'actions (colonne D - Resp. réalisation)."""

    __tablename__ = "responsables"

    display_name = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True)
    is_mapped = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    actions = relationship("Action", secondary=action_responsables, back_populates="responsables")
    relances = relationship("RelanceLog", back_populates="responsable", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Responsable id={self.id} display_name={self.display_name!r} mapped={self.is_mapped}>"


class Project(UUIDMixin, Base):
    __tablename__ = "projects"

    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    source_file_path = Column(String(1024), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    has_phases = Column(Boolean, default=False, nullable=False)  # active le format P01-01-01

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_synced_at = Column(DateTime, nullable=True)

    actions = relationship("Action", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Project id={self.id} code={self.code!r} name={self.name!r}>"


class ActionStatus(str, enum.Enum):
    A_FAIRE = "a_faire"
    EN_COURS = "en_cours"
    EN_RETARD = "en_retard"
    TERMINE = "termine"


class Action(UUIDMixin, Base):
    __tablename__ = "actions"
    __table_args__ = (
        UniqueConstraint("project_id", "numero", name="uq_action_project_numero"),
    )

    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)

    numero = Column(String(50), nullable=False)               # B - "P01-01" ou "P01-01-01" si phase
    phase = Column(String(10), nullable=True)                  # phase du projet (ex: "01"), si has_phases
    description = Column(Text, nullable=False)                 # C
    # D "Resp. réalisation" -> via la relation responsables (many-to-many)
    resp_suivi = Column(String(255), nullable=True)            # E
    progress = Column(Float, default=0.0, nullable=False)      # F
    spi = Column(Float, default=0.0, nullable=False)          # G
    otd = Column(Float, default=0.0, nullable=False)          # H
    deadline = Column(Date, nullable=True)                     # I
    date_realisation = Column(Date, nullable=True)             # J
    charges_hj = Column(Float, nullable=True)                  # K - Charges (h/j)
    commentaire = Column(Text, nullable=True)                  # L
    status = Column(Enum(ActionStatus), default=ActionStatus.A_FAIRE, nullable=False)  # champ interne, pas dans le tableau Excel

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    project = relationship("Project", back_populates="actions")
    responsables = relationship("Responsable", secondary=action_responsables, back_populates="actions")  # D

    def is_overdue(self, today: date | None = None) -> bool:
        today = today or date.today()
        return self.deadline is not None and self.deadline <= today and self.progress < 100.0

    def __repr__(self) -> str:
        return f"<Action id={self.id} numero={self.numero!r} progress={self.progress}>"

class SyncStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class SyncLog(UUIDMixin, Base):
    __tablename__ = "sync_logs"

    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    finished_at = Column(DateTime, nullable=True)
    status = Column(Enum(SyncStatus), default=SyncStatus.RUNNING, nullable=False)
    files_processed = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<SyncLog id={self.id} status={self.status} files={self.files_processed}>"


class RelanceLog(UUIDMixin, Base):
    __tablename__ = "relance_logs"

    responsable_id = Column(UUID(as_uuid=True), ForeignKey("responsables.id", ondelete="CASCADE"), nullable=False, index=True)
    sent_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    action_ids = Column(Text, nullable=False)
    email_status = Column(String(50), default="sent", nullable=False)

    responsable = relationship("Responsable", back_populates="relances")

    def __repr__(self) -> str:
        return f"<RelanceLog id={self.id} responsable_id={self.responsable_id} sent_at={self.sent_at}>"
