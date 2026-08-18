"""CRUD sur /responsables et logique de mapping nom Excel <-> email."""
import uuid


def test_create_responsable(api):
    name = f"Test-{uuid.uuid4().hex[:6]}"
    resp = api.post("/responsables", json={"display_name": name})
    assert resp.status_code == 201
    body = resp.json()
    assert body["display_name"] == name
    assert body["is_mapped"] is False
    assert body["email"] is None

    api.delete(f"/responsables/{body['id']}")


def test_create_responsable_duplicate_rejected(api):
    name = f"Test-{uuid.uuid4().hex[:6]}"
    first = api.post("/responsables", json={"display_name": name}).json()

    resp = api.post("/responsables", json={"display_name": name})
    assert resp.status_code == 409

    api.delete(f"/responsables/{first['id']}")


def test_auto_created_responsable_via_action_is_unmapped(api, test_project):
    unique_name = f"Auto-{uuid.uuid4().hex[:6]}"
    resp = api.post("/actions", json={
        "project_id": test_project["id"],
        "description": "test",
        "resp_suivi": "x",
        "deadline": "2026-12-31",
        "responsable_names": [unique_name],
    })
    assert resp.status_code == 201

    listed = api.get("/responsables?unmapped_only=true").json()
    names = [r["display_name"] for r in listed]
    assert unique_name in names


def test_map_responsable_email(api):
    name = f"Test-{uuid.uuid4().hex[:6]}"
    created = api.post("/responsables", json={"display_name": name}).json()

    resp = api.put(f"/responsables/{created['id']}", json={"email": "test@trimeta.mg"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "test@trimeta.mg"
    assert resp.json()["is_mapped"] is True

    api.delete(f"/responsables/{created['id']}")


def test_get_responsable_not_found(api):
    resp = api.get(f"/responsables/{uuid.uuid4()}")
    assert resp.status_code == 404
