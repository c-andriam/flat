"""
Tests unitaires du récapitulatif de relance : cadence, périmètre, sections et
mise en veille. Aucune base de données ni stack démarrée n'est nécessaire.

Les requêtes sont vérifiées par compilation SQL avec valeurs littérales, comme
dans `test_unit_relances` : c'est ce qui permet de contrôler les bornes de date
exactes — l'endroit où une régression coûte un email de trop à quelqu'un.
"""
import os
import uuid
from datetime import date, datetime

import pytest

os.environ.setdefault("POSTGRES_USER", "unit-test")
os.environ.setdefault("POSTGRES_PASSWORD", "unit-test")
os.environ.setdefault("POSTGRES_DB", "unit-test")
os.environ.setdefault("POSTGRES_HOST", "localhost")

import pydantic  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.project import (  # noqa: E402
    DEFAULT_JOURS_ENVOI,
    RelancePerimetre,
    parse_jours,
)
from app.schemas.relance_schema import RelancePreferenceUpdate  # noqa: E402
from app.schemas.report_schema import ActionDigestOut  # noqa: E402
from app.services.email_templates import build_digest_email  # noqa: E402
from app.services.relance_digest import (  # noqa: E402
    SECTIONS,
    Reglage,
    SectionKey,
    perimetre_condition,
    requete_section,
    requetes,
)

#: Mardi 18 août 2026 — même repère que `test_unit_relances`.
MARDI = date(2026, 8, 18)

#: Un mardi à 10 h, dans le fuseau de relance (naïf : seule la cadence compte).
MARDI_10H = datetime(2026, 8, 18, 10, 0)

RESP = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _sql(section: SectionKey, reglage: Reglage | None = None, **kw) -> str:
    stmt = requete_section(section, reglage or Reglage(**kw), RESP, MARDI)
    return str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def _digest(numero: str, deadline: date | None = None) -> ActionDigestOut:
    return ActionDigestOut(
        id=uuid.uuid4(),
        numero=numero,
        description=f"Action {numero}",
        project_code="P01",
        project_name="Projet test",
        status="a_faire",
        progress=25.0,
        deadline=deadline,
        days_left=None if deadline is None else (deadline - MARDI).days,
        resp_suivi="Xavier",
        responsables=["Andry"],
    )


# --- Réglages par défaut ---------------------------------------------------

def test_absence_de_ligne_vaut_valeurs_par_defaut():
    """Personne n'a besoin de configurer quoi que ce soit pour être relancé."""
    reglage = Reglage.depuis(None)
    assert reglage.enabled is True
    assert reglage.days_of_week == tuple(parse_jours(DEFAULT_JOURS_ENVOI))
    assert reglage.personnalise is False


def test_frequence_par_defaut_est_de_deux_par_semaine():
    reglage = Reglage()
    assert reglage.frequence_hebdomadaire == 2
    assert reglage.jours_lisibles == "lundi et jeudi"


def test_destinataire_par_defaut_est_le_responsable_de_suivi():
    """C'est la personne qui pilote l'action, pas celle qui l'exécute."""
    assert Reglage().perimeter is RelancePerimetre.SUIVI


def test_les_quatre_sections_sont_actives_par_defaut():
    assert Reglage().sections_actives == tuple(SectionKey)


def test_une_section_desactivee_disparait_du_message():
    reglage = Reglage(include_pending=False, include_due_soon=False)
    assert reglage.sections_actives == (SectionKey.OVERDUE, SectionKey.TODAY)
    assert [spec.key for spec, _ in requetes(reglage, RESP, MARDI)] == [
        SectionKey.OVERDUE,
        SectionKey.TODAY,
    ]


# --- Cadence ---------------------------------------------------------------

