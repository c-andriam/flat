"""
Tests d'intégration des vues d'actions, des rapports et des relances.
Nécessitent la stack démarrée (`make test`).
"""
import uuid

import pytest

VUES = [
    "open", "overdue", "today", "due-soon", "upcoming",
    "in-progress", "blocked", "done", "unassigned", "no-deadline",
]


def _action(project_id, **overrides):
    charge = {
        "project_id": project_id,
        "description": "Action de test",
        "resp_suivi": "Testeur",
        "deadline": "2026-12-31",
        "responsable_names": ["Testeur"],
    }
    charge.update(overrides)
    return charge


# --- Vues ------------------------------------------------------------------

@pytest.mark.parametrize("vue", VUES)
def test_chaque_vue_repond(api, vue):
    """Non-régression sur l'ordre de déclaration des routes : déclarée après
    `/actions/{action_id}`, chaque vue serait interprétée comme un UUID et
    renverrait 422."""
    resp = api.get(f"/actions/{vue}")
    assert resp.status_code == 200, f"/actions/{vue} -> {resp.status_code} {resp.text[:200]}"
    assert isinstance(resp.json(), list)
    assert "X-Total-Count" in resp.headers


def test_vue_inconnue_rejetee(api):
    resp = api.get("/actions?view=nimportequoi")
    assert resp.status_code == 422


