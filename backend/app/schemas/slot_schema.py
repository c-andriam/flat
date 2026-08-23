import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.slot import SlotStatus


class SlotOut(BaseModel):
    """Un quart d'heure, tel que le voit l'appelant.

    L'identité du demandeur est volontairement absente pour un tiers : savoir
    *quand* un créneau est pris suffit à s'organiser, savoir *qui* consulte le
    DSIO n'a pas à circuler.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_user_id: uuid.UUID
    owner_display_name: str
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    status: SlotStatus

    request_group_id: uuid.UUID | None = None
    requested_by_user_id: uuid.UUID | None = Field(
        None, description="Renseigné pour le DSIO propriétaire, un admin, ou le demandeur lui-même."
    )
    requested_by_display_name: str | None = None
    subject: str | None = Field(
        None, description="Objet du rendez-vous, visible des mêmes personnes."
    )
    is_mine: bool = Field(
        False, description="Vrai si la demande sur ce créneau est celle de l'appelant."
    )
    requested_at: datetime | None = None
    decided_at: datetime | None = None


class SlotOpenIn(BaseModel):
    """Ouverture de disponibilités par le DSIO."""

    starts_at: list[datetime] = Field(
        ...,
        min_length=1,
        max_length=200,
        description=(
            "Débuts de créneaux, alignés sur 15 minutes et horodatés avec "
            "leur fuseau. Les créneaux déjà ouverts sont ignorés sans erreur."
        ),
    )

    @field_validator("starts_at")
    @classmethod
    def _dedupe(cls, values: list[datetime]) -> list[datetime]:
        # Le même horaire envoyé deux fois violerait la contrainte UNIQUE au
        # milieu du lot et ferait échouer l'ouverture entière.
        seen: dict[datetime, None] = {}
        for value in values:
            seen.setdefault(value, None)
        return list(seen)


class SlotRequestIn(BaseModel):
    """Demande de rendez-vous sur des créneaux ouverts et jointifs."""

    slot_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Identifiants des quarts d'heure demandés, consécutifs.",
    )
    subject: str | None = Field(
        None, max_length=255, description="Objet du rendez-vous."
    )

    @field_validator("slot_ids")
    @classmethod
    def _dedupe(cls, values: list[uuid.UUID]) -> list[uuid.UUID]:
        seen: dict[uuid.UUID, None] = {}
        for value in values:
            seen.setdefault(value, None)
        return list(seen)


class SlotMoveIn(BaseModel):
    """Déplacement d'un créneau ou d'une plage entière."""

    slot_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Créneaux à déplacer, d'un même propriétaire.",
    )
    starts_at: datetime = Field(
        ...,
        description=(
            "Nouvel horaire du **premier** créneau. Le décalage qui en découle "
            "est appliqué à tous les autres, ce qui préserve la durée."
        ),
    )

    @field_validator("slot_ids")
    @classmethod
    def _dedupe(cls, values: list[uuid.UUID]) -> list[uuid.UUID]:
        seen: dict[uuid.UUID, None] = {}
        for value in values:
            seen.setdefault(value, None)
        return list(seen)


class SlotRequestOut(BaseModel):
    """Un rendez-vous, vu comme un tout plutôt que comme N quarts d'heure."""

    request_group_id: uuid.UUID
    owner_user_id: uuid.UUID
    owner_display_name: str
    requested_by_user_id: uuid.UUID | None = None
    requested_by_display_name: str | None = None
    subject: str | None = None
    status: SlotStatus
    starts_at: datetime
    ends_at: datetime
    slot_count: int
    duration_minutes: int
    requested_at: datetime | None = None
    decided_at: datetime | None = None
    is_mine: bool = False


class SlotOpenResultOut(BaseModel):
    """Bilan d'une ouverture : ce qui a été créé, ce qui existait déjà."""

    created: int
    skipped: int = Field(..., description="Créneaux déjà ouverts, laissés en l'état.")
    slots: list[SlotOut]
