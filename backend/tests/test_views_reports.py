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


def test_chaque_vue_est_coherente_avec_le_summary(api):
    """`/actions/summary` doit donner exactement les memes totaux que les
    routes individuelles : un tableau de bord affiche l'un et navigue vers
    l'autre, un ecart se verrait immediatement."""
    compteurs = api.get("/actions/summary?active_projects_only=false").json()["counts"]
    correspondance = {
        "open": "open", "overdue": "overdue", "today": "today",
        "due-soon": "due_soon", "upcoming": "upcoming", "in-progress": "in_progress",
        "blocked": "blocked", "done": "done", "unassigned": "unassigned",
        "no-deadline": "no_deadline",
    }
    for chemin, cle in correspondance.items():
        resp = api.get(f"/actions/{chemin}?active_projects_only=false&limit=1")
        assert resp.status_code == 200, f"/actions/{chemin} -> {resp.status_code}"
        total = int(resp.headers["X-Total-Count"])
        assert total == compteurs[cle], (
            f"/actions/{chemin} annonce {total}, summary annonce {compteurs[cle]}"
        )


def test_les_trois_vues_de_temps_sont_disjointes(api, test_project):
    """Une action ouverte a echeance datee doit tomber dans une seule vue.
    Sans cette partition, un responsable recevrait deux relances pour elle."""
    ensembles = {}
    for vue in ("overdue", "today", "due-soon"):
        resp = api.get(f"/actions/{vue}?active_projects_only=false&limit=1000")
        ensembles[vue] = {a["id"] for a in resp.json()}
    assert not (ensembles["overdue"] & ensembles["today"])
    assert not (ensembles["overdue"] & ensembles["due-soon"])
    assert not (ensembles["today"] & ensembles["due-soon"])


def test_action_entamee_apparait_dans_in_progress(api, test_project):
    """Regression : la vue filtrait sur `status = en_cours`, or une action
    entamee dont l'echeance est passee porte `en_retard`. Elle etait donc
    invisible de « entamees »."""
    cree = api.post("/actions", json=_action(test_project["id"], deadline="2020-01-01")).json()
    api.put(f"/actions/{cree['id']}", json={"progress": 45})

    entamees = api.get(f"/actions/in-progress?project_id={test_project['id']}&active_projects_only=false").json()
    assert cree["numero"] in [a["numero"] for a in entamees]

    # Et elle reste bien signalee en retard : les deux vues se recoupent.
    retards = api.get(f"/actions/overdue?project_id={test_project['id']}&active_projects_only=false").json()
    assert cree["numero"] in [a["numero"] for a in retards]