def test_envoi_uniquement_au_jour_et_a_l_heure_choisis():
    reglage = Reglage(days_of_week=(1,), send_hour=10)  # mardi 10 h
    assert reglage.doit_envoyer(MARDI_10H) is True
    # Bon jour, mauvaise heure.
    assert reglage.doit_envoyer(MARDI_10H.replace(hour=11)) is False
    # Bonne heure, mauvais jour (mercredi).
    assert reglage.doit_envoyer(datetime(2026, 8, 19, 10, 0)) is False


def test_la_minute_ne_compte_pas():
    """Le planificateur déclenche la tâche en début d'heure ; exiger l'égalité
    des minutes ferait dépendre l'envoi de la ponctualité du worker."""
    reglage = Reglage(days_of_week=(1,), send_hour=10)
    assert reglage.doit_envoyer(MARDI_10H.replace(minute=37)) is True


def test_relances_coupees_n_envoient_rien():
    assert Reglage(days_of_week=(1,), send_hour=10, enabled=False).doit_envoyer(
        MARDI_10H
    ) is False


def test_sans_aucune_section_rien_ne_part():
    """Un message sans section serait vide : mieux vaut ne pas l'envoyer que
    d'expédier un en-tête suivi de rien."""
    muet = Reglage(
        days_of_week=(1,),
        send_hour=10,
        include_overdue=False,
        include_today=False,
        include_due_soon=False,
        include_pending=False,
    )
    assert muet.doit_envoyer(MARDI_10H) is False
    assert muet.prochain_creneau(MARDI_10H) is None


@pytest.mark.parametrize(
    "maintenant, attendu",
    [
        # Mardi 10 h : le prochain jour retenu est le jeudi.
        (datetime(2026, 8, 18, 10, 0), datetime(2026, 8, 20, 8, 0)),
        # Lundi avant l'heure : c'est le jour même.
        (datetime(2026, 8, 17, 6, 0), datetime(2026, 8, 17, 8, 0)),
        # Lundi après l'heure : le créneau est passé, on saute à jeudi.
        (datetime(2026, 8, 17, 9, 0), datetime(2026, 8, 20, 8, 0)),
        # Pile à l'heure : le créneau courant ne compte pas comme « prochain ».
        (datetime(2026, 8, 20, 8, 0), datetime(2026, 8, 24, 8, 0)),
    ],
)
def test_prochain_creneau(maintenant, attendu):
    """Sans cette date affichée, un réglage modifié un mardi pour un envoi le
    lundi laisse croire à une panne pendant six jours."""
    assert Reglage().prochain_creneau(maintenant) == attendu


def test_pas_de_prochain_creneau_si_desactive():
    assert Reglage(enabled=False).prochain_creneau(MARDI_10H) is None


# --- Périmètre -------------------------------------------------------------

def test_perimetre_suivi_vise_la_table_des_suiveurs():
    sql = _sql(SectionKey.OVERDUE, Reglage(perimeter=RelancePerimetre.SUIVI))
    assert "action_resp_suivi" in sql
    assert "action_responsables" not in sql


def test_perimetre_realisation_vise_la_table_des_responsables():
    sql = _sql(SectionKey.OVERDUE, Reglage(perimeter=RelancePerimetre.REALISATION))
    assert "action_responsables" in sql
    assert "action_resp_suivi" not in sql


def test_perimetre_les_deux_est_une_disjonction():
    """« Suivi ou réalisation » — un ET ne renverrait que les actions où la
    personne cumule les deux rôles, soit presque aucune."""
    sql = _sql(SectionKey.OVERDUE, Reglage(perimeter=RelancePerimetre.LES_DEUX))
    assert "action_resp_suivi" in sql
    assert "action_responsables" in sql
    assert " OR " in sql


