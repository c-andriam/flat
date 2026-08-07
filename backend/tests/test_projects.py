"""CRUD complet sur /projects, avec cleanup automatique via la fixture test_project."""
import uuid


def test_create_project(api):
    code = f"TEST-{uuid.uuid4().hex[:8]}"
    resp = api.post(
        "/projects",
        json={
            "code": code,
            "name": "Projet créé par test",
            "source_file_path": "07_Projets_DSIO/Projet encours/TEST/x.xlsx",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["code"] == code
    assert body["is_active"] is True
    assert body["has_phases"] is False
    assert "id" in body

    # cleanup
    api.delete(f"/projects/{body['id']}")


def test_create_project_duplicate_code_rejected(api, test_project):
    resp = api.post(
        "/projects",
        json={
            "code": test_project["code"],
            "name": "Doublon",
            "source_file_path": "x.xlsx",
        },
    )
    assert resp.status_code == 409


def test_get_project(api, test_project):
    resp = api.get(f"/projects/{test_project['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == test_project["id"]
    assert resp.json()["actions"] == []


def test_get_project_not_found(api):
    resp = api.get(f"/projects/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_list_projects_includes_created(api, test_project):
    resp = api.get("/projects")
    assert resp.status_code == 200
    codes = [p["code"] for p in resp.json()]
    assert test_project["code"] in codes


def test_update_project(api, test_project):
    resp = api.patch(f"/projects/{test_project['id']}", json={"name": "Nom modifié"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Nom modifié"


def test_delete_project(api):
    code = f"TEST-DEL-{uuid.uuid4().hex[:8]}"
    created = api.post(
        "/projects",
        json={"code": code, "name": "À supprimer", "source_file_path": "x.xlsx"},
    ).json()

    resp = api.delete(f"/projects/{created['id']}")
    assert resp.status_code == 204

    resp = api.get(f"/projects/{created['id']}")
    assert resp.status_code == 404
