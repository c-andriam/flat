"""
CRUD complet sur /actions + toutes les règles métier durcies pendant
cette session : champs obligatoires, defaults spi/otd=0.0, has_phases,
numérotation automatique.
"""
import uuid


def _valid_action_payload(project_id, **overrides):
    payload = {
        "project_id": project_id,
        "description": "Action de test",
        "resp_suivi": "Testeur",
        "deadline": "2026-12-31",
        "responsable_names": ["Testeur"],
    }
    payload.update(overrides)
    return payload


def test_create_action_missing_required_fields_rejected(api, test_project):
    resp = api.post("/actions", json={
        "project_id": test_project["id"],
        "description": "incomplet",
    })
    assert resp.status_code == 422
    missing = {err["loc"][-1] for err in resp.json()["detail"]}
    assert {"resp_suivi", "deadline", "responsable_names"} <= missing


def test_create_action_empty_responsables_rejected(api, test_project):
    resp = api.post("/actions", json=_valid_action_payload(
        test_project["id"], responsable_names=[]
    ))
    assert resp.status_code == 422


def test_create_action_valid(api, test_project):
    resp = api.post("/actions", json=_valid_action_payload(test_project["id"]))
    assert resp.status_code == 201
    body = resp.json()

    # Les 3 règles qu'on a durcies cette session : jamais null par défaut
    assert body["spi"] == 0.0
    assert body["otd"] == 0.0
    assert body["progress"] == 0.0
    assert len(body["responsables"]) == 1
    assert body["responsables"][0]["display_name"] == "Testeur"
    assert body["date_realisation"] is None  # doit rester null tant que pas terminé
    assert body["numero"].startswith(test_project["code"])


def test_create_action_numero_auto_increments(api, test_project):
    r1 = api.post("/actions", json=_valid_action_payload(test_project["id"])).json()
    r2 = api.post("/actions", json=_valid_action_payload(test_project["id"])).json()
    assert r1["numero"] != r2["numero"]


def test_create_action_on_phased_project_requires_phase(api, test_project_with_phases):
    resp = api.post("/actions", json=_valid_action_payload(test_project_with_phases["id"]))
    assert resp.status_code == 422
    assert "phase" in resp.json()["detail"].lower()


def test_create_action_on_phased_project_with_phase_ok(api, test_project_with_phases):
    resp = api.post("/actions", json=_valid_action_payload(
        test_project_with_phases["id"], phase="01"
    ))
    assert resp.status_code == 201
    assert "-01-" in resp.json()["numero"]


def test_create_action_project_not_found(api):
    resp = api.post("/actions", json=_valid_action_payload(str(uuid.uuid4())))
    assert resp.status_code == 404


def test_get_action(api, test_project):
    created = api.post("/actions", json=_valid_action_payload(test_project["id"])).json()
    resp = api.get(f"/actions/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_list_actions_filter_by_project(api, test_project):
    api.post("/actions", json=_valid_action_payload(test_project["id"]))
    resp = api.get(f"/actions?project_id={test_project['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert all(a["project_id"] == test_project["id"] for a in body)


def test_update_action_progress(api, test_project):
    created = api.post("/actions", json=_valid_action_payload(test_project["id"])).json()
    resp = api.put(f"/actions/{created['id']}", json={"progress": 50.0})
    assert resp.status_code == 200
    assert resp.json()["progress"] == 50.0
    # Passer à 50% ne change pas le statut tout seul, il faut le faire explicitement
    assert resp.json()["status"] == "a_faire"


def test_update_action_progress_100_marks_termine(api, test_project):
    created = api.post("/actions", json=_valid_action_payload(test_project["id"])).json()
    resp = api.put(f"/actions/{created['id']}", json={"progress": 100.0})
    assert resp.status_code == 200
    assert resp.json()["status"] == "termine"
    # date_realisation doit se remplir automatiquement dès que l'action est terminée
    assert resp.json()["date_realisation"] is not None


def test_delete_action(api, test_project):
    created = api.post("/actions", json=_valid_action_payload(test_project["id"])).json()
    resp = api.delete(f"/actions/{created['id']}")
    assert resp.status_code == 204
    assert api.get(f"/actions/{created['id']}").status_code == 404


def test_create_action_progress_out_of_bounds_rejected(api, test_project):
    resp = api.post("/actions", json=_valid_action_payload(test_project["id"], progress=150.0))
    assert resp.status_code == 422

    resp = api.post("/actions", json=_valid_action_payload(test_project["id"], progress=-10.0))
    assert resp.status_code == 422


def test_update_action_progress_out_of_bounds_rejected(api, test_project):
    created = api.post("/actions", json=_valid_action_payload(test_project["id"])).json()
    resp = api.put(f"/actions/{created['id']}", json={"progress": 101.0})
    assert resp.status_code == 422


def test_update_action_phase_regenerates_numero(api, test_project_with_phases):
    created = api.post("/actions", json=_valid_action_payload(
        test_project_with_phases["id"], phase="01"
    )).json()
    assert "-01-" in created["numero"]

    resp = api.put(f"/actions/{created['id']}", json={"phase": "02"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["phase"] == "02"
    assert "-02-" in body["numero"]
    assert "-01-" not in body["numero"]


def test_update_action_phase_forbidden_on_non_phased_project(api, test_project):
    created = api.post("/actions", json=_valid_action_payload(test_project["id"])).json()
    resp = api.put(f"/actions/{created['id']}", json={"phase": "01"})
    assert resp.status_code == 422


def test_update_action_phase_required_on_phased_project(api, test_project_with_phases):
    created = api.post("/actions", json=_valid_action_payload(
        test_project_with_phases["id"], phase="01"
    )).json()
    resp = api.put(f"/actions/{created['id']}", json={"phase": None})
    assert resp.status_code == 422
