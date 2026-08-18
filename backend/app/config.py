"""
Configuration centralisée et validée de la plateforme DSIO.

Objectif : un seul endroit où lire l'environnement, avec des valeurs typées
et des erreurs explicites au démarrage plutôt que des `None` qui se propagent
jusqu'à un 500 en production.

Deux niveaux de validation :
  - les variables *infrastructure* (PostgreSQL) sont lues à l'import : sans
    elles aucun service ne peut démarrer, autant échouer immédiatement ;
  - les variables *fonctionnelles* (SECRET_KEY, AZURE_*) sont exposées via des
    propriétés : seuls les services qui s'en servent (auth-api, realtime-hub)
    échouent si elles manquent, ce qui laisse tourner alembic ou un worker
    d'ingestion sans configuration Azure.
"""

import os

# Valeurs livrées dans .env.example : utiles en local, jamais en production.
_PLACEHOLDER_SECRETS = {
    "super-secret-key-change-in-production-32-chars",
    "change-me",
    "changeme",
}


class ConfigError(RuntimeError):
    """Configuration absente ou invalide — le service ne peut pas démarrer."""


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"Variable d'environnement manquante : {name}")
    return value


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} doit être un entier, reçu : {raw!r}")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _csv_set(name: str) -> frozenset[str]:
    raw = os.getenv(name, "")
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


class Settings:
    # --- Environnement ---
    env: str = os.getenv("APP_ENV", "production").strip().lower()
    log_level: str = os.getenv("LOG_LEVEL", "INFO").strip().upper()

    @property
    def is_production(self) -> bool:
        return self.env not in ("dev", "development", "local", "test")

    # --- PostgreSQL (Supabase) ---
    postgres_user: str = _required("POSTGRES_USER")
    postgres_password: str = _required("POSTGRES_PASSWORD")
    postgres_db: str = _required("POSTGRES_DB")
    # Pas de défaut : la base est distante (Supabase), un défaut "postgres"
    # masquerait une erreur de configuration derrière un timeout réseau.
    postgres_host: str = _required("POSTGRES_HOST")
    postgres_port: int = _int("POSTGRES_PORT", 5432)

    # Supabase impose un plafond global de connexions, partagé par TOUS les
    # conteneurs (3 APIs + 3 workers). 5+5 par process reste sous la limite du
    # pooler ; à ajuster via l'environnement si l'offre change.
    db_pool_size: int = _int("DB_POOL_SIZE", 5)
    db_max_overflow: int = _int("DB_MAX_OVERFLOW", 5)
    db_pool_recycle: int = _int("DB_POOL_RECYCLE", 1800)
    db_echo: bool = _bool("DB_ECHO", False)

    # --- Redis ---
    redis_host: str = os.getenv("REDIS_HOST", "redis")
    redis_port: int = _int("REDIS_PORT", 6379)
    redis_db: int = _int("REDIS_DB", 0)

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # --- Frontend / CORS / cookies ---
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:8080").rstrip("/")

    @property
    def cors_origins(self) -> list[str]:
        raw = os.getenv("CORS_ORIGINS")
        if raw:
            return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
        return [self.frontend_url]

    # Les cookies ne doivent partir qu'en HTTPS ; le gateway force déjà la
    # redirection, mais un poste de dev en http:// a besoin de désactiver ça.
    cookie_secure: bool = _bool("COOKIE_SECURE", True)

    # --- JWT ---
    algorithm: str = os.getenv("ALGORITHM", "HS256")
    access_token_expire_minutes: int = _int("ACCESS_TOKEN_EXPIRE_MINUTES", 480)

    @property
    def secret_key(self) -> str:
        value = _required("SECRET_KEY")
        if len(value) < 32:
            raise ConfigError(
                "SECRET_KEY doit faire au moins 32 caractères "
                f"(actuellement {len(value)})."
            )
        if self.is_production and value in _PLACEHOLDER_SECRETS:
            raise ConfigError(
                "SECRET_KEY est encore la valeur d'exemple : générer une clé "
                "avec `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`."
            )
        return value

    # --- Microsoft Entra ID (SSO) ---
    azure_redirect_uri: str = os.getenv(
        "AZURE_REDIRECT_URI", "http://localhost:8080/api/v1/auth/callback"
    )

    @property
    def azure_client_id(self) -> str:
        return _required("AZURE_CLIENT_ID")

    @property
    def azure_tenant_id(self) -> str:
        return _required("AZURE_TENANT_ID")

    @property
    def azure_client_secret(self) -> str:
        return _required("AZURE_CLIENT_SECRET")

    # --- RBAC ---
    # Sans ça, le tout premier utilisateur se connecte en `lecteur` et personne
    # ne peut promouvoir personne : /users est réservé aux admins (impasse).
    @property
    def bootstrap_admin_emails(self) -> frozenset[str]:
        return _csv_set("BOOTSTRAP_ADMIN_EMAILS")

    # --- Relances ---
    # Fenêtre d'alerte : une action est relancée à partir de J-3.
    relance_horizon_days: int = _int("RELANCE_HORIZON_DAYS", 3)
    # Délai minimal entre deux relances d'un même responsable, pour éviter
    # qu'un beat quotidien ne transforme l'outil en spam.
    relance_cooldown_days: int = _int("RELANCE_COOLDOWN_DAYS", 3)


settings = Settings()
