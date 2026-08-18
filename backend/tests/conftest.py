import os
import uuid

import pytest
import requests
import urllib3

BASE_URL = os.getenv("DSIO_TEST_BASE_URL", "https://localhost:8443")

# Le gateway redirige tout le trafic HTTP vers HTTPS et presente un certificat
# auto-signe emis pour « localhost » : appele depuis le reseau interne
# (https://gateway) sa validation echoue forcement. On desactive donc la
# verification pour la suite de tests uniquement, jamais dans le code applicatif.
VERIFY_TLS = os.getenv("DSIO_TEST_VERIFY_TLS", "false").lower() in ("1", "true", "yes")
if not VERIFY_TLS:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Compte technique utilisé par la suite. Il n'a pas d'équivalent Entra ID :
# il ne peut donc pas servir à se connecter via le SSO, seulement à signer
# un JWT local pour appeler l'API.
TEST_USER_EMAIL = "pytest.suite@trimeta.local"


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def http():
    """Session requests brute (sans jeton), tolerante au certificat auto-signe."""
    session = requests.Session()
    session.verify = VERIFY_TLS
    return session


@pytest.fixture(scope="session")
def auth_token():
    """JWT admin pour la suite de tests.

    Les routes métier exigent désormais un jeton (elles étaient toutes
    ouvertes avant l'audit). Le jeton est fabriqué localement avec la même
    SECRET_KEY que l'API — ce qui suppose de lancer les tests dans le
    conteneur core-api, comme le fait `make test`. Depuis l'extérieur,
    fournir un jeton déjà émis via DSIO_TEST_TOKEN.
    """
    token = os.getenv("DSIO_TEST_TOKEN")
    if token:
        return token

    try:
        from app.database import SessionLocal
        from app.models.user import User, UserRole
        from app.services.security import create_access_token
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        pytest.skip(
            "Impossible d'importer l'application pour forger un jeton de test "
            f"({exc}). Lancer la suite dans le conteneur core-api "
            "(`make test`) ou définir DSIO_TEST_TOKEN."
        )

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_USER_EMAIL).first()
        if user is None:
            user = User(
                azure_object_id=f"pytest-{uuid.uuid4().hex[:24]}",
                email=TEST_USER_EMAIL,
                display_name="Suite de tests automatisés",
                role=UserRole.ADMIN,
            )
            db.add(user)
        else:
            user.role = UserRole.ADMIN
            user.is_active = True
        db.commit()
        db.refresh(user)
        return create_access_token(user)
    finally:
        db.close()


@pytest.fixture(scope="session")
def api(base_url, auth_token):
    """Petit wrapper autour de requests, préfixe automatiquement /api/v1
    et joint le header Authorization."""

    class Api:
        def __init__(self):
            self.session = requests.Session()
            self.session.verify = VERIFY_TLS
            self.session.headers["Authorization"] = f"Bearer {auth_token}"

        def _url(self, path):
            return f"{base_url}/api/v1{path}"

        def get(self, path, **kw):
            return self.session.get(self._url(path), timeout=10, **kw)

        def post(self, path, **kw):
            return self.session.post(self._url(path), timeout=10, **kw)

        def patch(self, path, **kw):
            return self.session.patch(self._url(path), timeout=10, **kw)

        def delete(self, path, **kw):
            return self.session.delete(self._url(path), timeout=10, **kw)

    return Api()


@pytest.fixture(scope="session")
def anon_api(base_url, http):
    """Client sans jeton, pour vérifier que les routes sont bien protégées."""

    class AnonApi:
        def _url(self, path):
            return f"{base_url}/api/v1{path}"

        def get(self, path, **kw):
            return http.get(self._url(path), timeout=10, **kw)

        def post(self, path, **kw):
            return http.post(self._url(path), timeout=10, **kw)

        def patch(self, path, **kw):
            return http.patch(self._url(path), timeout=10, **kw)

        def delete(self, path, **kw):
            return http.delete(self._url(path), timeout=10, **kw)

    return AnonApi()


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
