"""
Relances par email — aperçu et envoi, par responsable ou en campagne.

Deux familles de routes coexistent.

`/relances/preferences/…` et `/relances/{id}/digest…` servent le moteur
courant : un récapitulatif unique, sectionné, adressé au responsable de
*suivi*, dont chacun règle la cadence et le contenu.

Les routes `/relances/{id}/preview` et `/relances/{id}/send` sont l'ancien
mécanisme : un rappel d'une seule nature adressé aux responsables de
réalisation. Elles ne sont plus planifiées mais restent appelables pour un
envoi exceptionnel.

Dans les deux cas, le principe est le même : on fournit l'identifiant d'un
responsable, et la route choisit elle-même les actions concernées. Aucune
liste d'actions n'est à transmettre — la sélection vient des mêmes vues métier
que l'API de consultation et les rapports (`services/action_queries`), ce qui
garantit qu'un mail ne parle jamais d'actions différentes de celles affichées
à l'écran.
"""

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_async_db
from app.models.project import (
    Action,
    RelanceLog,
    RelancePreference,
    Responsable,
)
from app.models.user import User
from app.schemas.relance_schema import (
    RelanceBatchOut,
    RelanceConfigOut,
    RelanceDigestBatchOut,
    RelanceDigestPreviewOut,
    RelanceDigestSendOut,
    RelancePreferenceOut,
    RelancePreferenceUpdate,
    RelancePreviewOut,
    RelanceSectionOut,
    RelanceSendOut,
    jours_en_lettres,
)
from app.services import outlook, relance_service
from app.services.action_queries import ActionView, build_actions_query, default_order
from app.services.digests import to_digest
from app.services.email_templates import RelanceKind, build_email
from app.services.relance_digest import Reglage
from app.services.scoping import responsable_ids_for
from app.services.security import (
    get_current_user,
    require_admin,
    require_reader,
    require_writer,
)

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
            "Renseigner l'email via PUT /responsables/{id}."
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
# Préférences d'envoi
#
# Routes littérales, déclarées avant `/{responsable_id}/…` : FastAPI résout
# dans l'ordre de déclaration, et `/relances/preferences` serait sinon capté
# par une route paramétrée puis rejeté comme UUID invalide.
# ---------------------------------------------------------------------------

def _preference_out(
    responsable: Responsable, reglage: Reglage
) -> RelancePreferenceOut:
    return RelancePreferenceOut(
        responsable_id=responsable.id,
        responsable_name=responsable.display_name,
        email=responsable.email,
        is_mapped=responsable.is_mapped,
        enabled=reglage.enabled,
        perimeter=reglage.perimeter,
        days_of_week=list(reglage.days_of_week),
        send_hour=reglage.send_hour,
        include_overdue=reglage.include_overdue,
        include_today=reglage.include_today,
        include_due_soon=reglage.include_due_soon,
        include_pending=reglage.include_pending,
        horizon_days=reglage.horizon_days,
        personnalise=reglage.personnalise,
        frequence_hebdomadaire=reglage.frequence_hebdomadaire,
        cadence=relance_service.cadence_lisible(reglage),
        jours_labels=jours_en_lettres(list(reglage.days_of_week)),
    )


async def _appliquer_preference(
    db: AsyncSession, responsable: Responsable, payload: RelancePreferenceUpdate
) -> Reglage:
    """Écrit les champs fournis, en créant la ligne si elle n'existe pas.

    La ligne n'est créée qu'au premier réglage : tant que personne n'a rien
    changé, l'absence d'enregistrement *est* l'information « valeurs par
    défaut ». Les pré-créer pour tous les responsables aurait figé les défauts
    du jour de la création, et un changement de politique n'aurait plus atteint
    personne.
    """
    result = await db.execute(
        select(RelancePreference).filter(
            RelancePreference.responsable_id == responsable.id
        )
    )
    preference = result.scalars().first()
    if preference is None:
        preference = RelancePreference(responsable_id=responsable.id)
        db.add(preference)

    modifications = payload.model_dump(exclude_unset=True)
    jours = modifications.pop("days_of_week", None)
    for champ, valeur in modifications.items():
        setattr(preference, champ, valeur)
    if jours is not None:
        preference.days_of_week = ",".join(str(j) for j in jours)

    await db.commit()
    await db.refresh(preference)
    return Reglage.depuis(preference)