def test_perimetre_passe_par_exists_et_non_par_jointure():
    """Un JOIN dupliquerait la ligne action une fois par responsable."""
    condition = perimetre_condition(RelancePerimetre.SUIVI, RESP)
    sql = str(
        condition.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "EXISTS" in sql


# --- Sections : bornes de date --------------------------------------------

def test_les_quatre_sections_partitionnent_les_actions_ouvertes():
    """Chaque action ouverte tombe dans une seule section.

    Sans cette partition, le total annoncé en objet compterait deux fois la
    même ligne, et le destinataire lirait deux fois la même action.
    """
    horizon = Reglage(horizon_days=3)
    assert "deadline < '2026-08-18'" in _sql(SectionKey.OVERDUE, horizon)

    aujourdhui = _sql(SectionKey.TODAY, horizon)
    assert "deadline = '2026-08-18'" in aujourdhui

    proche = _sql(SectionKey.DUE_SOON, horizon)
    assert "deadline > '2026-08-18'" in proche
    assert "deadline <= '2026-08-21'" in proche

    # « En attente » reprend exactement là où « échéance proche » s'arrête.
    attente = _sql(SectionKey.PENDING, horizon)
    assert "deadline > '2026-08-21'" in attente


def test_section_en_attente_retient_les_actions_sans_echeance():
    """Le complément est calculé sur la date, pas en niant les trois autres
    prédicats : une négation laisserait les `NULL` en UNKNOWN et ferait
    disparaître précisément les actions que cette section doit montrer."""
    sql = _sql(SectionKey.PENDING)
    assert "deadline IS NULL" in sql
    assert " OR " in sql


def test_horizon_personnalise_deplace_la_frontiere():
    large = Reglage(horizon_days=10)
    assert "deadline <= '2026-08-28'" in _sql(SectionKey.DUE_SOON, large)
    assert "deadline > '2026-08-28'" in _sql(SectionKey.PENDING, large)


# --- Mise en veille --------------------------------------------------------

def test_les_actions_en_veille_sortent_de_toutes_les_sections():
    """Un projet suspendu accumule des retards que personne ne peut solder ;
    sans cette sortie ils gonflent chaque rappel jusqu'à noyer les actions sur
    lesquelles quelqu'un peut agir."""
    for section in SectionKey:
        sql = _sql(section)
        assert "actions.is_standby IS false" in sql, section
        assert "projects.is_standby IS true" in sql, section
        assert "NOT IN" in sql, section


def test_les_projets_archives_sortent_aussi():
    assert "is_active IS true" in _sql(SectionKey.OVERDUE)


def test_la_veille_est_testee_par_sous_requete():
    """La même requête est construite par six routes, dont une qui compte via
    `COUNT(*) OVER ()` : changer son FROM fausserait ce décompte."""
    sql = _sql(SectionKey.OVERDUE)
    assert "FROM actions" in sql
    assert "JOIN projects" not in sql


# --- Tri -------------------------------------------------------------------

def test_sections_triees_par_urgence():
    sql = _sql(SectionKey.PENDING)
    assert "ORDER BY actions.deadline" in sql
    # Une action sans échéance n'est ni la plus urgente ni la plus lointaine.
    assert "NULLS LAST" in sql


# --- Gabarit du message ----------------------------------------------------

def test_objet_annonce_le_retard_quand_il_y_en_a():
    """L'objet est souvent tout ce qui est lu depuis un téléphone."""
    message = build_digest_email(
        "Xavier Rabe",
        [
            (SECTIONS[SectionKey.OVERDUE], [_digest("P01-01", date(2026, 8, 10))]),
            (SECTIONS[SectionKey.PENDING], [_digest("P01-02"), _digest("P01-03")]),
        ],
    )
    assert "3 action(s)" in message.subject
    assert "1 en retard" in message.subject
    assert message.action_count == 3


def test_objet_sans_retard_ne_crie_pas():
    message = build_digest_email(
        "Xavier", [(SECTIONS[SectionKey.PENDING], [_digest("P01-02")])]
    )
    assert "en retard" not in message.subject


def test_sections_vides_ne_sont_pas_rendues():
    """Un titre suivi d'un tableau vide se lit comme un défaut d'affichage."""
    message = build_digest_email(
        "Xavier",
        [
            (SECTIONS[SectionKey.OVERDUE], []),
            (SECTIONS[SectionKey.TODAY], [_digest("P01-04", MARDI)]),
        ],
    )
    assert "En retard" not in message.html
    # L'apostrophe du libellé ressort échappée en `&#x27;` : on n'assert que
    # sur la partie stable du titre.
    assert "rendre aujourd" in message.html


def test_message_rendu_en_tableaux_pour_outlook():
    """Outlook pour Windows compose le HTML avec le moteur de Word : ni
    flexbox ni grid, et les feuilles `<style>` sont en partie ignorées."""
    message = build_digest_email(
        "Xavier", [(SECTIONS[SectionKey.TODAY], [_digest("P01-04", MARDI)])]
    )
    assert "<table" in message.html
    assert "display:flex" not in message.html
    assert "display:grid" not in message.html


def test_version_texte_reprend_toutes_les_actions():
    """Sans version texte, les passerelles anti-spam dégradent la note du
    message et les clients en mode texte affichent une page de balises."""
    message = build_digest_email(
        "Xavier",
        [
            (SECTIONS[SectionKey.OVERDUE], [_digest("P01-01", date(2026, 8, 10))]),
            (SECTIONS[SectionKey.PENDING], [_digest("P01-02")]),
        ],
    )
    assert "P01-01" in message.text
    assert "P01-02" in message.text
    assert "<table" not in message.text


def test_cadence_rappelee_en_pied_de_message():
    """Un destinataire qui ignore d'où vient un envoi automatique le classe en
    indésirable au lieu de le régler."""
    message = build_digest_email(
        "Xavier",
        [(SECTIONS[SectionKey.PENDING], [_digest("P01-02")])],
        cadence="2 fois par semaine (lundi et jeudi), vers 8 h",
        reglages_url="https://suivi.example/relances",
    )
    assert "2 fois par semaine" in message.html
    assert "https://suivi.example/relances" in message.html
    assert "2 fois par semaine" in message.text


def test_description_d_action_est_echappee():
    """Une description vient d'une cellule Excel : elle peut contenir n'importe
    quoi, y compris des balises."""
    action = _digest("P01-05", MARDI)
    injection = action.model_copy(update={"description": "<script>alert(1)</script>"})
    message = build_digest_email(
        "Xavier", [(SECTIONS[SectionKey.TODAY], [injection])]
    )
    assert "<script>" not in message.html
    assert "&lt;script&gt;" in message.html


# --- Validation des réglages ----------------------------------------------

def test_jours_tries_et_dedoublonnes():
    """La valeur part dans une colonne texte : « 3,0,3 » y serait
    indistinguable d'un réglage volontaire au moment de l'afficher."""
    assert RelancePreferenceUpdate(days_of_week=[3, 0, 3]).days_of_week == [0, 3]


def test_jour_hors_bornes_refuse():
    with pytest.raises(pydantic.ValidationError, match="Jour invalide"):
        RelancePreferenceUpdate(days_of_week=[7])


def test_liste_de_jours_vide_refusee():
    """Couper les relances se fait par `enabled: false` — le réglage reste
    alors en place et se retrouve tel quel à la reprise."""
    with pytest.raises(pydantic.ValidationError, match="Au moins un jour"):
        RelancePreferenceUpdate(days_of_week=[])


def test_heure_hors_bornes_refusee():
    with pytest.raises(pydantic.ValidationError):
        RelancePreferenceUpdate(send_hour=24)


def test_charge_utile_vide_refusee():
    """Une requête vide n'exprime aucune intention de modification."""
    with pytest.raises(pydantic.ValidationError):
        RelancePreferenceUpdate()


def test_champ_inconnu_refuse():
    """Un champ mal orthographié était auparavant ignoré en silence."""
    with pytest.raises(pydantic.ValidationError):
        RelancePreferenceUpdate(send_hours=8)


def test_reglage_partiel_ne_touche_que_les_champs_fournis():
    payload = RelancePreferenceUpdate(send_hour=17)
    assert payload.model_dump(exclude_unset=True) == {"send_hour": 17}
