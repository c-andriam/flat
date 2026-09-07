"""
Paramétrage : listes administrables et gabarits de création.

Ce qui relevait du code relève désormais de l'administration. Ajouter une
salle de réunion, renommer une catégorie d'action ou définir le squelette d'un
projet type ne demande plus ni migration ni déploiement.

La frontière est explicite : on administre les *valeurs* des listes, pas leurs
*types*. Un type de liste n'a de sens que si du code le consomme — proposer
d'en créer produirait des listes que rien ne lit. C'est la même règle que dans
GLPI, où les intitulés de dropdown sont libres et les dropdowns eux-mêmes
fixés par l'application.

Lecture ouverte à tout compte authentifié : les formulaires de création en ont
besoin. Écriture réservée aux administrateurs — une liste de valeurs et un
gabarit s'appliquent à toute la DSI.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_db
from app.models.gabarit import Gabarit, GabaritAction, GabaritEntite
from app.models.referentiel import REFERENTIEL_LABELS, Referentiel, ReferentielType
from app.schemas.parametrage_schema import (
    ChampsGabaritOut,
    GabaritCreate,
    GabaritOut,
    GabaritUpdate,
    ReferentielCreate,
    ReferentielListeOut,
    ReferentielOut,
    ReferentielUpdate,
)
from app.services import gabarits as service_gabarits
from app.services.security import require_admin, require_reader

router = APIRouter(tags=["paramétrage"])

AUTH_RESPONSES = {
    401: {"description": "Jeton absent, invalide ou expiré."},
    403: {"description": "Rôle insuffisant pour cette opération."},
}


# ---------------------------------------------------------------------------
# Référentiels
# ---------------------------------------------------------------------------

@router.get(
    "/referentiels",
    response_model=list[ReferentielListeOut],
    dependencies=[require_reader],
    summary="Toutes les listes administrables et leurs valeurs",
    description=(
        "Renvoie chaque liste avec ses valeurs, triées par position. Les "
        "listes vides sont incluses : c'est ce qui permet à l'écran "
        "d'administration de les afficher avant qu'on les remplisse.\n\n"
        "Un seul appel plutôt qu'un par liste — les formulaires de création "
        "en ont besoin de plusieurs à la fois, et quatre allers-retours sur "
        "une base distante coûtent plus que la réponse elle-même."
    ),
    responses=AUTH_RESPONSES,
)
async def lister_referentiels(
    inclure_inactifs: bool = Query(
        False,
        description=(
            "Inclure les valeurs désactivées. Faux pour un formulaire de "
            "saisie, vrai pour l'écran d'administration."
        ),
    ),
    db: AsyncSession = Depends(get_async_db),
):
    stmt = select(Referentiel).order_by(
        Referentiel.type, Referentiel.position, Referentiel.label
    )
    if not inclure_inactifs:
        stmt = stmt.filter(Referentiel.is_active.is_(True))

    valeurs = list((await db.execute(stmt)).scalars().all())

    par_type: dict[str, list[Referentiel]] = {}
    for valeur in valeurs:
        par_type.setdefault(valeur.type, []).append(valeur)

    return [
        ReferentielListeOut(
            type=type_liste,
            label=REFERENTIEL_LABELS[type_liste],
            values=par_type.get(type_liste.value, []),
        )
        for type_liste in ReferentielType
    ]


@router.post(
    "/referentiels",
    response_model=ReferentielOut,
    status_code=201,
    dependencies=[require_admin],
    summary="Ajouter une valeur à une liste",
    responses={
        **AUTH_RESPONSES,
        409: {"description": "Ce code existe déjà dans cette liste."},
    },
)
async def creer_referentiel(
    payload: ReferentielCreate, db: AsyncSession = Depends(get_async_db)
):
    valeur = Referentiel(**payload.model_dump(exclude={"type"}), type=payload.type.value)
    db.add(valeur)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"Le code « {payload.code} » existe déjà dans la liste "
                f"« {REFERENTIEL_LABELS[payload.type]} »."
            ),
        )
    await db.refresh(valeur)
    return valeur


@router.put(
    "/referentiels/{referentiel_id}",
    response_model=ReferentielOut,
    dependencies=[require_admin],
    summary="Modifier une valeur de liste",
    description=(
        "Modification partielle. Ni le type ni le code ne sont modifiables : "
        "déplacer une valeur d'une liste à l'autre, ou renommer son "
        "identifiant, romprait les rattachements existants sans qu'aucun ne "
        "le signale. Le libellé, lui, se change librement — c'est tout "
        "l'intérêt d'un code stable."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Valeur introuvable."}},
)
async def modifier_referentiel(
    payload: ReferentielUpdate,
    referentiel_id: uuid.UUID = Path(..., description="Identifiant de la valeur."),
    db: AsyncSession = Depends(get_async_db),
):
    valeur = (
        await db.execute(select(Referentiel).filter(Referentiel.id == referentiel_id))
    ).scalars().first()
    if valeur is None:
        raise HTTPException(status_code=404, detail="Valeur de référentiel introuvable")

    modifications = payload.model_dump(exclude_unset=True)
    if modifications.get("parent_id") == referentiel_id:
        raise HTTPException(
            status_code=422, detail="Une valeur ne peut pas être son propre parent."
        )
    for champ, contenu in modifications.items():
        setattr(valeur, champ, contenu)

    await db.commit()
    await db.refresh(valeur)
    return valeur


@router.delete(
    "/referentiels/{referentiel_id}",
    status_code=204,
    dependencies=[require_admin],
    summary="Supprimer une valeur de liste",
    description=(
        "À réserver aux valeurs créées par erreur. Pour retirer une valeur "
        "en service, préférer `is_active: false` : les projets et actions qui "
        "s'y rattachaient conservent alors leur libellé à l'affichage, là où "
        "une suppression les laisse sans catégorie."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Valeur introuvable."}},
)
async def supprimer_referentiel(
    referentiel_id: uuid.UUID = Path(..., description="Identifiant de la valeur."),
    db: AsyncSession = Depends(get_async_db),
):
    valeur = (
        await db.execute(select(Referentiel).filter(Referentiel.id == referentiel_id))
    ).scalars().first()
    if valeur is None:
        raise HTTPException(status_code=404, detail="Valeur de référentiel introuvable")
    await db.delete(valeur)
    await db.commit()


# ---------------------------------------------------------------------------
# Gabarits
# ---------------------------------------------------------------------------

_CHARGEMENT_GABARIT = selectinload(Gabarit.actions)


async def _charger_gabarit(db: AsyncSession, gabarit_id: uuid.UUID) -> Gabarit:
    gabarit = (
        await db.execute(
            select(Gabarit).options(_CHARGEMENT_GABARIT).filter(Gabarit.id == gabarit_id)
        )
    ).scalars().first()
    if gabarit is None:
        raise HTTPException(status_code=404, detail="Gabarit introuvable")
    return gabarit


async def _demarquer_defaut(db: AsyncSession, entite: GabaritEntite, sauf: uuid.UUID | None):
    """Un seul gabarit proposé d'office par entité.

    Un index unique partiel le garantit en base ; sans ce retrait préalable,
    désigner un nouveau défaut échouerait en conflit au lieu de déplacer la
    marque, ce qui n'est jamais l'intention.
    """
    stmt = select(Gabarit).filter(
        Gabarit.entite == entite, Gabarit.is_default.is_(True)
    )
    if sauf is not None:
        stmt = stmt.filter(Gabarit.id != sauf)
    for autre in (await db.execute(stmt)).scalars().all():
        autre.is_default = False
    # Le retrait doit atteindre la base avant l'insertion du nouveau défaut,
    # l'index unique étant vérifié à chaque instruction.
    await db.flush()


def _valider_contenu(entite: GabaritEntite, valeurs, politique):
    try:
        return (
            service_gabarits.valider_valeurs(entite, valeurs),
            service_gabarits.valider_politique(entite, politique),
        )
    except service_gabarits.GabaritError as erreur:
        raise HTTPException(status_code=422, detail=str(erreur))


def _lignes_actions(modeles) -> list[GabaritAction]:
    return [
        GabaritAction(
            **{
                **modele.model_dump(exclude={"responsable_names"}),
                # Stocké en texte, au format même de la cellule Excel dont ces
                # noms sortent d'habitude.
                "responsable_names": ", ".join(modele.responsable_names) or None,
            }
        )
        for modele in modeles
    ]


@router.get(
    "/gabarits",
    response_model=list[GabaritOut],
    dependencies=[require_reader],
    summary="Gabarits de création",
    responses=AUTH_RESPONSES,
)
async def lister_gabarits(
    entite: GabaritEntite | None = Query(
        None, description="Ne garder que les gabarits de projet, ou d'action."
    ),
    inclure_inactifs: bool = Query(False, description="Inclure les gabarits désactivés."),
    db: AsyncSession = Depends(get_async_db),
):
    stmt = (
        select(Gabarit)
        .options(_CHARGEMENT_GABARIT)
        .order_by(Gabarit.entite, Gabarit.position, Gabarit.nom)
    )
    if entite is not None:
        stmt = stmt.filter(Gabarit.entite == entite)
    if not inclure_inactifs:
        stmt = stmt.filter(Gabarit.is_active.is_(True))
    return list((await db.execute(stmt)).scalars().unique().all())


@router.get(
    "/gabarits/champs",
    response_model=list[ChampsGabaritOut],
    dependencies=[require_reader],
    summary="Champs qu'un gabarit peut préremplir ou contraindre",
    description=(
        "Nom, type et liste de référence de chaque champ, lus sur les schémas "
        "de création eux-mêmes. L'écran d'administration s'en sert pour "
        "proposer les bons champs *et* les bons contrôles : une liste recopiée "
        "dans l'interface aurait divergé au premier champ ajouté, et un "
        "gabarit se serait mis à porter des valeurs que la création ignore en "
        "silence."
    ),
    responses=AUTH_RESPONSES,
)
async def champs_gabarits():
    return [
        ChampsGabaritOut(
            entite=entite,
            champs=service_gabarits.decrire_champs(entite),
            cles_politique=sorted(service_gabarits.CLES_POLITIQUE),
        )
        for entite in GabaritEntite
    ]


@router.post(
    "/gabarits",
    response_model=GabaritOut,
    status_code=201,
    dependencies=[require_admin],
    summary="Créer un gabarit",
    description=(
        "Les valeurs et la politique sont validées contre les champs "
        "réellement acceptés à la création : une faute de frappe est refusée "
        "ici plutôt que de rester sans effet à chaque utilisation."
    ),
    responses={
        **AUTH_RESPONSES,
        409: {"description": "Un gabarit de ce nom existe déjà pour cette entité."},
        422: {"description": "Champ inconnu dans les valeurs ou la politique."},
    },
)
async def creer_gabarit(payload: GabaritCreate, db: AsyncSession = Depends(get_async_db)):
    valeurs, politique = _valider_contenu(
        payload.entite, payload.valeurs, payload.politique
    )
    if payload.actions and payload.entite is not GabaritEntite.PROJET:
        raise HTTPException(
            status_code=422,
            detail=(
                "Seul un gabarit de projet porte des actions type : le modèle "
                "n'a pas de hiérarchie d'actions."
            ),
        )

    if payload.is_default:
        await _demarquer_defaut(db, payload.entite, None)

    gabarit = Gabarit(
        **payload.model_dump(exclude={"valeurs", "politique", "actions"}),
        valeurs=valeurs,
        politique=politique,
    )
    gabarit.actions = _lignes_actions(payload.actions)
    db.add(gabarit)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Un gabarit nommé « {payload.nom} » existe déjà pour cette entité.",
        )
    return await _charger_gabarit(db, gabarit.id)


@router.put(
    "/gabarits/{gabarit_id}",
    response_model=GabaritOut,
    dependencies=[require_admin],
    summary="Modifier un gabarit",
    description=(
        "Modification partielle. `actions` remplace intégralement la liste "
        "des actions type ; absent, elle est conservée.\n\n"
        "L'entité n'est pas modifiable : les champs autorisés en dépendent, et "
        "basculer un gabarit de projet en gabarit d'action rendrait ses "
        "valeurs et sa politique invalides d'un coup."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Gabarit introuvable."}},
)
async def modifier_gabarit(
    payload: GabaritUpdate,
    gabarit_id: uuid.UUID = Path(..., description="Identifiant du gabarit."),
    db: AsyncSession = Depends(get_async_db),
):
    gabarit = await _charger_gabarit(db, gabarit_id)
    modifications = payload.model_dump(exclude_unset=True)

    # La validation porte sur la valeur résultante, pas sur le seul patch :
    # une politique fournie seule doit rester cohérente avec les valeurs déjà
    # enregistrées.
    valeurs, politique = _valider_contenu(
        gabarit.entite,
        modifications.get("valeurs", gabarit.valeurs),
        modifications.get("politique", gabarit.politique),
    )
    modifications.pop("valeurs", None)
    modifications.pop("politique", None)
    gabarit.valeurs, gabarit.politique = valeurs, politique

    actions = modifications.pop("actions", None)
    if actions is not None:
        if gabarit.entite is not GabaritEntite.PROJET:
            raise HTTPException(
                status_code=422,
                detail="Seul un gabarit de projet porte des actions type.",
            )
        # `cascade="all, delete-orphan"` supprime les anciennes lignes.
        gabarit.actions = _lignes_actions(payload.actions or [])

    if modifications.get("is_default"):
        await _demarquer_defaut(db, gabarit.entite, gabarit.id)

    for champ, contenu in modifications.items():
        setattr(gabarit, champ, contenu)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Un gabarit de ce nom existe déjà pour cette entité."
        )
    return await _charger_gabarit(db, gabarit_id)


@router.delete(
    "/gabarits/{gabarit_id}",
    status_code=204,
    dependencies=[require_admin],
    summary="Supprimer un gabarit",
    description=(
        "Les projets et actions déjà créés à partir de ce gabarit ne sont pas "
        "touchés : un gabarit ne fait que remplir un formulaire, il ne reste "
        "pas rattaché à ce qu'il a produit."
    ),
    responses={**AUTH_RESPONSES, 404: {"description": "Gabarit introuvable."}},
)
async def supprimer_gabarit(
    gabarit_id: uuid.UUID = Path(..., description="Identifiant du gabarit."),
    db: AsyncSession = Depends(get_async_db),
):
    gabarit = await _charger_gabarit(db, gabarit_id)
    await db.delete(gabarit)
    await db.commit()
