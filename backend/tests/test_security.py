"""
Non-régression sur le trou de sécurité corrigé pendant l'audit : avant, la
totalité de /api/v1 (projets, actions, responsables, journaux) répondait sans
aucun jeton — n'importe qui atteignant le gateway pouvait lire et supprimer le
portefeuille projet de la DSI.
"""
import uuid

import pytest

PROTECTED_READS = [
    "/projects",
    "/actions",
    "/responsables",
    "/sync-logs",
    "/relance-logs",
    "/users",
]


@pytest.mark.parametrize("path", PROTECTED_READS)
def test_read_requires_token(anon_api, path):
    resp = anon_api.get(path)
    assert resp.status_code in (401, 403), (
        f"{path} répond {resp.status_code} sans jeton — la route est ouverte."
    )


def test_write_requires_token(anon_api):
    resp = anon_api.post(
        "/projects",
        json={
            "code": f"HACK-{uuid.uuid4().hex[:8]}",
            "name": "Créé sans authentification",
            "source_file_path": "x.xlsx",
        },
    )
    assert resp.status_code in (401, 403)


def test_delete_requires_token(anon_api):
    resp = anon_api.delete(f"/projects/{uuid.uuid4()}")
    assert resp.status_code in (401, 403)


def test_invalid_token_rejected(base_url, http):
    resp = http.get(
        f"{base_url}/api/v1/projects",
        headers={"Authorization": "Bearer pas-un-vrai-jwt"},
        timeout=10,
    )
    assert resp.status_code == 401


def test_health_stays_public(anon_api):
    """Les sondes de supervision ne doivent pas avoir besoin d'un jeton."""
    resp = anon_api.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_valid_token_grants_access(api):
    resp = api.get("/projects")
    assert resp.status_code == 200
    assert "X-Total-Count" in resp.headers
