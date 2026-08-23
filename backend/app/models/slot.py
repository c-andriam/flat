import enum
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.base import UUIDMixin

#: Granularité d'un créneau. Les créneaux sont stockés comme des unités
#: atomiques de 15 minutes plutôt que comme des intervalles libres : une plage
#: d'une heure est donc quatre lignes consécutives.
#:
#: Ce choix rend le chevauchement structurellement impossible — deux offres du
#: même propriétaire au même horaire violent une simple contrainte UNIQUE. Un
#: modèle à intervalles aurait exigé une contrainte d'exclusion GiST, donc
#: l'extension `btree_gist`, dont l'installation n'est pas garantie sur une
#: base managée.
SLOT_MINUTES = 15


class SlotStatus(str, enum.Enum):
    #: Ouvert par le DSIO, personne ne l'a pris.
    OPEN = "open"
    #: Rendez-vous pris. Il n'y a pas d'étape d'acceptation : ouvrir un
    #: créneau vaut engagement de le tenir, et une validation que le DSIO
    #: accordait systématiquement n'était qu'une file d'attente de plus.
    CONFIRMED = "confirmed"

    @property
    def is_taken(self) -> bool:
        """Le créneau n'est plus proposable à quelqu'un d'autre."""
        return self is not SlotStatus.OPEN


class Slot(UUIDMixin, Base):
    """Un quart d'heure de disponibilité ouvert par le DSIO.

    L'annulation d'un rendez-vous ne supprime pas la ligne : elle la ramène à
    `OPEN`, ce qui remet le créneau à disposition de tout le monde. Un statut
    « annulé » terminal aurait encombré la grille de cases mortes que le DSIO
    aurait dû rouvrir à la main.
    """

    __tablename__ = "slots"

    owner_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    starts_at = Column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes = Column(SmallInteger, default=SLOT_MINUTES, nullable=False)

    status = Column(
        Enum(SlotStatus), default=SlotStatus.OPEN, nullable=False, index=True
    )

    # `SET NULL` plutôt que `CASCADE` : la suppression d'un compte ne doit pas
    # effacer les disponibilités du DSIO, seulement la demande qui s'y
    # rattachait.
    requested_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Regroupe les quarts d'heure consécutifs d'un même rendez-vous : c'est
    #: lui, et non l'identifiant de créneau, qu'on accepte ou refuse.
    request_group_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    subject = Column(String(255), nullable=True)
    requested_at = Column(DateTime(timezone=True), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # `lazy="raise"` volontaire : les noms d'affichage sont ramenes par la
    # jointure de `routers/slots.py`. Laisser SQLAlchemy les charger tout seul
    # ajoutait deux requetes par appel, invisibles a la lecture du code — donc
    # une demi-seconde sur une base distante. Tout acces oublie echoue ici,
    # bruyamment, plutot que de couter silencieusement un aller-retour.
    owner = relationship("User", foreign_keys=[owner_user_id], lazy="raise")
    requested_by = relationship(
        "User", foreign_keys=[requested_by_user_id], lazy="raise"
    )

    __table_args__ = (
        UniqueConstraint("owner_user_id", "starts_at", name="uq_slot_owner_start"),
        # Index de la requête dominante : « les créneaux de ce DSIO entre deux
        # dates », que la grille émet à chaque changement de semaine.
        Index("ix_slots_owner_window", "owner_user_id", "starts_at"),
    )

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes or SLOT_MINUTES)

    def __repr__(self) -> str:
        return f"<Slot id={self.id} start={self.starts_at} status={self.status}>"


def new_request_group_id() -> uuid.UUID:
    return uuid.uuid4()
