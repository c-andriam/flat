"""
Tests unitaires des vues métier, des charges utiles PATCH/PUT et des gabarits
d'email. Aucune base de données ni stack démarrée n'est nécessaire.
"""
import os
import uuid
from datetime import date

import pytest

os.environ.setdefault("POSTGRES_USER", "unit-test")
os.environ.setdefault("POSTGRES_PASSWORD", "unit-test")
os.environ.setdefault("POSTGRES_DB", "unit-test")
os.environ.setdefault("POSTGRES_HOST", "localhost")

import pydantic  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.project import ActionStatus  # noqa: E402
from app.schemas.project_schema import (  # noqa: E402
    ActionUpdate,
    ProjectUpdate,
    ResponsableUpdate,
)
from app.schemas.report_schema import ActionDigestOut  # noqa: E402
from app.services.action_queries import (  # noqa: E402
    ActionView,
    build_actions_query,
    week_bounds,
)
from app.services.digests import echeance_lisible  # noqa: E402
from app.services.email_templates import RelanceKind, build_email  # noqa: E402

MARDI = date(2026, 8, 18)


def _sql(view: ActionView, **kw) -> str:
    stmt = build_actions_query(view=view, today=MARDI, **kw)
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


# --- Vues métier -----------------------------------------------------------

def test_semaines_calees_sur_lundi():
    assert week_bounds(0, MARDI) == (date(2026, 8, 17), date(2026, 8, 23))
    assert week_bounds(1, MARDI) == (date(2026, 8, 24), date(2026, 8, 30))
    assert week_bounds(2, MARDI) == (date(2026, 8, 31), date(2026, 9, 6))


def test_toutes_les_vues_compilent():
    for view in ActionView:
        assert _sql(view)


def test_les_trois_vues_datees_sont_disjointes():
    """Une action ouverte à échéance datée tombe dans une seule des vues
    `overdue` / `today` / `due_soon`. Sans cette partition, un responsable
    recevrait deux emails pour la même ligne."""
    assert "deadline < '2026-08-18'" in _sql(ActionView.OVERDUE)
    assert "deadline = '2026-08-18'" in _sql(ActionView.TODAY)
    assert "deadline > '2026-08-18'" in _sql(ActionView.DUE_SOON)


def test_vue_ouverte_croise_statut_et_avancement():
    """Une action à 100 % dont le statut n'a pas été rafraîchi ne doit pas
    ressortir comme ouverte, et inversement."""
    sql = _sql(ActionView.OPEN)
    assert "status != 'TERMINE'" in sql
    assert "progress < 100.0" in sql


def test_filtre_responsable_utilise_exists_et_non_jointure():
    """Un JOIN sur la relation many-to-many dupliquerait la ligne action une
    fois par responsable et fausserait LIMIT comme le total."""
    sql = _sql(ActionView.ALL, responsable_id=uuid.uuid4())
    assert "EXISTS" in sql
    assert "JOIN" not in sql.split("WHERE")[0].upper().replace("LEFT JOIN", "")


def test_projets_archives_exclus_sur_demande():
    assert "is_active IS true" in _sql(ActionView.OPEN, active_projects_only=True)
    assert "is_active" not in _sql(ActionView.OPEN, active_projects_only=False)


def test_entamee_definie_sur_l_avancement_pas_sur_le_statut():
    """Le statut est une valeur unique : une action a 95 % dont l'echeance est
    passee porte `en_retard`. Definie sur le seul statut, la vue « entamees »
    renvoyait une liste vide alors que onze actions du portefeuille etaient
    bel et bien commencees."""
    sql = _sql(ActionView.IN_PROGRESS)
    assert "progress > 0.0" in sql
    assert "progress < 100.0" in sql
    # Le statut declare a la main reste pris en compte.
    assert "status = 'EN_COURS'" in sql


def test_entamee_recoupe_volontairement_en_retard():
    """Contrairement aux trois vues de temps, `in_progress` n'est pas exclusif :
    une action peut être entamée *et* en retard. Son filtre ne porte donc sur
    aucune date."""
    where = _sql(ActionView.IN_PROGRESS).split("WHERE", 1)[1]
    assert "deadline" not in where


def test_bloquees_non_filtrees_sur_l_avancement():
    """Une action bloquée reste listée quel que soit son avancement : c'est
    le blocage qu'on veut voir, pas son pourcentage."""
    assert "status = 'BLOQUE'" in _sql(ActionView.BLOCKED)


# --- PATCH : un champ, plusieurs champs, robustesse ------------------------

def test_patch_un_seul_champ():
    assert ProjectUpdate(name="Nouveau nom").model_dump(exclude_unset=True) == {
        "name": "Nouveau nom"
    }


def test_patch_plusieurs_champs():
    charge = ActionUpdate(progress=60.0, commentaire="En attente TED").model_dump(
        exclude_unset=True
    )
    assert charge == {"progress": 60.0, "commentaire": "En attente TED"}


def test_patch_vide_rejete():
    with pytest.raises(pydantic.ValidationError):
        ProjectUpdate()


