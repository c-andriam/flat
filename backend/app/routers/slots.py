"""
Créneaux de rendez-vous avec le DSIO.

Modèle d'usage : le DSIO ouvre des disponibilités, n'importe quel compte
authentifié en prend une, et le rendez-vous est confirmé immédiatement —
ouvrir un créneau vaut engagement de le tenir. Les deux parties peuvent
annuler, et le DSIO peut déplacer un rendez-vous quand une réunion tombe.

Les collaborateurs ne peuvent pas se donner rendez-vous entre eux : seul le
rôle `dsio` ouvre un créneau, ce que la dépendance RBAC garantit. Un
administrateur n'y a pas accès non plus — il administre les comptes, il n'est
pas un interlocuteur.

Concurrence : la prise d'un créneau est un `UPDATE … WHERE status = 'OPEN'`
suivi d'une vérification du nombre de lignes touchées. Deux personnes qui
cliquent à la même milliseconde ne peuvent donc pas obtenir le même quart
d'heure — la seconde reçoit un 409 plutôt qu'une confirmation mensongère.
Un `SELECT` préalable suivi d'un `UPDATE` aurait laissé exactement cette
fenêtre ouverte.
"""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import delete, select, update
from sqlalchemy.orm import aliased
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.slot import SLOT_MINUTES, Slot, SlotStatus
from app.models.user import User, UserRole
from app.schemas.slot_schema import (
    SlotMoveIn,
    SlotOpenIn,
    SlotOpenResultOut,
    SlotOut,
    SlotRequestIn,
    SlotRequestOut,
)
from app.services import slot_rules
from app.services.events import publish_event
from app.services.security import (
    SLOT_OWNER_ROLES,
    get_current_user,
    require_reader,
    require_slot_owner,
)

router = APIRouter(prefix="/slots", tags=["slots"])

AUTH_RESPONSES = {
    401: {"description": "Jeton absent, invalide ou expiré."},
    403: {"description": "Rôle insuffisant pour cette opération."},
}

#: Fenêtre maximale interrogeable en une fois — la grille affiche une semaine.
MAX_WINDOW_DAYS = 62


def _peut_arbitrer(user: User) -> bool:
    return user.role.value in SLOT_OWNER_ROLES


#: Un créneau porte deux références vers `users` : son propriétaire et son
#: demandeur. Les charger par relation coûtait deux requêtes supplémentaires
#: par appel — soit, sur une base distante à ~250 ms d'aller-retour, une demi-
#: seconde perdue pour deux noms d'affichage. Une jointure les ramène avec la
#: ligne.
_Owner = aliased(User, name="owner_user")
_Requester = aliased(User, name="requester_user")


def _select_slots():
    """`SELECT` de base : le créneau et les deux noms d'affichage, en une passe."""
    return (
        select(Slot, _Owner.display_name, _Requester.display_name)
        .join(_Owner, _Owner.id == Slot.owner_user_id)
        .outerjoin(_Requester, _Requester.id == Slot.requested_by_user_id)
    )


#: Ligne renvoyée par `_select_slots` : (créneau, nom du propriétaire, nom du
#: demandeur ou None).
SlotRow = tuple[Slot, str, str | None]


def _to_out(slot: Slot, owner_name: str, requester_name: str | None, viewer: User) -> SlotOut:
    """Sérialise un créneau en masquant le demandeur aux tiers."""
    is_mine = slot.requested_by_user_id == viewer.id
    devoile = is_mine or _peut_arbitrer(viewer)
    return SlotOut(
        id=slot.id,
        owner_user_id=slot.owner_user_id,
        owner_display_name=owner_name,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        duration_minutes=slot.duration_minutes or SLOT_MINUTES,
        status=slot.status,
        request_group_id=slot.request_group_id,
        requested_by_user_id=slot.requested_by_user_id if devoile else None,
        requested_by_display_name=requester_name if devoile else None,
        subject=slot.subject if devoile else None,
        is_mine=is_mine,
        requested_at=slot.requested_at,
        decided_at=slot.decided_at,
    )


