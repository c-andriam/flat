"""
Relances par email — aperçu et envoi, par responsable ou en campagne.

Le principe demandé : on fournit l'identifiant d'un responsable, et la route
choisit elle-même les actions concernées. `/relances/{id}/retard` sélectionne
ses actions en retard, `/relances/{id}/jour-j` celles dues aujourd'hui,
`/relances/{id}/echeances-proches` celles dont la date approche. Aucune liste
d'actions n'est à transmettre : la sélection vient des mêmes vues métier que
l'API de consultation et les rapports (`services/action_queries`), ce qui
garantit qu'un mail ne parle jamais d'actions différentes de celles affichées
à l'écran.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_async_db
from app.models.project import Action, RelanceLog, Responsable
from app.schemas.relance_schema import (
    RelanceBatchOut,
    RelanceConfigOut,
    RelancePreviewOut,
    RelanceSendOut,
)
from app.services import outlook
from app.services.action_queries import ActionView, build_actions_query, default_order
from app.services.digests import to_digest
from app.services.email_templates import RelanceKind, build_email
from app.services.security import require_admin, require_writer

router = APIRouter(prefix="/relances", tags=["relances"])

AUTH_RESPONSES = {
    401: {"description": "Jeton absent, invalide ou expiré."},
    403: {"description": "Rôle insuffisant pour cette opération."},
}

# Chaque nature de rappel s'appuie sur la vue métier correspondante.
_VUE_PAR_NATURE: dict[RelanceKind, ActionView] = {
    RelanceKind.OVERDUE: ActionView.OVERDUE,
    RelanceKind.TODAY: ActionView.TODAY,
    RelanceKind.DUE_SOON: ActionView.DUE_SOON,
}


async def _charger_responsable(db: AsyncSession, responsable_id: uuid.UUID) -> Responsable:
    result = await db.execute(select(Responsable).filter(Responsable.id == responsable_id))
    responsable = result.scalars().first()
    if not responsable:
        raise HTTPException(status_code=404, detail="Responsable introuvable")
    return responsable


async def _actions_du_responsable(
    db: AsyncSession, responsable_id: uuid.UUID, kind: RelanceKind
) -> list[Action]:
    stmt = build_actions_query(
        view=_VUE_PAR_NATURE[kind],
        responsable_id=responsable_id,
        # Un projet archivé ne doit plus déclencher de relance.
        active_projects_only=True,
        due_soon_days=settings.relance_horizon_days,
    )
    stmt = default_order(stmt).options(
        selectinload(Action.responsables), selectinload(Action.project)
    )
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def _derniere_relance(db: AsyncSession, responsable_id: uuid.UUID) -> datetime | None:
    result = await db.execute(
        select(func.max(RelanceLog.sent_at)).filter(
            RelanceLog.responsable_id == responsable_id
        )
    )
    return result.scalar_one_or_none()


def _en_periode_de_silence(derniere: datetime | None) -> bool:
    """Le beat tourne tous les jours ; sans ce délai, un responsable reçoit
    un rappel quotidien tant qu'une action reste ouverte."""
    if derniere is None:
        return False
    seuil = datetime.now(timezone.utc) - timedelta(days=settings.relance_cooldown_days)
    # `sent_at` est stocké sans fuseau : on le compare en UTC naïf.
    return derniere.replace(tzinfo=timezone.utc) >= seuil if derniere.tzinfo is None else derniere >= seuil


async def _preparer(
    db: AsyncSession, responsable_id: uuid.UUID, kind: RelanceKind, ignorer_silence: bool
):
    responsable = await _charger_responsable(db, responsable_id)
    actions = await _actions_du_responsable(db, responsable_id, kind)
    digests = [to_digest(a) for a in actions]
    message = build_email(
        kind,
        responsable.display_name,
        digests,
        app_url=f"{settings.frontend_url}/actions",
    )

    motif = None
    if not digests:
        motif = "Aucune action ne correspond à cette relance."
    elif not (responsable.is_mapped and responsable.email):
        motif = (
            "Responsable non mappé : aucune adresse email associée. "
            "Renseigner l'email via PATCH /responsables/{id}."
        )
    elif not ignorer_silence and _en_periode_de_silence(await _derniere_relance(db, responsable_id)):
        motif = (
            f"Relance déjà envoyée il y a moins de {settings.relance_cooldown_days} "
            "jours. Utiliser `force=true` pour passer outre."
        )

    return responsable, digests, message, motif