def test_action_non_commencee_absente_de_in_progress(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    entamees = api.get(f"/actions/in-progress?project_id={test_project['id']}&active_projects_only=false").json()
    assert cree["numero"] not in [a["numero"] for a in entamees]


def test_action_terminee_absente_de_in_progress(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    api.put(f"/actions/{cree['id']}", json={"progress": 100})
    entamees = api.get(f"/actions/in-progress?project_id={test_project['id']}&active_projects_only=false").json()
    assert cree["numero"] not in [a["numero"] for a in entamees]


def test_pagination_pages_disjointes(api):
    p1 = api.get("/actions?limit=5&offset=0&active_projects_only=false").json()
    p2 = api.get("/actions?limit=5&offset=5&active_projects_only=false").json()
    assert not ({a["id"] for a in p1} & {a["id"] for a in p2})


def test_tri_par_echeance_croissante(api):
    actions = api.get("/actions?limit=50&active_projects_only=false").json()
    echeances = [a["deadline"] for a in actions if a["deadline"]]
    assert echeances == sorted(echeances)


def test_tri_par_projet_regroupe_les_actions(api):
    """`sort=project` doit regrouper les actions d'un meme projet.

    Sans tri, l'ordre est l'urgence : les 262 actions en retard du
    portefeuille sont reparties sur 11 pages et celles d'un projet donne se
    retrouvent eparpillees sur 4 pages, ce qui rend la vue inutilisable pour
    « ou en est P01 ».
    """
    actions = api.get(
        "/actions?view=overdue&sort=project&limit=200&active_projects_only=false"
    ).json()
    codes = [a["project_code"] for a in actions if a["project_code"]]
    assert codes == sorted(codes), "les codes projet doivent sortir dans l'ordre"
    # Regroupes, donc chaque code n'apparait que dans un seul bloc contigu.
    blocs = [code for i, code in enumerate(codes) if i == 0 or codes[i - 1] != code]
    assert len(blocs) == len(set(blocs))


def test_tri_descendant_inverse_l_ordre(api):
    croissant = api.get(
        "/actions?view=overdue&sort=deadline&order=asc&limit=50&active_projects_only=false"
    ).json()
    decroissant = api.get(
        "/actions?view=overdue&sort=deadline&order=desc&limit=50&active_projects_only=false"
    ).json()
    dates_asc = [a["deadline"] for a in croissant if a["deadline"]]
    dates_desc = [a["deadline"] for a in decroissant if a["deadline"]]
    assert dates_asc == sorted(dates_asc)
    assert dates_desc == sorted(dates_desc, reverse=True)


def test_tri_garde_les_pages_disjointes(api):
    """Un tri sans depart de rang stable ferait reapparaitre la meme action
    sur deux pages : des dizaines d'actions partagent le meme avancement."""
    p1 = api.get("/actions?sort=progress&limit=5&offset=0&active_projects_only=false").json()
    p2 = api.get("/actions?sort=progress&limit=5&offset=5&active_projects_only=false").json()
    assert not ({a["id"] for a in p1} & {a["id"] for a in p2})


def test_tri_inconnu_rejete(api):
    assert api.get("/actions?sort=commentaire").status_code == 422
    assert api.get("/actions?sort=deadline&order=aleatoire").status_code == 422


def test_liste_expose_le_projet_porteur(api, test_project):
    """La colonne « Projet » du tableau lit ces champs : sans eux, il faudrait
    un appel par ligne pour afficher le code du projet."""
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    ligne = next(
        a for a in api.get(
            f"/actions?project_id={test_project['id']}&limit=200&active_projects_only=false"
        ).json()
        if a["id"] == cree["id"]
    )
    assert ligne["project_code"] == test_project["code"]
    assert ligne["project_name"] == test_project["name"]


def test_limit_hors_bornes_rejete(api):
    assert api.get("/actions?limit=0").status_code == 422
    assert api.get("/actions?limit=99999").status_code == 422


def test_action_id_invalide_rejete(api):
    assert api.get("/actions/pas-un-uuid").status_code == 422


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
    api.put(f"/actions/{cree['id']}", json={"progress": 100.0})
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


# --- PUT : un champ, plusieurs champs, ou tous -----------------------------

def test_put_un_seul_champ(api, test_project):
    """Le cas d'usage principal : cocher l'avancement d'une action sans avoir
    à renvoyer le reste de ses champs."""
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    resp = api.put(f"/actions/{cree['id']}", json={"progress": 10})
    assert resp.status_code == 200, resp.text
    corps = resp.json()
    assert corps["progress"] == 10.0
    # La réponse contient l'action complète, pas seulement le champ modifié.
    assert corps["description"] == cree["description"]
    assert corps["numero"] == cree["numero"]
    assert corps["responsables"] == cree["responsables"]


def test_put_plusieurs_champs(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    resp = api.put(
        f"/actions/{cree['id']}",
        json={"progress": 40.0, "commentaire": "Deux champs", "resp_suivi": "Autre"},
    )
    assert resp.status_code == 200
    corps = resp.json()
    assert (corps["progress"], corps["commentaire"], corps["resp_suivi"]) == (
        40.0, "Deux champs", "Autre",
    )
    # Le SPI suit l'avancement sans avoir été envoyé.
    assert corps["spi"] == 40.0
    assert corps["description"] == cree["description"]


def test_put_tous_les_champs(api, test_project):
    """Envoyer l'ensemble des champs modifiables doit fonctionner aussi bien
    qu'un seul, et renvoyer l'action complète."""
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    resp = api.put(
        f"/actions/{cree['id']}",
        json={
            "description": "Description remplacée",
            "resp_suivi": "Nouveau suivi",
            "responsable_names": ["Nouveau"],
            "deadline": "2027-01-31",
            "progress": 25.0,
            "charges_hj": 2.5,
            "commentaire": "Tous les champs",
            "date_realisation": None,
        },
    )
    assert resp.status_code == 200, resp.text
    corps = resp.json()
    assert corps["description"] == "Description remplacée"
    assert corps["resp_suivi"] == "Nouveau suivi"
    assert corps["charges_hj"] == 2.5
    assert [r["display_name"] for r in corps["responsables"]] == ["Nouveau"]


def test_put_ne_touche_pas_aux_champs_absents(api, test_project):
    """Différence assumée avec un PUT « remplacement complet » : ce qui n'est
    pas envoyé est conservé, pas effacé."""
    cree = api.post(
        "/actions",
        json=_action(test_project["id"], commentaire="À conserver", charges_hj=3.0),
    ).json()

    resp = api.put(f"/actions/{cree['id']}", json={"progress": 60.0})
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["progress"] == 60.0
    assert corps["commentaire"] == "À conserver"
    assert corps["charges_hj"] == 3.0


def test_put_progress_100_bascule_le_statut(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    corps = api.put(f"/actions/{cree['id']}", json={"progress": 100}).json()
    assert corps["status"] == "termine"
    assert corps["date_realisation"] is not None


def test_put_vide_rejete(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    assert api.put(f"/actions/{cree['id']}", json={}).status_code == 422


def test_put_refuse_les_champs_calcules(api, test_project):
    """`spi`, `otd` et `numero` sont dérivés : les accepter laisserait croire
    à une saisie possible, que le prochain enregistrement écraserait."""
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    for champ, valeur in (("spi", 75), ("otd", 100), ("numero", "X-01")):
        resp = api.put(f"/actions/{cree['id']}", json={champ: valeur})
        assert resp.status_code == 422, f"{champ} devrait être refusé"
        assert "calcul" in resp.text.lower()


def test_put_statut_derive_refuse(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    assert api.put(f"/actions/{cree['id']}", json={"status": "termine"}).status_code == 422
    assert api.put(f"/actions/{cree['id']}", json={"status": "en_retard"}).status_code == 422
    # `bloque` porte une information non déductible : il reste imposable.
    resp = api.put(f"/actions/{cree['id']}", json={"status": "bloque"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "bloque"


def test_put_spi_otd_suivent_l_avancement(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    assert (cree["spi"], cree["otd"]) == (0.0, 0.0)
    corps = api.put(f"/actions/{cree['id']}", json={"progress": 100}).json()
    assert corps["status"] == "termine"
    assert corps["spi"] == 100.0
    assert corps["otd"] == 100.0, "échéance future respectée"


def test_put_otd_nul_si_echeance_depassee(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"], deadline="2020-01-01")).json()
    corps = api.put(f"/actions/{cree['id']}", json={"progress": 100}).json()
    assert corps["status"] == "termine"
    assert corps["otd"] == 0.0, "livrée après l'échéance"


def test_put_champ_inconnu_rejete(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    resp = api.put(f"/actions/{cree['id']}", json={"progres": 50})
    assert resp.status_code == 422, "une faute de frappe doit être signalée, pas ignorée"


def test_put_change_les_responsables(api, test_project):
    cree = api.post("/actions", json=_action(test_project["id"])).json()
    nouveau = f"Resp-{uuid.uuid4().hex[:6]}"
    resp = api.put(f"/actions/{cree['id']}", json={"responsable_names": [nouveau]})
    assert resp.status_code == 200
    assert [r["display_name"] for r in resp.json()["responsables"]] == [nouveau]


def test_put_projet(api, test_project):
    resp = api.put(
        f"/projects/{test_project['id']}",
        json={"name": "Nom modifié", "is_active": False},
    )
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["name"] == "Nom modifié"
    assert corps["is_active"] is False
    # Le code projet n'est pas modifiable : il est encodé dans le numéro de
    # chacune de ses actions.
    assert corps["code"] == test_project["code"]


def test_put_projet_code_refuse(api, test_project):
    resp = api.put(f"/projects/{test_project['id']}", json={"code": "AUTRE"})
    assert resp.status_code == 422


def test_put_responsable_demappe_avec_email_null(api):
    """Envoyer explicitement `null` démappe ; omettre le champ le conserve."""
    nom = f"Test-{uuid.uuid4().hex[:6]}"
    cree = api.post("/responsables", json={"display_name": nom, "email": "x@trimeta.mg"}).json()
    assert cree["is_mapped"] is True

    conserve = api.put(f"/responsables/{cree['id']}", json={"display_name": nom}).json()
    assert conserve["is_mapped"] is True, "un champ absent ne doit pas être effacé"

    demappe = api.put(f"/responsables/{cree['id']}", json={"email": None}).json()
    assert demappe["is_mapped"] is False
    assert demappe["email"] is None
    api.delete(f"/responsables/{cree['id']}")


def test_patch_nest_plus_expose(api, test_project):
    """PATCH a été retiré au profit de PUT."""
    import requests

    from tests.conftest import VERIFY_TLS

    reponse = requests.patch(
        f"{api._url('/projects/' + test_project['id'])}",
        json={"name": "x"},
        headers=dict(api.session.headers),
        verify=VERIFY_TLS,
        timeout=10,
    )
    assert reponse.status_code == 405


def test_bascule_has_phases_refusee_si_actions(api, test_project):
    api.post("/actions", json=_action(test_project["id"]))
    resp = api.put(f"/projects/{test_project['id']}", json={"has_phases": True})
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
