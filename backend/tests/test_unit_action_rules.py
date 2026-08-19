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
from app.services.action_rules import (  # noqa: E402
    apply_indicators,
    apply_status,
    compute_otd,
    compute_spi,
    compute_status,
)

TODAY = date(2026, 8, 18)
FUTUR = date(2026, 12, 31)
PASSE = date(2026, 1, 1)


def test_cent_pourcent_donne_termine():
    assert compute_status(100.0, FUTUR, ActionStatus.EN_COURS, TODAY) is ActionStatus.TERMINE


def test_echeance_depassee_donne_en_retard():
    assert compute_status(40.0, PASSE, ActionStatus.EN_COURS, TODAY) is ActionStatus.EN_RETARD


def test_le_jour_de_l_echeance_n_est_pas_un_retard():
    """L'action a sa journée pour être livrée : c'est déjà la règle de l'OTD,
    qui compte une livraison le jour J comme tenue. `/actions/today` et
    `/actions/overdue` restent ainsi strictement disjointes."""
    assert compute_status(40.0, TODAY, ActionStatus.EN_COURS, TODAY) is ActionStatus.EN_COURS
    assert compute_status(0.0, TODAY, ActionStatus.A_FAIRE, TODAY) is ActionStatus.A_FAIRE


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


# --- SPI et OTD ------------------------------------------------------------

def test_spi_suit_l_avancement():
    """Constaté sur 547 des 555 actions des classeurs : le SPI est
    l'avancement rapporté à l'objectif de 100 % à l'échéance."""
    assert compute_spi(0.0) == 0.0
    assert compute_spi(40.0) == 40.0
    assert compute_spi(100.0) == 100.0


def test_spi_borne_et_tolere_l_absence():
    assert compute_spi(None) == 0.0
    assert compute_spi(-5.0) == 0.0
    assert compute_spi(150.0) == 100.0


def test_otd_livraison_dans_les_temps():
    assert compute_otd(100.0, FUTUR, date(2026, 12, 1)) == 100.0


def test_otd_le_jour_de_l_echeance_compte_comme_tenu():
    """Conforme aux fichiers : P01-02-04, livrée le 05/03 pour une échéance au
    05/03, porte un OTD de 100 %."""
    assert compute_otd(100.0, TODAY, TODAY) == 100.0


def test_otd_livraison_en_retard():
    assert compute_otd(100.0, PASSE, TODAY) == 0.0


def test_otd_nul_tant_que_non_livree():
    assert compute_otd(40.0, FUTUR, None) == 0.0
    assert compute_otd(40.0, PASSE, None) == 0.0
    # Une date de réalisation sans achèvement ne suffit pas.
    assert compute_otd(80.0, FUTUR, TODAY) == 0.0


def test_otd_sans_echeance():
    """Aucune date à respecter : rien n'a été manqué."""
    assert compute_otd(100.0, None, TODAY) == 100.0
    assert compute_otd(50.0, None, None) == 0.0


def test_apply_indicators_a_cent_pour_cent():
    """Le cas demandé : passer une action à 100 % doit tout aligner d'un coup."""
    action = _action(progress=100.0, deadline=FUTUR)
    apply_indicators(action, TODAY)
    assert action.status is ActionStatus.TERMINE
    assert action.date_realisation == TODAY
    assert action.spi == 100.0
    assert action.otd == 100.0


def test_apply_indicators_terminee_hors_delai():
    action = _action(progress=100.0, deadline=PASSE)
    apply_indicators(action, TODAY)
    assert action.status is ActionStatus.TERMINE
    assert action.spi == 100.0
    assert action.otd == 0.0, "livrée après l'échéance : la deadline n'est pas respectée"


def test_apply_indicators_reouverture_remet_les_indicateurs_a_plat():
    action = _action(progress=100.0, deadline=FUTUR)
    apply_indicators(action, TODAY)
    action.progress = 60.0
    apply_indicators(action, TODAY)
    assert action.status is ActionStatus.EN_COURS
    assert action.date_realisation is None
    assert action.spi == 60.0
    assert action.otd == 0.0


def test_apply_indicators_respecte_une_valeur_imposee():
    """Un chef de projet doit pouvoir corriger un indicateur sans que
    l'enregistrement suivant l'écrase."""
    action = _action(progress=100.0, deadline=PASSE)
    action.spi = 75.0
    action.otd = 50.0
    apply_indicators(action, TODAY, recompute_spi=False, recompute_otd=False)
    assert (action.spi, action.otd) == (75.0, 50.0)
    assert action.status is ActionStatus.TERMINE


def test_apply_indicators_preserve_la_date_du_fichier_excel():
    action = _action(progress=100.0, deadline=FUTUR, date_realisation=date(2026, 5, 1))
    apply_indicators(action, TODAY, manage_date_realisation=False)
    assert action.date_realisation == date(2026, 5, 1)
    assert action.otd == 100.0
