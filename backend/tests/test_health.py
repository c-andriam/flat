"""
Vérifie que les 3 services (core-api, auth-api, realtime-hub) sont bien
joignables et documentés via le gateway - exactement les bugs de routage
qu'on a chassés manuellement pendant cette session.
"""
import requests


def test_core_api_health(base_url):
    resp = requests.get(f"{base_url}/api/v1/health", timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected", (
        "core-api ne peut pas joindre Supabase - vérifier .env / DNS / réseau"
    )


def test_auth_api_health(base_url):
    resp = requests.get(f"{base_url}/api/v1/auth/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_realtime_hub_health(base_url):
    resp = requests.get(f"{base_url}/api/v1/realtime/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_core_api_docs_reachable(base_url):
    resp = requests.get(f"{base_url}/api/v1/docs", timeout=10)
    assert resp.status_code == 200


def test_auth_api_docs_reachable(base_url):
    resp = requests.get(f"{base_url}/api/v1/auth/docs", timeout=10)
    assert resp.status_code == 200


def test_realtime_hub_docs_reachable(base_url):
    resp = requests.get(f"{base_url}/api/v1/realtime/docs", timeout=10)
    assert resp.status_code == 200


def test_frontend_reachable(base_url):
    resp = requests.get(f"{base_url}/", timeout=10)
    assert resp.status_code == 200