# ---------------------------------------------------------------------------
# Configuration (routes littérales déclarées avant les routes paramétrées)
# ---------------------------------------------------------------------------

@router.get(
    "/config",
    response_model=RelanceConfigOut,
    dependencies=[require_writer],
    summary="État de la configuration d'envoi",
    description=(
        "Indique si les emails partent réellement ou sont seulement simulés, "
        "et ce qui manque le cas échéant. À consulter en premier quand une "
        "campagne ne produit aucun message dans les boîtes."
    ),
    responses=AUTH_RESPONSES,
)
async def relance_config():
    return RelanceConfigOut(
        mode=outlook.send_mode().value,
        explanation=outlook.mode_explanation(),
        sender=outlook.sender_upn(),
        cooldown_days=settings.relance_cooldown_days,
        horizon_days=settings.relance_horizon_days,
    )


# ---------------------------------------------------------------------------
# Aperçu et envoi pour un responsable
# ---------------------------------------------------------------------------

_KIND_PARAM = Query(
    RelanceKind.OVERDUE,
    description=(
        "Nature du rappel : `overdue` (actions en retard), `today` (échéance "
        "au jour même), `due_soon` (échéance proche)."
    ),
)


@router.get(
    "/{responsable_id}/preview",
    response_model=RelancePreviewOut,
    dependencies=[require_writer],
    summary="Aperçu d'une relance (sans envoi)",
    description=(
        "Construit le message qui serait envoyé au responsable, avec la liste "
        "des actions retenues et le corps HTML complet. Rien n'est expédié et "
        "aucune trace n'est enregistrée."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Responsable introuvable."}},
)
async def preview_relance(
    responsable_id: uuid.UUID = Path(..., description="Identifiant du responsable."),
    kind: RelanceKind = _KIND_PARAM,
    force: bool = Query(False, description="Ignorer la période de silence dans l'évaluation."),
    db: AsyncSession = Depends(get_async_db),
):
    responsable, digests, message, motif = await _preparer(db, responsable_id, kind, force)
    return RelancePreviewOut(
        responsable_id=responsable.id,
        responsable_name=responsable.display_name,
        email=responsable.email,
        is_mapped=responsable.is_mapped,
        kind=kind,
        subject=message.subject,
        action_count=message.action_count,
        actions=digests,
        html=message.html,
        text=message.text,
        would_send=motif is None,
        skip_reason=motif,
    )


@router.get(
    "/{responsable_id}/preview.html",
    response_class=HTMLResponse,
    dependencies=[require_writer],
    summary="Aperçu du rendu HTML dans le navigateur",
    description=(
        "Renvoie directement le corps du mail, pour le relire en conditions "
        "réelles avant une campagne. Le gabarit est construit en tableaux et "
        "styles en ligne, contrainte du moteur de rendu d'Outlook."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Responsable introuvable."}},
)
async def preview_relance_html(
    responsable_id: uuid.UUID = Path(..., description="Identifiant du responsable."),
    kind: RelanceKind = _KIND_PARAM,
    db: AsyncSession = Depends(get_async_db),
):
    _, _, message, _ = await _preparer(db, responsable_id, kind, True)
    return HTMLResponse(content=message.html)


@router.post(
    "/{responsable_id}/send",
    response_model=RelanceSendOut,
    dependencies=[require_writer],
    summary="Envoyer la relance à un responsable",
    description=(
        "Sélectionne automatiquement les actions correspondant à la nature du "
        "rappel, construit le message et l'envoie via Microsoft Graph. Si la "
        "configuration Azure est incomplète, l'envoi est simulé et le statut "
        "renvoyé vaut `simulated` — la trace `RelanceLog` distingue les deux."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Responsable introuvable."}},
)
async def send_relance(
    responsable_id: uuid.UUID = Path(..., description="Identifiant du responsable."),
    kind: RelanceKind = _KIND_PARAM,
    force: bool = Query(False, description="Envoyer même si la période de silence n'est pas écoulée."),
    db: AsyncSession = Depends(get_async_db),
):
    responsable, digests, message, motif = await _preparer(db, responsable_id, kind, force)
    return await _envoyer(db, responsable, digests, message, kind, motif)


async def _envoyer(db, responsable, digests, message, kind, motif) -> RelanceSendOut:
    if motif is not None:
        return RelanceSendOut(
            responsable_id=responsable.id,
            responsable_name=responsable.display_name,
            email=responsable.email,
            kind=kind,
            status="skipped",
            action_count=len(digests),
            detail=motif,
        )

    resultat = outlook.send_email(
        to=responsable.email,
        subject=message.subject,
        html_body=message.html,
        text_body=message.text,
    )

    log = None
    if resultat.ok:
        # Trace d'audit : quelles actions, à qui, quand. Elle sert aussi de
        # base à la période de silence.
        log = RelanceLog(
            responsable_id=responsable.id,
            action_ids=",".join(str(d.id) for d in digests),
            email_status=resultat.status.value,
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)

    return RelanceSendOut(
        responsable_id=responsable.id,
        responsable_name=responsable.display_name,
        email=responsable.email,
        kind=kind,
        status=resultat.status.value,
        action_count=len(digests),
        detail=resultat.detail,
        relance_log_id=log.id if log else None,
    )


@router.post(
    "/send",
    response_model=RelanceBatchOut,
    dependencies=[require_admin],
    summary="Campagne de relance sur tous les responsables",
    description=(
        "Parcourt les responsables disposant d'une adresse email, sélectionne "
        "pour chacun ses actions correspondant à la nature du rappel, et "
        "envoie un message consolidé — un seul email par personne, pas un par "
        "action.\n\n"
        "Réservé aux administrateurs : une campagne touche toute la DSI."
    ),
    responses=AUTH_RESPONSES,
)
async def send_batch(
    kind: RelanceKind = _KIND_PARAM,
    force: bool = Query(False, description="Ignorer la période de silence."),
    dry_run: bool = Query(
        False,
        description="Tout calculer sans rien envoyer ni enregistrer — pour vérifier le périmètre.",
    ),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(Responsable)
        .filter(Responsable.is_mapped.is_(True), Responsable.email.isnot(None))
        .order_by(Responsable.display_name)
    )
    responsables = list(result.scalars().all())

    resultats: list[RelanceSendOut] = []
    for responsable in responsables:
        _, digests, message, motif = await _preparer(db, responsable.id, kind, force)
        if not digests:
            # Personne à relancer : on n'encombre pas le rapport.
            continue
        if dry_run:
            resultats.append(
                RelanceSendOut(
                    responsable_id=responsable.id,
                    responsable_name=responsable.display_name,
                    email=responsable.email,
                    kind=kind,
                    status="skipped" if motif else "simulated",
                    action_count=len(digests),
                    detail=motif or "Simulation demandée (dry_run=true).",
                )
            )
            continue
        resultats.append(await _envoyer(db, responsable, digests, message, kind, motif))

    return RelanceBatchOut(
        generated_at=datetime.now(timezone.utc),
        kind=kind,
        mode=outlook.send_mode().value,
        considered=len(resultats),
        sent=sum(1 for r in resultats if r.status == "sent"),
        simulated=sum(1 for r in resultats if r.status == "simulated"),
        failed=sum(1 for r in resultats if r.status == "failed"),
        skipped=sum(1 for r in resultats if r.status.startswith("skipped")),
        results=resultats,
    )