async def _responsable_de_lappelant(db: AsyncSession, user: User) -> Responsable:
    """Fiche responsable rattachée au compte connecté.

    Le rapprochement se fait par email, comme pour le cloisonnement des
    données (`services/scoping`). Un compte sans fiche ne reçoit aucune
    relance : il n'a donc rien à régler, et le dire explicitement vaut mieux
    qu'un formulaire sans effet.
    """
    ids = await responsable_ids_for(db, user)
    if not ids:
        raise HTTPException(
            status_code=404,
            detail=(
                "Aucune fiche responsable n'est rattachée à votre compte : "
                "vous ne figurez dans aucune relance. Demander à un "
                "administrateur d'associer votre adresse à votre nom Excel."
            ),
        )
    # Une même personne peut porter plusieurs fiches (« AndryI » et
    # « Andry I ») : on règle la première par ordre alphabétique, celle que
    # `GET /relances/preferences` montrera en tête.
    result = await db.execute(
        select(Responsable)
        .filter(Responsable.id.in_(ids))
        .order_by(Responsable.display_name)
    )
    return result.scalars().first()


@router.get(
    "/preferences/me",
    response_model=RelancePreferenceOut,
    dependencies=[require_reader],
    summary="Mes réglages de relance",
    description=(
        "Réglages effectifs du compte connecté : jours d'envoi, heure, "
        "périmètre et sections retenues. Tant que rien n'a été réglé, les "
        "valeurs par défaut sont renvoyées et `personnalise` vaut `false`."
    ),
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Aucune fiche responsable rattachée à ce compte."},
    },
)
async def mes_preferences(
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    responsable = await _responsable_de_lappelant(db, user)
    reglage = await relance_service.reglage_async(db, responsable.id)
    return _preference_out(responsable, reglage)


@router.put(
    "/preferences/me",
    response_model=RelancePreferenceOut,
    dependencies=[require_reader],
    summary="Modifier mes réglages de relance",
    description=(
        "Modification partielle : seuls les champs envoyés changent.\n\n"
        "Accessible à tout compte authentifié, y compris en lecture seule — "
        "régler la fréquence de ses propres emails n'est pas une écriture sur "
        "le portefeuille, et l'alternative serait de subir la cadence par "
        "défaut ou de filtrer l'expéditeur."
    ),
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Aucune fiche responsable rattachée à ce compte."},
        422: {"description": "Jour ou heure hors bornes."},
    },
)
async def modifier_mes_preferences(
    payload: RelancePreferenceUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    responsable = await _responsable_de_lappelant(db, user)
    reglage = await _appliquer_preference(db, responsable, payload)
    return _preference_out(responsable, reglage)


@router.get(
    "/preferences",
    response_model=list[RelancePreferenceOut],
    dependencies=[require_admin],
    summary="Réglages de relance de tous les responsables",
    description=(
        "Un enregistrement par responsable disposant d'une adresse email, "
        "réglages effectifs compris — les valeurs par défaut apparaissent pour "
        "ceux qui n'ont rien configuré.\n\n"
        "Réservé aux administrateurs : c'est la vue qui expose la cadence de "
        "toute la DSI."
    ),
    responses=AUTH_RESPONSES,
)
async def lister_preferences(
    tous: bool = Query(
        False,
        description=(
            "Inclure les responsables sans adresse email. Ils ne reçoivent "
            "rien : utile pour repérer qui reste à mapper."
        ),
    ),
    db: AsyncSession = Depends(get_async_db),
):
    stmt = (
        select(Responsable, RelancePreference)
        .outerjoin(
            RelancePreference, RelancePreference.responsable_id == Responsable.id
        )
        .order_by(Responsable.display_name)
    )
    if not tous:
        stmt = stmt.filter(
            Responsable.is_mapped.is_(True), Responsable.email.isnot(None)
        )
    result = await db.execute(stmt)
    return [
        _preference_out(responsable, Reglage.depuis(preference))
        for responsable, preference in result.all()
    ]


@router.put(
    "/preferences/{responsable_id}",
    response_model=RelancePreferenceOut,
    dependencies=[require_admin],
    summary="Modifier les réglages d'un responsable",
    description=(
        "Même sémantique que `/preferences/me`, mais pour n'importe quelle "
        "fiche. Réservé aux administrateurs."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Responsable introuvable."}},
)
async def modifier_preferences(
    payload: RelancePreferenceUpdate,
    responsable_id: uuid.UUID = Path(..., description="Identifiant du responsable."),
    db: AsyncSession = Depends(get_async_db),
):
    responsable = await _charger_responsable(db, responsable_id)
    reglage = await _appliquer_preference(db, responsable, payload)
    return _preference_out(responsable, reglage)


# ---------------------------------------------------------------------------
# Récapitulatif : aperçu, envoi unitaire, campagne
# ---------------------------------------------------------------------------

def _sections_out(sections) -> list[RelanceSectionOut]:
    return [
        RelanceSectionOut(
            key=spec.key,
            label=spec.label,
            intro=spec.intro,
            action_count=len(actions),
            actions=actions,
        )
        for spec, actions in sections
    ]


async def _preparer_digest(
    db: AsyncSession, responsable: Responsable, *, ignorer_desactivation: bool = False
):
    reglage = await relance_service.reglage_async(db, responsable.id)
    sections = await relance_service.sections_async(db, reglage, responsable.id)
    message = relance_service.construire_message(responsable, reglage, sections)
    motif = relance_service.motif_de_blocage(
        responsable, reglage, sections, ignorer_desactivation=ignorer_desactivation
    )
    return reglage, sections, message, motif


@router.post(
    "/digests/send",
    response_model=RelanceDigestBatchOut,
    dependencies=[require_admin],
    summary="Envoyer les récapitulatifs à tout le monde, sans attendre le créneau",
    description=(
        "Parcourt les responsables joignables et envoie à chacun son "
        "récapitulatif, selon ses propres réglages de contenu — mais sans "
        "tenir compte de ses jours et de son heure d'envoi.\n\n"
        "À réserver aux envois exceptionnels, la veille d'un comité de "
        "pilotage par exemple : la cadence normale est assurée par le "
        "planificateur, et doubler un envoi automatique est le meilleur moyen "
        "de faire filtrer l'expéditeur.\n\n"
        "`dry_run=true` calcule tout sans rien expédier ni tracer."
    ),
    responses=AUTH_RESPONSES,
)
async def envoyer_digests(
    dry_run: bool = Query(
        False,
        description="Tout calculer sans rien envoyer ni enregistrer — pour vérifier le périmètre.",
    ),
    respecter_desactivation: bool = Query(
        True,
        description=(
            "Laisser de côté les personnes ayant coupé leurs relances "
            "(`enabled: false`). Le passer à `false` outrepasse un choix "
            "explicite : à n'utiliser que sur consigne."
        ),
    ),
    db: AsyncSession = Depends(get_async_db),
):
    resultats: list[RelanceDigestSendOut] = []

    # `heure=None` : la campagne ignore les créneaux, c'est sa raison d'être.
    for responsable, _ in await relance_service.candidats_async(db, None):
        reglage, sections, message, motif = await _preparer_digest(
            db, responsable, ignorer_desactivation=not respecter_desactivation
        )

        # Une personne ayant coupé ses relances est écartée sans figurer au
        # rapport : elle n'est pas « en échec », elle a fait un choix.
        if not reglage.enabled and respecter_desactivation:
            continue
        if relance_service.total_actions(sections) == 0:
            # Personne à relancer : on n'encombre pas le rapport.
            continue

        if dry_run:
            resultats.append(
                RelanceDigestSendOut(
                    responsable_id=responsable.id,
                    responsable_name=responsable.display_name,
                    email=responsable.email,
                    status="skipped" if motif else "simulated",
                    action_count=message.action_count,
                    detail=motif or "Simulation demandée (dry_run=true).",
                )
            )
            continue

        resultats.append(
            await _envoyer_digest(db, responsable, message, sections, motif)
        )

    return RelanceDigestBatchOut(
        generated_at=datetime.now(timezone.utc),
        mode=outlook.send_mode().value,
        considered=len(resultats),
        sent=sum(1 for r in resultats if r.status == "sent"),
        simulated=sum(1 for r in resultats if r.status == "simulated"),
        failed=sum(1 for r in resultats if r.status == "failed"),
        skipped=sum(1 for r in resultats if r.status.startswith("skipped")),
        results=resultats,
    )


async def _envoyer_digest(
    db: AsyncSession, responsable, message, sections, motif
) -> RelanceDigestSendOut:
    if motif is not None:
        return RelanceDigestSendOut(
            responsable_id=responsable.id,
            responsable_name=responsable.display_name,
            email=responsable.email,
            status="skipped",
            action_count=message.action_count,
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
        ids = relance_service.ids_actions(sections)
        log = RelanceLog(
            responsable_id=responsable.id,
            action_ids=",".join(str(i) for i in ids),
            email_status=resultat.status.value,
            kind=relance_service.KIND_DIGEST,
            action_count=len(ids),
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)

    return RelanceDigestSendOut(
        responsable_id=responsable.id,
        responsable_name=responsable.display_name,
        email=responsable.email,
        status=resultat.status.value,
        action_count=message.action_count,
        detail=resultat.detail,
        relance_log_id=log.id if log else None,
    )


@router.get(
    "/{responsable_id}/digest",
    response_model=RelanceDigestPreviewOut,
    dependencies=[require_writer],
    summary="Aperçu du récapitulatif d'un responsable",
    description=(
        "Construit le message qui partirait au prochain créneau, avec ses "
        "sections et le corps HTML complet. Rien n'est expédié et aucune trace "
        "n'est enregistrée."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Responsable introuvable."}},
)
async def apercu_digest(
    responsable_id: uuid.UUID = Path(..., description="Identifiant du responsable."),
    db: AsyncSession = Depends(get_async_db),
):
    responsable = await _charger_responsable(db, responsable_id)
    reglage, sections, message, motif = await _preparer_digest(db, responsable)
    maintenant = datetime.now(ZoneInfo(settings.relance_timezone))

    return RelanceDigestPreviewOut(
        responsable_id=responsable.id,
        responsable_name=responsable.display_name,
        email=responsable.email,
        is_mapped=responsable.is_mapped,
        preference=_preference_out(responsable, reglage),
        subject=message.subject,
        action_count=message.action_count,
        sections=_sections_out(sections),
        html=message.html,
        text=message.text,
        would_send=motif is None,
        skip_reason=motif,
        next_send_at=reglage.prochain_creneau(maintenant),
    )


@router.get(
    "/{responsable_id}/digest.html",
    response_class=HTMLResponse,
    dependencies=[require_writer],
    summary="Aperçu du récapitulatif rendu dans le navigateur",
    description=(
        "Renvoie directement le corps du mail, pour le relire en conditions "
        "réelles. Le gabarit est construit en tableaux et styles en ligne, "
        "contrainte du moteur de rendu d'Outlook."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Responsable introuvable."}},
)
async def apercu_digest_html(
    responsable_id: uuid.UUID = Path(..., description="Identifiant du responsable."),
    db: AsyncSession = Depends(get_async_db),
):
    responsable = await _charger_responsable(db, responsable_id)
    _, _, message, _ = await _preparer_digest(db, responsable)
    return HTMLResponse(content=message.html)


@router.post(
    "/{responsable_id}/digest/send",
    response_model=RelanceDigestSendOut,
    dependencies=[require_writer],
    summary="Envoyer le récapitulatif à un responsable",
    description=(
        "Envoi immédiat, sans attendre le créneau de la personne. Le contenu "
        "reste celui de ses réglages.\n\n"
        "Si la configuration Azure est incomplète, l'envoi est simulé et le "
        "statut renvoyé vaut `simulated` — la trace `RelanceLog` distingue les "
        "deux."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Responsable introuvable."}},
)
async def envoyer_digest(
    responsable_id: uuid.UUID = Path(..., description="Identifiant du responsable."),
    db: AsyncSession = Depends(get_async_db),
):
    responsable = await _charger_responsable(db, responsable_id)
    _, sections, message, motif = await _preparer_digest(db, responsable)
    return await _envoyer_digest(db, responsable, message, sections, motif)


# ---------------------------------------------------------------------------
# Rappels ponctuels par nature (hérité)
#
# Ces routes précèdent le récapitulatif : elles envoient un message d'une
# seule nature à un responsable de *réalisation*. Elles ne sont plus
# planifiées — le récapitulatif les couvre — mais restent utiles pour un envoi
# ciblé et exceptionnel.
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
