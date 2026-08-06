import enum
from datetime import date, datetime

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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.base import UUIDMixin

# ---------------------------------------------------------------------------
# Table d'association Action <-> Responsable (many-to-many)
# Une action peut avoir plusieurs responsables (ex: "Meylis, Xavier" dans Excel)
# ---------------------------------------------------------------------------
action_responsables = Table(
    "action_responsables",
    Base.metadata,
    Column("action_id", UUID(as_uuid=True), ForeignKey("actions.id", ondelete="CASCADE"), primary_key=True),
    Column("responsable_id", UUID(as_uuid=True), ForeignKey("responsables.id", ondelete="CASCADE"), primary_key=True),
)


class Responsable(UUIDMixin, Base):
    """
    Personne responsable d'actions, extraite de la colonne "Resp. réalisation"
    des fichiers Excel.

    display_name : nom brut tel qu'il apparaît dans Excel (ex: "Meylis").
    email        : renseigné manuellement via l'interface de mapping.
    is_mapped    : False tant qu'aucun email n'est associé -> déclenche
                   l'alerte "Nouveau responsable détecté" côté worker d'ingestion.
    """

    __tablename__ = "responsables"

    display_name = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True)
    is_mapped = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    actions = relationship("Action", secondary=action_responsables, back_populates="responsables")
    relances = relationship("RelanceLog", back_populates="responsable", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Responsable id={self.id} display_name={self.display_name!r} mapped={self.is_mapped}>"


class Project(UUIDMixin, Base):
    """
    Projet source, correspondant à un fichier Excel dans
    SharePoint (ex: 07_Projets_DSIO/Projet encours/P01 - Nom/P01_xxx.xlsx).
    """

    __tablename__ = "projects"

    code = Column(String(50), unique=True, nullable=False, index=True)  # ex: "P01"
    name = Column(String(255), nullable=False)
    source_file_path = Column(String(1024), nullable=False)  # chemin SharePoint du fichier Excel
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
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
    """
    Ligne d'action extraite du tableau Excel d'un projet
    (colonnes: N° d'actions, Actions, Resp. réalisation, %Progress, Deadline).
    """

    __tablename__ = "actions"

    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)

    numero = Column(String(50), nullable=False)  # "N° d'actions" tel quel dans Excel
    description = Column(Text, nullable=False)
    progress = Column(Float, default=0.0, nullable=False)  # 0.0 -> 100.0
    deadline = Column(Date, nullable=True)
    status = Column(Enum(ActionStatus), default=ActionStatus.A_FAIRE, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="actions")
    responsables = relationship("Responsable", secondary=action_responsables, back_populates="actions")

    def is_overdue(self, today: date | None = None) -> bool:
        """Deadline <= aujourd'hui ET progress < 100 -> éligible à une relance."""
        today = today or date.today()
        return self.deadline is not None and self.deadline <= today and self.progress < 100.0

    def __repr__(self) -> str:
        return f"<Action id={self.id} numero={self.numero!r} progress={self.progress}>"


class SyncStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class SyncLog(UUIDMixin, Base):
    """Historique des synchronisations SharePoint -> PostgreSQL (worker d'ingestion)."""

    __tablename__ = "sync_logs"

    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    status = Column(Enum(SyncStatus), default=SyncStatus.RUNNING, nullable=False)
    files_processed = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<SyncLog id={self.id} status={self.status} files={self.files_processed}>"


class RelanceLog(UUIDMixin, Base):
    """Historique des e-mails de relance envoyés via Outlook (moteur d'alertes)."""

    __tablename__ = "relance_logs"

    responsable_id = Column(UUID(as_uuid=True), ForeignKey("responsables.id", ondelete="CASCADE"), nullable=False, index=True)
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    action_ids = Column(Text, nullable=False)  # liste d'IDs d'actions concernées, sérialisée en JSON
    email_status = Column(String(50), default="sent", nullable=False)  # sent / failed

    responsable = relationship("Responsable", back_populates="relances")

    def __repr__(self) -> str:
        return f"<RelanceLog id={self.id} responsable_id={self.responsable_id} sent_at={self.sent_at}>"
