"""
Tests unitaires des règles de statut d'une action.

Ces règles étaient dupliquées entre le routeur HTTP et le worker d'ingestion,
avec deux comportements divergents ; elles vivent maintenant dans
`app.services.action_rules` et sont testables sans stack.
"""
import os
from datetime import date

# `app.database` construit ses moteurs à l'import (sans se connecter) et exige
# donc la présence des variables PostgreSQL. `setdefault` fournit un repli
# pour l'exécution hors conteneur sans jamais écraser une vraie configuration.
os.environ.setdefault("POSTGRES_USER", "unit-test")
os.environ.setdefault("POSTGRES_PASSWORD", "unit-test")
os.environ.setdefault("POSTGRES_DB", "unit-test")
os.environ.setdefault("POSTGRES_HOST", "localhost")

from app.models.project import Action, ActionStatus  # noqa: E402
from app.services.action_rules import apply_status, compute_status  # noqa: E402

TODAY = date(2026, 8, 18)
FUTUR = date(2026, 12, 31)
PASSE = date(2026, 1, 1)


def test_cent_pourcent_donne_termine():
    assert compute_status(100.0, FUTUR, ActionStatus.EN_COURS, TODAY) is ActionStatus.TERMINE


def test_echeance_atteinte_donne_en_retard():
    assert compute_status(40.0, PASSE, ActionStatus.EN_COURS, TODAY) is ActionStatus.EN_RETARD
    # Le jour même compte comme un retard, cohérent avec Action.is_overdue.
    assert compute_status(40.0, TODAY, ActionStatus.A_FAIRE, TODAY) is ActionStatus.EN_RETARD


def test_termine_prime_sur_le_retard():
    assert compute_status(100.0, PASSE, ActionStatus.A_FAIRE, TODAY) is ActionStatus.TERMINE


def test_statut_manuel_conserve():
    # Un chef de projet qui a marqué « en cours » ne doit pas voir son choix
    # écrasé à chaque enregistrement.
    assert compute_status(30.0, FUTUR, ActionStatus.EN_COURS, TODAY) is ActionStatus.EN_COURS
    assert compute_status(0.0, FUTUR, ActionStatus.A_FAIRE, TODAY) is ActionStatus.A_FAIRE


def test_retour_en_arriere_depuis_termine():
    # Action rouverte : elle ne peut pas rester TERMINE.
    assert compute_status(60.0, FUTUR, ActionStatus.TERMINE, TODAY) is ActionStatus.EN_COURS
    assert compute_status(0.0, FUTUR, ActionStatus.TERMINE, TODAY) is ActionStatus.A_FAIRE


def _action(**kwargs):
    action = Action(numero="P01-01", description="x")
    action.progress = kwargs.get("progress", 0.0)
    action.deadline = kwargs.get("deadline")
    action.status = kwargs.get("status", ActionStatus.A_FAIRE)
    action.date_realisation = kwargs.get("date_realisation")
    return action


def test_apply_status_date_le_jour_de_cloture():
    action = _action(progress=100.0, deadline=FUTUR)
    apply_status(action, TODAY)
    assert action.status is ActionStatus.TERMINE
    assert action.date_realisation == TODAY


def test_apply_status_conserve_une_date_deja_saisie():
    action = _action(progress=100.0, deadline=FUTUR, date_realisation=date(2026, 5, 1))
    apply_status(action, TODAY)
    assert action.date_realisation == date(2026, 5, 1)


def test_apply_status_efface_la_date_si_rouverte():
    action = _action(progress=50.0, deadline=FUTUR, status=ActionStatus.TERMINE,
                     date_realisation=TODAY)
    apply_status(action, TODAY)
    assert action.status is ActionStatus.EN_COURS
    assert action.date_realisation is None


def test_apply_status_respecte_la_date_du_fichier_excel():
    """À l'ingestion, la colonne J du fichier fait autorité : la recalculer
    effacerait une date saisie par le chef de projet."""
    action = _action(progress=50.0, deadline=FUTUR, date_realisation=date(2026, 5, 1))
    apply_status(action, TODAY, manage_date_realisation=False)
    assert action.date_realisation == date(2026, 5, 1)
