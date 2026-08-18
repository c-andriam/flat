import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.report_schema import ActionDigestOut
from app.services.email_templates import RelanceKind


class RelanceConfigOut(BaseModel):
    """État de la configuration d'envoi — à consulter avant de s'étonner
    qu'aucun email n'arrive."""

    mode: str = Field(..., description="`graph` (envoi réel) ou `dry_run` (simulation).")
    explanation: str = Field(..., description="Ce qui manque, le cas échéant.")
    sender: str | None = Field(None, description="Boîte d'envoi (GRAPH_SENDER_UPN).")
    cooldown_days: int = Field(..., description="Délai minimal entre deux relances d'un même responsable.")
    horizon_days: int = Field(..., description="Fenêtre de la vue « échéance proche ».")


class RelancePreviewOut(BaseModel):
    """Aperçu complet du message, sans rien envoyer."""

    responsable_id: uuid.UUID
    responsable_name: str
    email: str | None = None
    is_mapped: bool
    kind: RelanceKind
    subject: str
    action_count: int
    actions: list[ActionDigestOut]
    html: str = Field(..., description="Corps HTML, tel qu'il sera remis à Outlook.")
    text: str = Field(..., description="Corps texte brut de repli.")
    would_send: bool = Field(
        ...,
        description=(
            "Faux si l'envoi serait ignoré : responsable non mappé, aucune "
            "action concernée, ou période de silence en cours."
        ),
    )
    skip_reason: str | None = Field(None, description="Motif du non-envoi, le cas échéant.")


class RelanceSendOut(BaseModel):
    """Résultat d'un envoi pour un responsable."""

    responsable_id: uuid.UUID
    responsable_name: str
    email: str | None = None
    kind: RelanceKind
    status: str = Field(
        ...,
        description="`sent`, `simulated`, `failed`, `skipped_no_email` ou `skipped`.",
    )
    action_count: int
    detail: str | None = None
    relance_log_id: uuid.UUID | None = Field(
        None, description="Trace enregistrée, absente si rien n'a été envoyé."
    )


class RelanceBatchOut(BaseModel):
    """Résultat d'une campagne sur l'ensemble des responsables."""

    generated_at: datetime
    kind: RelanceKind
    mode: str
    considered: int = Field(..., description="Responsables ayant au moins une action concernée.")
    sent: int
    simulated: int
    failed: int
    skipped: int
    results: list[RelanceSendOut]