def _grouper(rows: list[SlotRow], viewer: User) -> list[SlotRequestOut]:
    """Reconstitue les rendez-vous à partir de leurs quarts d'heure."""
    par_groupe: dict[uuid.UUID, list[SlotRow]] = {}
    for row in rows:
        if row[0].request_group_id is None:
            continue
        par_groupe.setdefault(row[0].request_group_id, []).append(row)

    demandes: list[SlotRequestOut] = []
    for group_id, membres in par_groupe.items():
        membres.sort(key=lambda item: item[0].starts_at)
        premier, owner_name, requester_name = membres[0]
        dernier = membres[-1][0]
        is_mine = premier.requested_by_user_id == viewer.id
        devoile = is_mine or _peut_arbitrer(viewer)
        demandes.append(
            SlotRequestOut(
                request_group_id=group_id,
                owner_user_id=premier.owner_user_id,
                owner_display_name=owner_name,
                requested_by_user_id=premier.requested_by_user_id if devoile else None,
                requested_by_display_name=requester_name if devoile else None,
                subject=premier.subject if devoile else None,
                status=premier.status,
                starts_at=premier.starts_at,
                ends_at=dernier.ends_at,
                slot_count=len(membres),
                duration_minutes=len(membres) * SLOT_MINUTES,
                requested_at=premier.requested_at,
                decided_at=premier.decided_at,
                is_mine=is_mine,
            )
        )
    demandes.sort(key=lambda item: item.starts_at)
    return demandes


async def _charger_groupe(db: AsyncSession, group_id: uuid.UUID) -> list[SlotRow]:
    result = await db.execute(
        _select_slots().filter(Slot.request_group_id == group_id).order_by(Slot.starts_at)
    )
    return [tuple(row) for row in result.all()]


# ─── Lecture ───


@router.get(
    "",
    response_model=list[SlotOut],
    dependencies=[require_reader],
    summary="Lister les créneaux d'une fenêtre",
    description=(
        "Retourne les créneaux dont le début tombe entre `from_` et `to`, "
        "triés chronologiquement. L'identité du demandeur et l'objet du "
        "rendez-vous ne sont renseignés que pour le DSIO propriétaire, un "
        "administrateur, ou l'auteur de la demande."
    ),
    responses=AUTH_RESPONSES,
)
async def list_slots(
    from_: datetime = Query(
        ..., alias="from", description="Début de la fenêtre (horodatage avec fuseau)."
    ),
    to: datetime = Query(..., description="Fin de la fenêtre, exclue."),
    owner_id: uuid.UUID | None = Query(
        None, description="Restreindre aux disponibilités d'un DSIO donné."
    ),
    mine_only: bool = Query(
        False, description="Ne garder que les créneaux que l'appelant a demandés."
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    if to <= from_:
        raise HTTPException(
            status_code=422, detail="`to` doit être postérieur à `from`."
        )
    if to - from_ > timedelta(days=MAX_WINDOW_DAYS):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Fenêtre trop large : {MAX_WINDOW_DAYS} jours au maximum "
                "par appel."
            ),
        )

    stmt = _select_slots().filter(Slot.starts_at >= from_, Slot.starts_at < to)
    if owner_id is not None:
        stmt = stmt.filter(Slot.owner_user_id == owner_id)
    if mine_only:
        stmt = stmt.filter(Slot.requested_by_user_id == current_user.id)

    result = await db.execute(stmt.order_by(Slot.starts_at))
    return [
        _to_out(slot, owner_name, requester_name, current_user)
        for slot, owner_name, requester_name in result.all()
    ]


