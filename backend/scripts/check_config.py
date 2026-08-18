#!/usr/bin/env python3
"""
Diagnostic de configuration : dit en une page ce qui empêche la plateforme
de démarrer, au lieu d'une centaine de lignes de trace SQLAlchemy.

    podman exec -it dsio-core-api python3 scripts/check_config.py
    make doctor

Vérifie, dans l'ordre : les variables d'environnement, la résolution DNS de
l'hôte PostgreSQL, la connexion à la base, la connexion à Redis, et l'état de
la configuration Entra ID. Les valeurs sensibles ne sont jamais affichées en
clair — seulement leur longueur et le fait qu'elles soient renseignées.

Code de sortie : 0 si tout est vert, 1 s'il reste au moins un blocage.
"""

import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OK = "  [ OK ]"
KO = "  [FAIL]"
WARN = "  [WARN]"

_failures: list[str] = []
_warnings: list[str] = []


def ok(message: str) -> None:
    print(f"{OK} {message}")


def fail(message: str, remedy: str) -> None:
    print(f"{KO} {message}")
    print(f"         -> {remedy}")
    _failures.append(message)


def warn(message: str, remedy: str) -> None:
    print(f"{WARN} {message}")
    print(f"         -> {remedy}")
    _warnings.append(message)


def mask(value: str | None) -> str:
    """N'affiche que la longueur : la sortie de ce script finit souvent
    collée dans un ticket ou un chat, elle ne doit contenir aucun fragment
    de secret exploitable."""
    if not value:
        return "(vide)"
    return f"renseigné, {len(value)} caractères"


def section(title: str) -> None:
    print()
    print(f"--- {title} " + "-" * max(0, 58 - len(title)))