def test_patch_champ_inconnu_rejete():
    """`progres` au lieu de `progress` renvoyait 200 sans rien modifier."""
    with pytest.raises(pydantic.ValidationError) as err:
        ActionUpdate(progres=50)
    assert err.value.errors()[0]["type"] == "extra_forbidden"


def test_patch_email_null_explicite_conserve():
    """Distinguer « champ absent » de « null explicite » est ce qui permet de
    démapper un responsable."""
    assert "email" in ResponsableUpdate(email=None).model_fields_set
    assert "email" not in ResponsableUpdate(display_name="X").model_fields_set


def test_patch_valeur_hors_bornes_rejetee():
    with pytest.raises(pydantic.ValidationError):
        ActionUpdate(progress=150.0)


# --- PUT : la charge utile accepte un champ comme tous -------------------

def test_put_accepte_une_charge_utile_complete():
    """Le même schéma sert au PUT d'un champ et à celui de tous : ce qui est
    envoyé est appliqué, ce qui est absent est conservé."""
    complet = ActionUpdate(
        description="Recueillir les besoins",
        resp_suivi="Xavier",
        responsable_names=["Meylis"],
        deadline=date(2026, 12, 31),
        progress=25.0,
        charges_hj=2.5,
        commentaire="Tous les champs",
    )
    charge = complet.model_dump(exclude_unset=True)
    assert len(charge) == 7
    assert charge["responsable_names"] == ["Meylis"]


def test_put_dedoublonne_les_responsables():
    partiel = ActionUpdate(responsable_names=["Meylis", " Meylis ", "Xavier"])
    assert partiel.responsable_names == ["Meylis", "Xavier"]


# --- Gabarits d'email ------------------------------------------------------

def _digests():
    return [
        ActionDigestOut(
            id=uuid.uuid4(),
            numero="P01-02-09",
            description="Intégrer la solution pointeuse faciale",
            project_code="P01",
            project_name="Projet Cantine",
            status=ActionStatus.EN_RETARD,
            progress=40.0,
            deadline=date(2026, 6, 18),
            days_left=-61,
            resp_suivi="Xavier",
            responsables=["Meylis"],
        )
    ]


@pytest.mark.parametrize("kind", list(RelanceKind))
def test_email_produit_html_et_texte(kind):
    message = build_email(kind, "Meylis Rakoto", _digests())
    assert message.subject
    assert message.action_count == 1
    assert message.html.startswith("<!DOCTYPE html>")
    assert message.text and "<table" not in message.text


@pytest.mark.parametrize("kind", list(RelanceKind))
def test_email_compatible_outlook(kind):
    """Outlook pour Windows compose avec le moteur de Word : pas de flexbox,
    pas de grid, pas de feuille de style externe, pas d'image distante."""
    html = build_email(kind, "Meylis", _digests()).html
    assert "<table" in html
    for interdit in ("display:flex", "display: flex", "display:grid", "<link", "http://", "src="):
        assert interdit not in html, f"{interdit} casse le rendu Outlook"


def test_email_echappe_le_html_des_donnees():
    """Une description issue d'Excel ne doit pas pouvoir injecter de balise."""
    digests = _digests()
    digests[0].description = "<script>alert('x')</script> & suite"
    html = build_email(RelanceKind.OVERDUE, "Meylis", digests).html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_email_sans_action_reste_valide():
    message = build_email(RelanceKind.TODAY, "Meylis", [])
    assert message.action_count == 0
    assert message.html.startswith("<!DOCTYPE html>")


def test_bouton_absent_sans_url():
    assert "Ouvrir le suivi" not in build_email(RelanceKind.OVERDUE, "M", _digests()).html
    avec = build_email(RelanceKind.OVERDUE, "M", _digests(), app_url="https://x.mg/actions").html
    assert "Ouvrir le suivi" in avec


@pytest.mark.parametrize(
    "jours,attendu",
    [(-4, "en retard de 4 jours"), (-1, "en retard d'un jour"), (0, "aujourd'hui"), (1, "demain"), (5, "dans 5 jours")],
)
def test_echeance_lisible(jours, attendu):
    digest = _digests()[0]
    digest.days_left = jours
    assert echeance_lisible(digest) == attendu


def test_echeance_lisible_sans_date():
    digest = _digests()[0]
    digest.deadline = None
    digest.days_left = None
    assert echeance_lisible(digest) == "sans échéance"


def test_put_refuse_les_indicateurs_calcules():
    """`spi` et `otd` sont dérivés : les accepter en écriture donnerait une
    valeur que le prochain enregistrement écraserait."""
    for champ in ("spi", "otd", "numero"):
        with pytest.raises(pydantic.ValidationError) as err:
            ActionUpdate(**{champ: 50})
        assert "calcul" in str(err.value).lower()


def test_put_refuse_un_statut_derive():
    for statut in (ActionStatus.TERMINE, ActionStatus.EN_RETARD):
        with pytest.raises(pydantic.ValidationError):
            ActionUpdate(status=statut)
    # `bloque` est un constat humain, il reste imposable.
    assert ActionUpdate(status=ActionStatus.BLOQUE).status is ActionStatus.BLOQUE