@router.get(
    "/requests",
    response_model=list[SlotRequestOut],
    dependencies=[require_reader],
    summary="Lister les rendez-vous",
    description=(
        "Regroupe les quarts d'heure en rendez-vous. Un DSIO ou un admin voit "
        "toutes les demandes ; les autres comptes ne voient que les leurs, "
        "quel que soit le filtre demandé."
    ),
    responses=AUTH_RESPONSES,
)
async def list_requests(
    status_filter: SlotStatus | None = Query(
        None, alias="status", description="Filtrer sur un statut (`pending`, `confirmed`)."
    ),
    upcoming_only: bool = Query(
        True, description="Écarter les rendez-vous dont l'horaire est passé."
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    stmt = _select_slots().filter(Slot.request_group_id.isnot(None))
    if status_filter is not None:
        stmt = stmt.filter(Slot.status == status_filter)
    if upcoming_only:
        stmt = stmt.filter(Slot.starts_at >= slot_rules.now_utc())
    # Le filtrage de confidentialité est appliqué en base, pas au moment de la
    # sérialisation : masquer les champs d'une ligne qu'on n'aurait pas dû
    # renvoyer laisse quand même fuiter l'existence du rendez-vous.
    if not _peut_arbitrer(current_user):
        stmt = stmt.filter(Slot.requested_by_user_id == current_user.id)

    result = await db.execute(stmt.order_by(Slot.starts_at))
    return _grouper([tuple(row) for row in result.all()], current_user)


@router.get(
    "/owners",
    response_model=list[dict],
    dependencies=[require_reader],
    summary="Lister les comptes qui ouvrent des créneaux",
    description="Comptes actifs de rôle `dsio`, auprès desquels prendre rendez-vous.",
    responses=AUTH_RESPONSES,
)
async def list_owners(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(User)
        .filter(User.role == UserRole.DSIO, User.is_active.is_(True))
        .order_by(User.display_name)
    )
    return [
        {"id": str(user.id), "display_name": user.display_name, "email": user.email}
        for user in result.scalars().all()
    ]


# ─── Ouverture (DSIO / admin) ───


@router.post(
    "",
    response_model=SlotOpenResultOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_slot_owner],
    summary="Ouvrir des disponibilités",
    description=(
        "Crée un créneau de 15 minutes par horaire fourni. Les horaires déjà "
        "ouverts sont comptés dans `skipped` sans faire échouer l'appel : "
        "ré-envoyer une sélection élargie est une opération courante."
    ),
    responses={**AUTH_RESPONSES, 422: {"description": "Horaire hors des règles d'ouverture."}},
)
async def open_slots(
    payload: SlotOpenIn,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    reference = slot_rules.now_utc()
    try:
        horaires = [
            slot_rules.validate_open(value, reference=reference)
            for value in payload.starts_at
        ]
    except slot_rules.SlotRuleError as erreur:
        raise HTTPException(status_code=422, detail=str(erreur))

    existants = await db.execute(
        select(Slot.starts_at).filter(
            Slot.owner_user_id == current_user.id, Slot.starts_at.in_(horaires)
        )
    )
    deja_ouverts = set(existants.scalars().all())

    nouveaux = [
        Slot(owner_user_id=current_user.id, starts_at=horaire, status=SlotStatus.OPEN)
        for horaire in horaires
        if horaire not in deja_ouverts
    ]
    db.add_all(nouveaux)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Deux ouvertures simultanées sur le même horaire : la contrainte
        # UNIQUE a tranché, et c'est bien ce qu'on veut.
        raise HTTPException(
            status_code=409,
            detail="Un de ces créneaux vient d'être ouvert par ailleurs. Réessayez.",
        )

    await publish_event(
        "slot_created",
        {"owner_user_id": current_user.id, "count": len(nouveaux)},
    )
    # Le propriétaire est l'appelant : inutile de relire son nom en base.
    return SlotOpenResultOut(
        created=len(nouveaux),
        skipped=len(deja_ouverts),
        slots=[
            _to_out(slot, current_user.display_name, None, current_user)
            for slot in nouveaux
        ],
    )


@router.delete(
    "/{slot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_slot_owner],
    summary="Retirer une disponibilité",
    description=(
        "Supprime un créneau encore libre. Un créneau demandé ou confirmé est "
        "refusé (409) : il faut d'abord refuser ou annuler le rendez-vous, "
        "pour que le demandeur en soit informé plutôt que de voir son "
        "rendez-vous disparaître."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Créneau introuvable."}},
)
async def delete_slot(
    slot_id: uuid.UUID = Path(..., description="Identifiant du créneau."),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Slot).filter(Slot.id == slot_id))
    slot = result.scalars().first()
    if slot is None:
        raise HTTPException(status_code=404, detail="Créneau introuvable.")
    if slot.owner_user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Ce créneau appartient à un autre compte."
        )
    if slot.status is not SlotStatus.OPEN:
        raise HTTPException(
            status_code=409,
            detail=(
                "Créneau déjà demandé : refuser ou annuler le rendez-vous "
                "avant de retirer la disponibilité."
            ),
        )

    await db.execute(delete(Slot).filter(Slot.id == slot_id))
    await db.commit()
    await publish_event("slot_deleted", {"id": slot_id})


@router.post(
    "/move",
    response_model=list[SlotOut],
    dependencies=[require_slot_owner],
    summary="Déplacer des créneaux",
    description=(
        "Décale un créneau ou une plage entière vers un nouvel horaire, en "
        "conservant les rendez-vous qui s'y rattachent. Le décalage est "
        "calculé à partir du premier créneau fourni et appliqué à tous, pour "
        "qu'une réunion d'une heure reste d'une heure.\n\n"
        "Refusé si la destination chevauche une autre disponibilité, ou si "
        "elle sort des règles d'ouverture."
    ),
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Créneau introuvable."},
        409: {"description": "La destination est déjà occupée."},
        422: {"description": "Destination hors des règles d'ouverture."},
    },
)
async def move_slots(
    payload: SlotMoveIn,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Slot).filter(Slot.id.in_(payload.slot_ids)).order_by(Slot.starts_at)
    )
    slots = list(result.scalars().all())
    if len(slots) != len(payload.slot_ids):
        raise HTTPException(
            status_code=404, detail="Un ou plusieurs créneaux sont introuvables."
        )
    if any(slot.owner_user_id != current_user.id for slot in slots):
        raise HTTPException(
            status_code=403, detail="Ces créneaux appartiennent à un autre compte."
        )

    reference = slot_rules.now_utc()
    try:
        cible = slot_rules.normalize(payload.starts_at)
        # Le décalage vient du premier créneau : déplacer chaque ligne vers le
        # même horaire les empilerait toutes au même endroit.
        delta = cible - slots[0].starts_at
        nouveaux = [slot.starts_at + delta for slot in slots]
        for horaire in nouveaux:
            slot_rules.validate_open(horaire, reference=reference)
    except slot_rules.SlotRuleError as erreur:
        raise HTTPException(status_code=422, detail=str(erreur))

    if delta == timedelta(0):
        return [
            _to_out(slot, current_user.display_name, None, current_user) for slot in slots
        ]

    # Une destination occupée par un créneau qui n'est pas du voyage est un
    # conflit ; occupée par un créneau qui se déplace aussi, non.
    en_mouvement = {slot.id for slot in slots}
    occupes = await db.execute(
        select(Slot.id).filter(
            Slot.owner_user_id == current_user.id,
            Slot.starts_at.in_(nouveaux),
            Slot.id.notin_(en_mouvement),
        )
    )
    if occupes.first() is not None:
        raise HTTPException(
            status_code=409,
            detail="La destination chevauche une disponibilité déjà ouverte.",
        )

    # La contrainte d'unicité est différée jusqu'au COMMIT (migration
    # 900000000000) : sans cela, un décalage d'un quart d'heure ferait passer
    # par un état transitoire où deux lignes partagent le même horaire.
    for slot, horaire in zip(slots, nouveaux):
        slot.starts_at = horaire
    await db.commit()

    for slot in slots:
        await db.refresh(slot)

    await publish_event(
        "slot_moved",
        {"owner_user_id": current_user.id, "count": len(slots)},
    )
    return [
        _to_out(slot, current_user.display_name, None, current_user) for slot in slots
    ]


