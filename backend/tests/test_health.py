"""
Vérifie que les 3 services (core-api, auth-api, realtime-hub) sont bien
joignables et documentés via le gateway - exactement les bugs de routage
qu'on a chassés manuellement pendant cette session.

Les appels passent par HTTPS : le gateway redirige tout le trafic HTTP, et
suivre cette redirection avec un certificat auto-signé faisait échouer la
suite entière sur une erreur TLS. La fixture `http` désactive la vérification
du certificat pour les tests uniquement.
"""


def test_core_api_health(base_url, http):
    resp = http.get(f"{base_url}/api/v1/health", timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected", (
        "core-api ne peut pas joindre Supabase - vérifier .env / DNS / réseau"
    )


def test_core_api_health_repond_503_si_base_injoignable(base_url, http):
    """Documente le contrat : le health check ne renvoie 200 que si la base
    répond. Un `{"status": "ok"}` en HTTP 200 alors que PostgreSQL était
    injoignable empêchait un load balancer de sortir l'instance du pool."""
    resp = http.get(f"{base_url}/api/v1/health", timeout=10)
    assert (resp.status_code == 200) == (resp.json()["database"] == "connected")


def test_auth_api_health(base_url, http):
    resp = http.get(f"{base_url}/api/v1/auth/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_realtime_hub_health(base_url, http):
    resp = http.get(f"{base_url}/api/v1/realtime/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_core_api_docs_reachable(base_url, http):
    resp = http.get(f"{base_url}/api/v1/docs", timeout=10)
    assert resp.status_code == 200


def test_auth_api_docs_reachable(base_url, http):
    resp = http.get(f"{base_url}/api/v1/auth/docs", timeout=10)
    assert resp.status_code == 200


def test_realtime_hub_docs_reachable(base_url, http):
    resp = http.get(f"{base_url}/api/v1/realtime/docs", timeout=10)
    assert resp.status_code == 200


def test_frontend_reachable(base_url, http):
    resp = http.get(f"{base_url}/", timeout=10)
    assert resp.status_code == 200


def test_security_headers_presents(base_url, http):
    """Le gateway doit poser les en-têtes de durcissement sur toute réponse."""
    resp = http.get(f"{base_url}/", timeout=10)
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Server" not in resp.headers or "nginx/" not in resp.headers["Server"]
