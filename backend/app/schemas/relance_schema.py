import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.project import RelancePerimetre
from app.schemas.project_schema import PartialUpdate
from app.schemas.report_schema import ActionDigestOut
from app.services.email_templates import RelanceKind
from app.services.relance_digest import JOURS_FR, SectionKey


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


# ---------------------------------------------------------------------------
# Préférences d'envoi
# ---------------------------------------------------------------------------

_JOURS_DESCRIPTION = (
    "Jours d'envoi, en indices `date.weekday()` : 0 = lundi … 6 = dimanche. "
    "Le nombre de jours *est* la fréquence hebdomadaire — deux entrées valent "
    "deux envois par semaine. Par défaut `[0, 3]` (lundi et jeudi)."
)


def _valider_jours(valeurs: list[int] | None) -> list[int] | None:
    """Contrôle et normalise une liste de jours d'envoi.

    Fonction de module plutôt que méthode héritée : un validateur Pydantic est
    un descripteur, et le réutiliser d'une classe à l'autre par héritage
    d'attribut ne rattache pas le champ dans la sous-classe.
    """
    if valeurs is None:
        return None
    hors_bornes = [v for v in valeurs if not 0 <= v <= 6]
    if hors_bornes:
        raise ValueError(
            f"Jour invalide {hors_bornes[0]} : attendu 0 (lundi) à 6 (dimanche)."
        )
    # Trier et dédoublonner ici plutôt qu'à la lecture : la valeur part dans
    # une colonne texte, et « 3,0,3 » y serait indistinguable d'un réglage
    # volontaire au moment de l'afficher.
    uniques = sorted(set(valeurs))
    if not uniques:
        raise ValueError(
            "Au moins un jour d'envoi est requis. Pour suspendre les relances, "
            "utiliser `enabled: false` — le réglage reste alors en place et se "
            "retrouve tel quel à la reprise."
        )
    return uniques


class RelancePreferenceBase(BaseModel):
    """Réglages d'envoi communs à la lecture et à l'écriture."""

    enabled: bool = Field(
        True, description="Faux, la personne ne reçoit plus aucun récapitulatif."
    )
    perimeter: RelancePerimetre = Field(
        RelancePerimetre.SUIVI,
        description=(
            "Quelles actions figurent dans le message : `suivi` (celles dont "
            "la personne assure le suivi, colonne E — la valeur par défaut), "
            "`realisation` (celles qu'elle doit réaliser, colonne D), ou "
            "`les_deux`."
        ),
    )
    days_of_week: list[int] = Field(
        default_factory=lambda: [0, 3], description=_JOURS_DESCRIPTION
    )
    send_hour: int = Field(
        8, ge=0, le=23,
        description=(
            "Heure d'envoi, dans le fuseau du serveur de relance "
            "(`RELANCE_TIMEZONE`, Indian/Antananarivo par défaut)."
        ),
    )
    include_overdue: bool = Field(True, description="Section « en retard ».")
    include_today: bool = Field(True, description="Section « à rendre aujourd'hui ».")
    include_due_soon: bool = Field(
        True, description="Section « échéances proches », sur `horizon_days` jours."
    )
    include_pending: bool = Field(
        True,
        description=(
            "Section « en attente » : actions ouvertes sans échéance, ou dont "
            "l'échéance dépasse l'horizon. C'est le complément exact des trois "
            "autres sections."
        ),
    )
    horizon_days: int = Field(
        3, ge=1, le=90, description="Fenêtre de la section « échéances proches », en jours."
    )

    @field_validator("days_of_week")
    @classmethod
    def _jours_valides(cls, valeurs: list[int]) -> list[int]:
        return _valider_jours(valeurs)


class RelancePreferenceUpdate(PartialUpdate):
    """Modification partielle des réglages — seuls les champs fournis changent."""

    enabled: bool | None = None
    perimeter: RelancePerimetre | None = None
    days_of_week: list[int] | None = Field(None, description=_JOURS_DESCRIPTION)
    send_hour: int | None = Field(None, ge=0, le=23)
    include_overdue: bool | None = None
    include_today: bool | None = None
    include_due_soon: bool | None = None
    include_pending: bool | None = None
    horizon_days: int | None = Field(None, ge=1, le=90)

    @field_validator("days_of_week")
    @classmethod
    def _jours_valides(cls, valeurs: list[int] | None) -> list[int] | None:
        return _valider_jours(valeurs)


class RelancePreferenceOut(RelancePreferenceBase):
    """Réglages effectifs d'une personne, valeurs par défaut comprises."""

    model_config = ConfigDict(from_attributes=True)

    responsable_id: uuid.UUID
    responsable_name: str
    email: str | None = None
    is_mapped: bool = Field(
        ..., description="Faux, aucun email : le réglage est sans effet."
    )
    personnalise: bool = Field(
        ...,
        description=(
            "Faux tant que la personne n'a rien réglé : les valeurs renvoyées "
            "sont alors celles par défaut, appliquées telles quelles."
        ),
    )
    frequence_hebdomadaire: int = Field(
        ..., description="Nombre d'envois par semaine — la longueur de `days_of_week`."
    )
    cadence: str = Field(
        ..., description="Cadence en clair, telle qu'elle figure en pied de message."
    )
    jours_labels: list[str] = Field(
        default_factory=list, description="Jours d'envoi en toutes lettres."
    )


# ---------------------------------------------------------------------------
# Récapitulatif
# ---------------------------------------------------------------------------

class RelanceSectionOut(BaseModel):
    """Une section du récapitulatif et les actions qu'elle contient."""

    key: SectionKey
    label: str
    intro: str
    action_count: int
    actions: list[ActionDigestOut]


class RelanceDigestPreviewOut(BaseModel):
    """Aperçu complet du récapitulatif d'une personne, sans rien envoyer."""

    responsable_id: uuid.UUID
    responsable_name: str
    email: str | None = None
    is_mapped: bool
    preference: RelancePreferenceOut
    subject: str
    action_count: int
    sections: list[RelanceSectionOut]
    html: str = Field(..., description="Corps HTML, tel qu'il sera remis à Outlook.")
    text: str = Field(..., description="Corps texte brut de repli.")
    would_send: bool
    skip_reason: str | None = None
    next_send_at: datetime | None = Field(
        None,
        description=(
            "Prochain créneau d'envoi automatique, dans le fuseau de relance. "
            "`null` si les relances sont désactivées pour cette personne."
        ),
    )


class RelanceDigestSendOut(BaseModel):
    """Résultat de l'envoi d'un récapitulatif."""

    responsable_id: uuid.UUID
    responsable_name: str
    email: str | None = None
    status: str = Field(
        ..., description="`sent`, `simulated`, `failed`, `skipped_no_email` ou `skipped`."
    )
    action_count: int
    detail: str | None = None
    relance_log_id: uuid.UUID | None = None


class RelanceDigestBatchOut(BaseModel):
    """Résultat d'une campagne de récapitulatifs."""

    generated_at: datetime
    mode: str
    considered: int = Field(
        ..., description="Personnes ayant au moins une action à signaler."
    )
    sent: int
    simulated: int
    failed: int
    skipped: int
    results: list[RelanceDigestSendOut]


def jours_en_lettres(jours: list[int]) -> list[str]:
    """« [0, 3] » -> « ['lundi', 'jeudi'] »."""
    return [JOURS_FR[j] for j in jours if 0 <= j <= 6]
