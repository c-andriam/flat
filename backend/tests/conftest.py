import os
import uuid

import pytest
import requests

BASE_URL = os.getenv("DSIO_TEST_BASE_URL", "http://localhost:8080")


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def api(base_url):
    """Petit wrapper autour de requests, préfixe automatiquement /api/v1."""

    class Api:
        def get(self, path, **kw):
            return requests.get(f"{base_url}/api/v1{path}", timeout=10, **kw)

        def post(self, path, **kw):
            return requests.post(f"{base_url}/api/v1{path}", timeout=10, **kw)

        def patch(self, path, **kw):
            return requests.patch(f"{base_url}/api/v1{path}", timeout=10, **kw)

        def delete(self, path, **kw):
            return requests.delete(f"{base_url}/api/v1{path}", timeout=10, **kw)

    return Api()


@pytest.fixture
def test_project(api):
    """
    Crée un projet de test isolé (code unique à chaque run) et le supprime
    à la fin, avec cascade sur ses actions. N'utilise jamais les données
    réelles de production - toujours un code préfixé TEST- unique.
    """
    code = f"TEST-{uuid.uuid4().hex[:8]}"
    resp = api.post(
        "/projects",
        json={
            "code": code,
            "name": "Projet de test automatisé",
            "source_file_path": "07_Projets_DSIO/Projet encours/TEST/test.xlsx",
        },
    )
    assert resp.status_code == 201, f"Échec création projet de test: {resp.text}"
    project = resp.json()

    yield project

    api.delete(f"/projects/{project['id']}")


@pytest.fixture
def test_project_with_phases(api):
    """Variante avec has_phases=True, pour tester la contrainte 'phase obligatoire'."""
    code = f"TEST-PH-{uuid.uuid4().hex[:8]}"
    resp = api.post(
        "/projects",
        json={
            "code": code,
            "name": "Projet de test avec phases",
            "source_file_path": "07_Projets_DSIO/Projet encours/TEST/test_phases.xlsx",
            "has_phases": True,
        },
    )
    assert resp.status_code == 201, f"Échec création projet de test: {resp.text}"
    project = resp.json()

    yield project

    api.delete(f"/projects/{project['id']}")
