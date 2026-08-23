import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.base import UUIDMixin


class ReportItemSource(str, enum.Enum):
    """D'où vient une ligne du rapport."""

    #: Reprise d'une action suggérée — la ligne reste liée à cette action.
    ACTION = "action"
    #: Saisie libre : réunion, dépannage, tout ce qui ne porte pas de numéro.
    MANUAL = "manual"


class DailyReport(UUIDMixin, Base):
    """Rapport de fin de journée d'un compte, pour une date donnée.

    Une seule ligne par personne et par jour : la contrainte d'unicité évite
    qu'un double-clic ou deux onglets ouverts n'en créent deux, ce qui
    donnerait deux rapports partiels au lieu d'un complet.
    """

    __tablename__ = "daily_reports"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Date métier du rapport, en heure locale — pas l'horodatage de création.
    report_date = Column(Date, nullable=False, index=True)

    note = Column(Text, nullable=True)
    #: Renseigné quand la personne déclare sa journée close. Un rapport non
    #: soumis reste un brouillon, mais compte déjà comme « commencé » et fait
    #: disparaître le rappel.
    submitted_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = relationship("User", lazy="raise")
    items = relationship(
        "DailyReportItem",
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="DailyReportItem.position",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "report_date", name="uq_daily_report_user_date"),
        Index("ix_daily_reports_user_date", "user_id", "report_date"),
    )

    def __repr__(self) -> str:
        return f"<DailyReport user={self.user_id} date={self.report_date}>"


class DailyReportItem(UUIDMixin, Base):
    """Une ligne du rapport : une tâche déclarée."""

    __tablename__ = "daily_report_items"

    report_id = Column(
        UUID(as_uuid=True),
        ForeignKey("daily_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: `SET NULL` : supprimer une action ne doit pas effacer la trace du
    #: travail déclaré ce jour-là. Le libellé, lui, est recopié à la création.
    action_id = Column(
        UUID(as_uuid=True),
        ForeignKey("actions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source = Column(Enum(ReportItemSource), nullable=False, default=ReportItemSource.MANUAL)

    #: Copie du libellé au moment de la déclaration. Une action renommée trois
    #: mois plus tard ne doit pas réécrire ce qui a été rapporté.
    label = Column(String(500), nullable=False)
    done = Column(Boolean, nullable=False, default=False)
    position = Column(SmallInteger, nullable=False, default=0)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    report = relationship("DailyReport", back_populates="items")

    def __repr__(self) -> str:
        return f"<DailyReportItem {self.label[:30]!r} done={self.done}>"