def test_action_en_retard_apparait_dans_overdue(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"], deadline="2020-01-01")).json()
    numeros = [a["numero"] for a in api.get(f"/actions/overdue?project_id={test_project['id']}").json()]
    assert cree["numero"] in numeros
    # Et pas dans les échéances proches : les deux vues sont disjointes.
    proches = [a["numero"] for a in api.get(f"/actions/due-soon?project_id={test_project['id']}").json()]
    assert cree["numero"] not in proches


def test_action_terminee_sort_des_vues_ouvertes(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"], deadline="2020-01-01")).json()
    api.patch(f"/actions/{cree['id']}", json={"progress": 100.0})
    numeros = [a["numero"] for a in api.get(f"/actions/overdue?project_id={test_project['id']}").json()]
    assert cree["numero"] not in numeros


def test_summary_coherent(api, test_project):
    api.post("/actions", json=_action(test_project["id"], deadline="2020-01-01"))
    resp = api.get(f"/actions/summary?project_id={test_project['id']}&active_projects_only=false")
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["counts"]["overdue"] >= 1
    assert corps["counts"]["all"] >= corps["counts"]["open"]
    assert 0 <= corps["overdue_ratio"] <= 100


def test_upcoming_suit_le_decalage_de_semaine(api, test_project):
    resp = api.get(f"/actions/upcoming?project_id={test_project['id']}&weeks_ahead=1")
    assert resp.status_code == 200
    resp = api.get(f"/actions/upcoming?project_id={test_project['id']}&weeks_ahead=99")
    assert resp.status_code == 422  # borne haute à 52


# --- PATCH / PUT -----------------------------------------------------------

def test_patch_un_seul_champ(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    resp = api.patch(f"/actions/{cree['id']}", json={"commentaire": "Une seule modification"})
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["commentaire"] == "Une seule modification"
    assert corps["description"] == cree["description"]  # le reste est intact


def test_patch_plusieurs_champs(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    resp = api.patch(
        f"/actions/{cree['id']}",
        json={"progress": 40.0, "commentaire": "Deux champs", "spi": 80.0},
    )
    assert resp.status_code == 200
    corps = resp.json()
    assert (corps["progress"], corps["commentaire"], corps["spi"]) == (40.0, "Deux champs", 80.0)


def test_patch_vide_rejete(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    assert api.patch(f"/actions/{cree['id']}", json={}).status_code == 422


def test_patch_champ_inconnu_rejete(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    resp = api.patch(f"/actions/{cree['id']}", json={"progres": 50})
    assert resp.status_code == 422, "une faute de frappe doit être signalée, pas ignorée"


def test_patch_change_les_responsables(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    nouveau = f"Resp-{uuid.uuid4().hex[:6]}"
    resp = api.patch(f"/actions/{cree['id']}", json={"responsable_names": [nouveau]})
    assert resp.status_code == 200
    assert [r["display_name"] for r in resp.json()["responsables"]] == [nouveau]


def test_put_remplace_et_efface_les_champs_absents(api, test_project):
    cree = api.post(
        "/actions",
        json=_action(test_project["id"], commentaire="À effacer", charges_hj=3.0),
    ).json()
    assert cree["commentaire"] == "À effacer"

    resp = api.put(
        f"/actions/{cree['id']}",
        json={
            "description": "Description remplacée",
            "resp_suivi": "Nouveau suivi",
            "responsable_names": ["Nouveau"],
            "deadline": "2027-01-31",
        },
    )
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["description"] == "Description remplacée"
    assert corps["commentaire"] is None, "PUT doit effacer les champs absents"
    assert corps["charges_hj"] is None
    assert [r["display_name"] for r in corps["responsables"]] == ["Nouveau"]


def test_put_exige_les_champs_obligatoires(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    resp = api.put(f"/actions/{cree['id']}", json={"description": "incomplet"})
    assert resp.status_code == 422


def test_put_projet(api, test_project):
    resp = api.put(
        f"/projects/{test_project['id']}",
        json={
            "code": test_project["code"],
            "name": "Nom remplacé",
            "source_file_path": "x.xlsx",
            "has_phases": False,
            "is_active": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Nom remplacé"
    assert resp.json()["is_active"] is False


def test_put_responsable_demappe_sans_email(api):
    nom = f"Test-{uuid.uuid4().hex[:6]}"
    cree = api.post("/responsables", json={"display_name": nom, "email": "x@trimeta.mg"}).json()
    assert cree["is_mapped"] is True

    resp = api.put(f"/responsables/{cree['id']}", json={"display_name": nom})
    assert resp.status_code == 200
    assert resp.json()["is_mapped"] is False
    api.delete(f"/responsables/{cree['id']}")


def test_bascule_has_phases_refusee_si_actions(api, test_project):
    api.post("/actions", json=_action(test_project["id"]))
    resp = api.patch(f"/projects/{test_project['id']}", json={"has_phases": True})
    assert resp.status_code == 409


# --- Rapports --------------------------------------------------------------

def test_rapport_portefeuille(api, test_project):
    resp = api.get("/reports/portfolio?scope=all")
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["project_count"] >= 1
    codes = [p["code"] for p in corps["projects"]]
    assert test_project["code"] in codes
    projet = next(p for p in corps["projects"] if p["code"] == test_project["code"])
    assert projet["health"] in ("ok", "attention", "critique")
    assert 0 <= projet["completion_rate"] <= 100


def test_rapport_projet(api, test_project):
    api.post("/actions", json=_action(test_project["id"], deadline="2020-01-01"))
    resp = api.get(f"/reports/projects/{test_project['id']}")
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["total_actions"] >= 1
    assert corps["overdue"] >= 1
    assert corps["health"] in ("attention", "critique")


def test_rapport_projet_introuvable(api):
    assert api.get(f"/reports/projects/{uuid.uuid4()}").status_code == 404


def test_rapport_charge(api):
    resp = api.get("/reports/workload")
    assert resp.status_code == 200
    corps = resp.json()
    assert "unassigned_actions" in corps
    assert isinstance(corps["responsables"], list)


def test_rapport_prevision(api):
    resp = api.get("/reports/forecast?weeks=3")
    assert resp.status_code == 200
    corps = resp.json()
    assert len(corps["weeks"]) == 3
    # Les créneaux se suivent sans trou ni recouvrement.
    for precedent, suivant in zip(corps["weeks"], corps["weeks"][1:]):
        assert precedent["week_end"] < suivant["week_start"]


# --- Relances --------------------------------------------------------------

def test_config_relance(api):
    resp = api.get("/relances/config")
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["mode"] in ("graph", "dry_run")
    assert corps["explanation"]


def test_apercu_relance_detecte_les_actions(api, test_project):
    """Le principe demandé : on ne fournit qu'un identifiant de responsable,
    la route sélectionne elle-même les actions correspondantes."""
    nom = f"Resp-{uuid.uuid4().hex[:6]}"
    api.post("/actions", json=_action(test_project["id"], deadline="2020-01-01", responsable_names=[nom]))
    responsable = next(
        r for r in api.get("/responsables?limit=1000").json() if r["display_name"] == nom
    )

    resp = api.get(f"/relances/{responsable['id']}/preview?kind=overdue")
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["action_count"] >= 1
    assert corps["subject"]
    assert corps["html"].startswith("<!DOCTYPE html>")
    # Non mappé : l'aperçu se construit, mais l'envoi serait ignoré.
    assert corps["would_send"] is False
    assert "non mappé" in corps["skip_reason"]


def test_apercu_html_navigable(api, test_project):
    nom = f"Resp-{uuid.uuid4().hex[:6]}"
    api.post("/actions", json=_action(test_project["id"], responsable_names=[nom]))
    responsable = next(
        r for r in api.get("/responsables?limit=1000").json() if r["display_name"] == nom
    )
    resp = api.get(f"/relances/{responsable['id']}/preview.html?kind=due_soon")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_relance_responsable_introuvable(api):
    assert api.get(f"/relances/{uuid.uuid4()}/preview").status_code == 404


def test_campagne_en_simulation(api):
    resp = api.post("/relances/send?kind=overdue&dry_run=true")
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["kind"] == "overdue"
    assert corps["sent"] == 0, "dry_run ne doit rien envoyer"