def main() -> int:
    print()
    print("=" * 64)
    print(" Diagnostic de configuration DSIO")
    print("=" * 64)

    # ------------------------------------------------------------------
    section("Variables d'environnement")
    try:
        from app.config import ConfigError, settings
    except Exception as exc:
        fail(
            f"Chargement de la configuration impossible : {exc}",
            "Vérifier que les variables POSTGRES_* sont bien présentes dans .env.",
        )
        return 1

    ok(f"APP_ENV = {settings.env}" + ("  (contrôles stricts actifs)" if settings.is_production else ""))
    ok(f"POSTGRES_HOST = {settings.postgres_host}:{settings.postgres_port}")
    ok(f"POSTGRES_USER = {settings.postgres_user}")
    ok(f"POSTGRES_DB   = {settings.postgres_db}")
    print(f"         mot de passe : {mask(settings.postgres_password)}")

    # ------------------------------------------------------------------
    section("Clé de signature des jetons")
    try:
        key = settings.secret_key
        ok(f"SECRET_KEY valide : {mask(key)}")
    except ConfigError as exc:
        fail(
            str(exc),
            'Générer une clé puis la placer dans .env :\n'
            '            python3 -c "import secrets; print(secrets.token_urlsafe(48))"',
        )

    # ------------------------------------------------------------------
    section("Résolution DNS de l'hôte PostgreSQL")
    try:
        infos = socket.getaddrinfo(settings.postgres_host, settings.postgres_port, proto=socket.IPPROTO_TCP)
        adresses = sorted({info[4][0] for info in infos})
        ok(f"{settings.postgres_host} -> {', '.join(adresses)}")
    except socket.gaierror as exc:
        fail(
            f"{settings.postgres_host} ne résout pas ({exc})",
            "Problème DNS côté conteneur : vérifier la section `dns:` de compose.yml.",
        )
        adresses = []

    # ------------------------------------------------------------------
    section("Connexion PostgreSQL")
    if adresses:
        try:
            with socket.create_connection((settings.postgres_host, settings.postgres_port), timeout=8):
                ok(f"Port {settings.postgres_port} joignable")
        except OSError as exc:
            fail(
                f"Port {settings.postgres_port} injoignable ({exc})",
                "Pare-feu ou sortie réseau bloquée depuis le serveur.",
            )

    try:
        import psycopg2

        conn = psycopg2.connect(
            user=settings.postgres_user,
            password=settings.postgres_password,
            dbname=settings.postgres_db,
            host=settings.postgres_host,
            port=settings.postgres_port,
            sslmode="require",
            connect_timeout=10,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
            tables = cur.fetchone()[0]
        conn.close()
        ok(f"Connecté — {version.split(',')[0]}")
        ok(f"{tables} table(s) dans le schéma public")
        if tables == 0:
            warn(
                "Base vide : aucune table dans le schéma public.",
                "Appliquer les migrations : make migrate",
            )
    except Exception as exc:
        message = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
        if "Tenant or user not found" in str(exc) or "ENOTFOUND" in str(exc):
            fail(
                f"Supabase refuse l'identifiant : {message}",
                "Le pooler ne trouve pas ce projet. Trois causes, à vérifier\n"
                "            dans cet ordre sur https://supabase.com/dashboard :\n"
                "            1. le projet est en pause (offre gratuite) -> le relancer ;\n"
                "            2. POSTGRES_HOST ne correspond pas à la région du projet\n"
                "               (le pooler identifie le tenant d'après la région) ;\n"
                "            3. la référence du projet dans POSTGRES_USER\n"
                "               (postgres.<ref>) ne correspond plus au projet.\n"
                "            Copier la chaîne « Connection pooling » du tableau de bord.",
            )
        elif "password authentication failed" in str(exc):
            fail(
                "Mot de passe refusé par PostgreSQL.",
                "Mettre à jour POSTGRES_PASSWORD dans .env avec la valeur du tableau de bord.",
            )
        else:
            fail(f"Connexion impossible : {message}", "Voir le message ci-dessus.")

    # ------------------------------------------------------------------
    section("Connexion Redis")
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=5)
        client.ping()
        client.close()
        ok(f"{settings.redis_url} répond au PING")
    except Exception as exc:
        fail(
            f"Redis injoignable ({exc.__class__.__name__})",
            "Vérifier que le conteneur dsio-redis tourne : podman ps",
        )

    # ------------------------------------------------------------------
    section("Microsoft Entra ID (SSO)")
    placeholders = {"", "your_azure_client_secret_here", "00000000-0000-0000-0000-000000000000"}
    azure = {
        "AZURE_CLIENT_ID": os.getenv("AZURE_CLIENT_ID", ""),
        "AZURE_TENANT_ID": os.getenv("AZURE_TENANT_ID", ""),
        "AZURE_CLIENT_SECRET": os.getenv("AZURE_CLIENT_SECRET", ""),
    }
    manquants = [name for name, value in azure.items() if value in placeholders]
    if manquants:
        warn(
            f"SSO non configuré : {', '.join(manquants)} encore à leur valeur d'exemple.",
            "La connexion Microsoft ne fonctionnera pas. Pour tester l'API en\n"
            "            attendant : make token EMAIL=prenom.nom@trimetagroup.mg",
        )
    else:
        ok("Les trois variables Azure sont renseignées.")
        ok(f"Redirect URI : {settings.azure_redirect_uri}")

    # ------------------------------------------------------------------
    section("Amorçage RBAC")
    if settings.bootstrap_admin_emails:
        ok(f"BOOTSTRAP_ADMIN_EMAILS : {', '.join(sorted(settings.bootstrap_admin_emails))}")
    else:
        warn(
            "BOOTSTRAP_ADMIN_EMAILS est vide.",
            "Sans au moins une adresse, aucun compte ne deviendra administrateur\n"
            "            à la connexion SSO (/users est réservé aux admins).",
        )

    # ------------------------------------------------------------------
    print()
    print("=" * 64)
    if _failures:
        print(f" {len(_failures)} blocage(s), {len(_warnings)} avertissement(s)")
        print(" La plateforme ne peut pas fonctionner en l'état.")
    elif _warnings:
        print(f" Aucun blocage, {len(_warnings)} avertissement(s)")
    else:
        print(" Configuration complète et fonctionnelle.")
    print("=" * 64)
    print()
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
