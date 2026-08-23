"""
Règles d'ouverture et de réservation des créneaux.

Elles vivent ici, et non dans le routeur, pour qu'une seule fonction décide de
ce qu'est un horaire valide. Le frontend applique les mêmes bornes afin de
griser les cases immédiatement, mais c'est cette validation qui fait autorité :
un appel direct à l'API doit être refusé aussi sûrement qu'un clic.
"""

from datetime import datetime, timedelta, timezone

from app.models.slot import SLOT_MINUTES

#: Fuseau métier (Madagascar, UTC+3). Les bornes horaires ci-dessous
#: s'entendent en heure locale : stockées en UTC, elles glisseraient d'une
#: journée à l'autre pour un utilisateur connecté depuis un autre fuseau.
MG_TZ = timezone(timedelta(hours=3))

#: Plage ouvrable, heure locale.
OPEN_HOUR = 8
CLOSE_HOUR = 17
#: Pause déjeuner : aucune disponibilité entre 12 h et 13 h.
LUNCH_HOUR = 12

#: Délai minimal entre maintenant et le début d'un créneau réservable.
MIN_LEAD_MINUTES = 15


class SlotRuleError(ValueError):
    """Horaire refusé — le message est destiné à l'utilisateur."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_local(moment: datetime) -> datetime:
    """Ramène un instant au fuseau métier, en supposant UTC s'il est naïf."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(MG_TZ)


def ends_at(starts_at: datetime, duration_minutes: int = SLOT_MINUTES) -> datetime:
    return starts_at + timedelta(minutes=duration_minutes)


def normalize(starts_at: datetime) -> datetime:
    """Ramène l'horaire en UTC, après avoir vérifié qu'il est exploitable."""
    if starts_at.tzinfo is None:
        # Un horaire sans fuseau est ambigu : le refuser vaut mieux que de
        # supposer UTC et décaler le rendez-vous de trois heures en silence.
        raise SlotRuleError(
            "Horaire sans fuseau horaire : indiquer un décalage explicite "
            "(par exemple 2026-08-24T08:15:00+03:00)."
        )
    return starts_at.astimezone(timezone.utc)


def validate_open(starts_at: datetime, *, reference: datetime | None = None) -> datetime:
    """Valide un horaire que le DSIO souhaite ouvrir.

    Renvoie l'horaire normalisé en UTC, ou lève `SlotRuleError`.
    """
    moment = normalize(starts_at)
    local = to_local(moment)

    if moment.second or moment.microsecond or local.minute % SLOT_MINUTES:
        raise SlotRuleError(
            f"Les créneaux sont alignés sur {SLOT_MINUTES} minutes : "
            f"{local:%H:%M:%S} n'est pas un début valide."
        )

    if local.weekday() >= 5:
        raise SlotRuleError(
            f"Le {local:%d/%m/%Y} tombe un week-end : aucune disponibilité ouvrable."
        )

    if not (OPEN_HOUR <= local.hour < CLOSE_HOUR):
        raise SlotRuleError(
            f"{local:%H:%M} est hors de la plage ouvrable "
            f"({OPEN_HOUR:02d}:00 – {CLOSE_HOUR:02d}:00)."
        )

    if local.hour == LUNCH_HOUR:
        raise SlotRuleError(
            f"{local:%H:%M} tombe sur la pause déjeuner "
            f"({LUNCH_HOUR:02d}:00 – {LUNCH_HOUR + 1:02d}:00)."
        )

    floor = (reference or now_utc()) + timedelta(minutes=MIN_LEAD_MINUTES)
    if moment < floor:
        raise SlotRuleError(
            f"Un créneau doit commencer au moins {MIN_LEAD_MINUTES} minutes "
            f"après l'heure courante — {local:%d/%m à %H:%M} est trop proche."
        )

    return moment


def validate_bookable(starts_at: datetime, *, reference: datetime | None = None) -> None:
    """Vérifie qu'un créneau déjà ouvert peut encore être demandé.

    Plus permissif que `validate_open` : les bornes ouvrables ont été
    contrôlées à la création, seul le délai de prévenance reste à revérifier —
    un créneau ouvert la veille peut être devenu trop proche depuis.
    """
    moment = normalize(starts_at)
    floor = (reference or now_utc()) + timedelta(minutes=MIN_LEAD_MINUTES)
    if moment < floor:
        local = to_local(moment)
        raise SlotRuleError(
            f"Le créneau de {local:%H:%M} commence dans moins de "
            f"{MIN_LEAD_MINUTES} minutes : il n'est plus réservable."
        )


def assert_contiguous(starts: list[datetime]) -> None:
    """Refuse une demande faite de quarts d'heure non jointifs.

    Un rendez-vous est une plage continue. Autoriser « 8 h 00 puis 10 h 30 »
    dans une même demande rendrait l'acceptation ambiguë : le DSIO validerait
    deux rendez-vous en un clic sans le voir.
    """
    if len(starts) < 2:
        return
    ordered = sorted(normalize(value) for value in starts)
    step = timedelta(minutes=SLOT_MINUTES)
    for previous, current in zip(ordered, ordered[1:]):
        if current - previous != step:
            raise SlotRuleError(
                "Les créneaux d'une même demande doivent se suivre sans "
                f"interruption : {to_local(previous):%H:%M} et "
                f"{to_local(current):%H:%M} ne sont pas jointifs."
            )