# ─── Demande de rendez-vous (tout compte authentifié) ───


@router.post(
    "/requests",
    response_model=SlotRequestOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_reader],
    summary="Demander un rendez-vous",
    description=(
        "Réserve des quarts d'heure consécutifs et ouverts, chez un même "
        "propriétaire. Si l'un d'eux vient d'être pris, rien n'est réservé et "
        "l'appel renvoie 409."
    ),
    responses={
        **AUTH_RESPONSES,
        409: {"description": "Un créneau n'est plus disponible."},
        422: {"description": "Créneaux non jointifs, expirés, ou de propriétaires différents."},
    },
)
async def request_slots(
    payload: SlotRequestIn,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Slot).filter(Slot.id.in_(payload.slot_ids)).order_by(Slot.starts_at)
    )
    slots = list(result.scalars().all())

    if len(slots) != len(payload.slot_ids):
        raise HTTPException(
            status_code=404, detail="Un ou plusieurs créneaux sont introuvables."
        )
    if len({slot.owner_user_id for slot in slots}) > 1:
        raise HTTPException(
            status_code=422,
            detail="Un rendez-vous ne peut pas mélanger les disponibilités de deux personnes.",
        )
    if any(slot.status is not SlotStatus.OPEN for slot in slots):
        raise HTTPException(
            status_code=409, detail="Un de ces créneaux n'est plus disponible."
        )
    if slots[0].owner_user_id == current_user.id:
        raise HTTPException(
            status_code=422,
            detail="Vous ne pouvez pas prendre rendez-vous sur vos propres disponibilités.",
        )

    reference = slot_rules.now_utc()
    try:
        slot_rules.assert_contiguous([slot.starts_at for slot in slots])
        for slot in slots:
            slot_rules.validate_bookable(slot.starts_at, reference=reference)
    except slot_rules.SlotRuleError as erreur:
        raise HTTPException(status_code=422, detail=str(erreur))

    group_id = uuid.uuid4()
    # Le `WHERE status = OPEN` est la garde anti-course : entre le SELECT
    # ci-dessus et cet UPDATE, un autre appel a pu prendre le créneau.
    #
    # Le rendez-vous est confirmé d'emblée : le DSIO s'engage en ouvrant le
    # créneau, pas en validant après coup.
    verrou = await db.execute(
        update(Slot)
        .where(Slot.id.in_(payload.slot_ids), Slot.status == SlotStatus.OPEN)
        .values(
            status=SlotStatus.CONFIRMED,
            requested_by_user_id=current_user.id,
            request_group_id=group_id,
            subject=payload.subject,
            requested_at=reference,
            decided_at=reference,
        )
    )
    if verrou.rowcount != len(payload.slot_ids):
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Un de ces créneaux vient d'être pris. Rafraîchissez la grille.",
        )

    await db.commit()

    membres = await _charger_groupe(db, group_id)
    await publish_event(
        "slot_confirmed",
        {
            "request_group_id": group_id,
            "owner_user_id": slots[0].owner_user_id,
            "slot_count": len(membres),
        },
    )
    return _grouper(membres, current_user)[0]


