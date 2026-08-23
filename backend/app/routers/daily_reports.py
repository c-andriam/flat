"""
Rapports de fin de journée.

Chacun déclare ce qu'il a fait dans la journée. Les actions qui le concernent
sont proposées automatiquement — échéance du jour, action touchée aujourd'hui,
ou travail resté en cours depuis la veille — et il ajoute ce qui n'a pas de
numéro d'action : réunions, dépannages, imprévus.

Cocher « terminée » sur une ligne issue d'une suggestion porte l'action à
100 %. C'est le point de tout le dispositif : sans ce couplage, la même
information se saisit à deux endroits, et au bout de quelques semaines les deux
ne coïncident plus — c'est alors le rapport qu'on abandonne.

Confidentialité : chacun lit ses propres rapports, le DSIO et les
administrateurs lisent tout, comme pour les projets et les actions.
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_db
from app.models.daily_report import DailyReport, DailyReportItem, ReportItemSource
from app.models.project import Action, Project
from app.models.user import User
from app.schemas.daily_report_schema import (
    DailyReportIn,
    DailyReportOut,
    ReportSuggestionOut,
    SuggestionReason,
    TodayReportOut,
)
from app.services.action_rules import apply_indicators
from app.services.events import publish_event
from app.services.scoping import Scope, get_scope, sees_all_data
from app.services.security import get_current_user, require_reader

router = APIRouter(prefix="/daily-reports", tags=["rapports quotidiens"])

AUTH_RESPONSES = {
    401: {"description": "Jeton absent, invalide ou expiré."},
    403: {"description": "Rôle insuffisant pour cette opération."},
}

#: Fuseau métier. La date d'un rapport est celle que voit la personne, pas
#: celle d'UTC : à 22 h à Antananarivo, UTC est déjà passé au lendemain et le
#: rapport aurait porté la mauvaise date.
_MG_TZ = timezone(timedelta(hours=3))

#: Nombre maximal de suggestions. Au-delà, la liste cesse d'aider.
_MAX_SUGGESTIONS = 25


def today_local() -> date:
    return datetime.now(_MG_TZ).date()


def _debut_de_journee_utc(jour: date) -> datetime:
    """Minuit local du jour, exprimé en UTC."""
    return datetime.combine(jour, time.min, tzinfo=_MG_TZ).astimezone(timezone.utc)


def _to_out(rapport: DailyReport, nom: str | None = None) -> DailyReportOut:
    sortie = DailyReportOut.model_validate(rapport)
    sortie.user_display_name = nom
    return sortie


async def _charger(
    db: AsyncSession, user_id: uuid.UUID, jour: date
) -> DailyReport | None:
    result = await db.execute(
        select(DailyReport)
        .options(selectinload(DailyReport.items))
        .where(DailyReport.user_id == user_id, DailyReport.report_date == jour)
    )
    return result.scalars().first()


async def _suggestions(
    db: AsyncSession, scope: Scope, jour: date, deja_reprises: set[uuid.UUID]
) -> list[ReportSuggestionOut]:
    """Actions à proposer pour la journée.

    Trois motifs cumulables. Ne retenir que l'échéance du jour laisserait de
    côté le travail fait en avance ou en rattrapage — c'est-à-dire l'essentiel
    d'une journée réelle.
    """
    condition = scope.actions()
    if condition is None:
        # Un compte qui voit tout n'a pas d'actions « à lui » : sans fiche
        # responsable rattachée, il n'y a rien de pertinent à proposer.
        if not scope.responsable_ids:
            return []
        condition = None

    stmt = (
        select(Action)
        .options(selectinload(Action.project))
        .where(Action.progress < 100.0)
    )
    if condition is not None:
        stmt = stmt.where(condition)

    debut = _debut_de_journee_utc(jour)
    fin = debut + timedelta(days=1)

    result = await db.execute(stmt.order_by(Action.deadline.nulls_last(), Action.numero))
    candidates = list(result.scalars().unique().all())

    propositions: list[ReportSuggestionOut] = []
    for action in candidates:
        motifs: list[SuggestionReason] = []
        if action.deadline == jour:
            motifs.append(
                SuggestionReason(code="deadline_today", label="Échéance aujourd'hui")
            )
        if action.updated_at is not None and debut <= action.updated_at < fin:
            motifs.append(
                SuggestionReason(code="touched_today", label="Modifiée aujourd'hui")
            )
        if 0.0 < (action.progress or 0.0) < 100.0 and not motifs:
            motifs.append(SuggestionReason(code="carry_over", label="En cours"))

        if not motifs:
            continue
        propositions.append(
            ReportSuggestionOut(
                action_id=action.id,
                numero=action.numero,
                description=action.description,
                project_code=action.project.code if action.project else None,
                progress=action.progress or 0.0,
                deadline=action.deadline,
                reasons=motifs,
                already_added=action.id in deja_reprises,
            )
        )

    # L'échéance du jour d'abord, l'activité ensuite, le reste après : c'est
    # l'ordre dans lequel on se remémore sa journée.
    priorite = {"deadline_today": 0, "touched_today": 1, "carry_over": 2}
    propositions.sort(
        key=lambda item: (
            min(priorite.get(motif.code, 9) for motif in item.reasons),
            item.numero,
        )
    )
    return propositions[:_MAX_SUGGESTIONS]


@router.get(
    "/today",
    response_model=TodayReportOut,
    dependencies=[require_reader],
    summary="Rapport du jour et suggestions",
    description=(
        "Renvoie le rapport de la date demandée — vide s'il n'existe pas "
        "encore — accompagné des actions à proposer. Les deux en un seul "
        "appel : deux allers-retours séquentiels se verraient à l'ouverture "
        "de l'écran."
    ),
    responses=AUTH_RESPONSES,
)
async def report_of_day(
    day: date | None = Query(
        None, description="Date du rapport. Par défaut, aujourd'hui en heure locale."
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    scope: Scope = Depends(get_scope),
):
    jour = day or today_local()
    rapport = await _charger(db, current_user.id, jour)
    deja = {item.action_id for item in (rapport.items if rapport else []) if item.action_id}

    return TodayReportOut(
        report_date=jour,
        report=_to_out(rapport, current_user.display_name) if rapport else None,
        suggestions=await _suggestions(db, scope, jour, deja),
        has_content=bool(rapport and (rapport.items or rapport.note)),
    )


@router.put(
    "/{day}",
    response_model=DailyReportOut,
    dependencies=[require_reader],
    summary="Enregistrer le rapport d'une journée",
    description=(
        "Remplace intégralement le contenu du rapport. Les lignes issues "
        "d'une action et cochées « terminée » portent cette action à 100 % : "
        "une seule saisie met à jour les deux.\n\n"
        "Un rapport ne se modifie que le jour même — le lendemain, il devient "
        "une trace figée."
    ),
    responses={
        **AUTH_RESPONSES,
        409: {"description": "Journée close : le rapport n'est plus modifiable."},
    },
)
async def save_report(
    payload: DailyReportIn,
    day: date = Path(..., description="Date du rapport."),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    scope: Scope = Depends(get_scope),
):
    if day != today_local():
        # Rouvrir un rapport passé permettrait de réécrire l'histoire, et
        # ôterait au rapport sa valeur de trace.
        raise HTTPException(
            status_code=409,
            detail=(
                f"Le rapport du {day:%d/%m/%Y} n'est plus modifiable : "
                "un rapport se remplit le jour même."
            ),
        )

    rapport = await _charger(db, current_user.id, day)
    if rapport is None:
        rapport = DailyReport(user_id=current_user.id, report_date=day)
        db.add(rapport)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Un rapport vient d'être créé pour cette journée. Rafraîchissez.",
            )

    # Les actions que l'appelant a le droit de piloter : une ligne pointant
    # vers l'action d'un tiers ne doit pas pouvoir la passer à 100 %.
    ids_actions = {item.action_id for item in payload.items if item.action_id}
    autorisees: dict[uuid.UUID, Action] = {}
    if ids_actions:
        stmt = select(Action).where(Action.id.in_(ids_actions))
        condition = scope.actions()
        if condition is not None:
            stmt = stmt.where(condition)
        result = await db.execute(stmt)
        autorisees = {action.id: action for action in result.scalars().all()}

    # Suppression puis réinsertion par instructions explicites, sans passer
    # par la collection `rapport.items` : sur un rapport qui vient d'être
    # inséré, y toucher déclenche un chargement paresseux hors du contexte
    # asynchrone — l'erreur `MissingGreenlet`.
    await db.execute(delete(DailyReportItem).where(DailyReportItem.report_id == rapport.id))

    for position, entree in enumerate(payload.items):
        action_id = entree.action_id if entree.action_id in autorisees else None
        db.add(
            DailyReportItem(
                report_id=rapport.id,
                action_id=action_id,
                source=ReportItemSource.ACTION if action_id else ReportItemSource.MANUAL,
                label=entree.label,
                done=entree.done,
                position=position,
            )
        )
        if action_id and entree.done:
            action = autorisees[action_id]
            if (action.progress or 0.0) < 100.0:
                action.progress = 100.0
                # Statut, date de réalisation et indicateurs se déduisent de
                # l'avancement : même chemin que la mise à jour d'une action,
                # pour que les deux écrans produisent le même résultat.
                apply_indicators(action, manage_date_realisation=True)

    rapport.note = payload.note
    rapport.updated_at = datetime.now(timezone.utc)

    await db.commit()

    if any(entree.done and entree.action_id in autorisees for entree in payload.items):
        # Des actions ont changé : les compteurs et rapports en cache doivent
        # être recalculés.
        await publish_event(
            "action_updated",
            {"source": "daily_report", "user_id": current_user.id},
        )

    enregistre = await _charger(db, current_user.id, day)
    if enregistre is None:
        raise HTTPException(status_code=500, detail="Rapport introuvable après enregistrement.")
    return _to_out(enregistre, current_user.display_name)


@router.post(
    "/{day}/submit",
    response_model=DailyReportOut,
    dependencies=[require_reader],
    summary="Clore le rapport de la journée",
    description="Horodate le rapport comme terminé. Le contenu reste modifiable le jour même.",
    responses={**AUTH_RESPONSES, 404: {"description": "Aucun rapport pour cette date."}},
)
async def submit_report(
    day: date = Path(..., description="Date du rapport."),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    rapport = await _charger(db, current_user.id, day)
    if rapport is None:
        raise HTTPException(status_code=404, detail="Aucun rapport pour cette date.")
    rapport.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    # Rechargé plutôt que rafraîchi : `refresh` ne recharge pas les relations,
    # et la sérialisation a besoin des lignes.
    enregistre = await _charger(db, current_user.id, day)
    return _to_out(enregistre or rapport, current_user.display_name)


@router.get(
    "",
    response_model=list[DailyReportOut],
    dependencies=[require_reader],
    summary="Historique des rapports",
    description=(
        "Rapports d'une période. Chacun ne voit que les siens ; le DSIO et "
        "les administrateurs voient ceux de tout le monde."
    ),
    responses=AUTH_RESPONSES,
)
async def list_reports(
    from_: date = Query(..., alias="from", description="Premier jour inclus."),
    to: date = Query(..., description="Dernier jour inclus."),
    user_id: uuid.UUID | None = Query(
        None, description="Filtrer sur un compte — réservé au DSIO et aux admins."
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    if to < from_:
        raise HTTPException(status_code=422, detail="`to` doit suivre `from`.")

    stmt = (
        select(DailyReport, User.display_name)
        .join(User, User.id == DailyReport.user_id)
        .options(selectinload(DailyReport.items))
        .where(DailyReport.report_date >= from_, DailyReport.report_date <= to)
    )
    if sees_all_data(current_user):
        if user_id is not None:
            stmt = stmt.where(DailyReport.user_id == user_id)
    else:
        # Le filtre est appliqué en base, pas à la sérialisation : masquer les
        # champs d'une ligne qu'on n'aurait pas dû renvoyer laisse quand même
        # fuiter son existence.
        stmt = stmt.where(DailyReport.user_id == current_user.id)

    result = await db.execute(
        stmt.order_by(DailyReport.report_date.desc(), User.display_name)
    )
    return [_to_out(rapport, nom) for rapport, nom in result.all()]


@router.delete(
    "/{day}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_reader],
    summary="Supprimer son rapport du jour",
    responses={**AUTH_RESPONSES, 404: {"description": "Aucun rapport pour cette date."}},
)
async def delete_report(
    day: date = Path(..., description="Date du rapport."),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    rapport = await _charger(db, current_user.id, day)
    if rapport is None:
        raise HTTPException(status_code=404, detail="Aucun rapport pour cette date.")
    if day != today_local():
        raise HTTPException(
            status_code=409, detail="Un rapport passé ne peut plus être supprimé."
        )
    await db.delete(rapport)
    await db.commit()