@router.delete(
    "/requests/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_reader],
    summary="Annuler son rendez-vous",
    description=(
        "Le demandeur retire sa demande, ou le propriétaire annule un "
        "rendez-vous confirmé. Les créneaux redeviennent disponibles."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Demande introuvable."}},
)
async def cancel_request(
    group_id: uuid.UUID = Path(..., description="Identifiant du rendez-vous."),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    membres = await _charger_groupe(db, group_id)
    if not membres:
        raise HTTPException(status_code=404, detail="Demande introuvable.")

    premier = membres[0][0]
    # Seuls les deux interesses : le demandeur et le DSIO concerne.
    autorise = (
        premier.requested_by_user_id == current_user.id
        or premier.owner_user_id == current_user.id
    )
    if not autorise:
        raise HTTPException(
            status_code=403, detail="Ce rendez-vous ne vous concerne pas."
        )

    await _liberer(db, group_id)
    await publish_event(
        "slot_released",
        {"request_group_id": group_id, "owner_user_id": premier.owner_user_id},
    )


async def _liberer(db: AsyncSession, group_id: uuid.UUID) -> None:
    """Remet les créneaux d'un rendez-vous à disposition."""
    await db.execute(
        update(Slot)
        .where(Slot.request_group_id == group_id)
        .values(
            status=SlotStatus.OPEN,
            requested_by_user_id=None,
            request_group_id=None,
            subject=None,
            requested_at=None,
            decided_at=None,
        )
    )
    await db.commit()
