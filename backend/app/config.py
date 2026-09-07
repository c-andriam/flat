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
    # Verification « la connexion est-elle encore vivante ? » avant chaque
    # emprunt au pool. Elle protege des coupures du pooler Supabase, mais
    # coute un aller-retour complet : mesure a ~780 ms par requete depuis
    # Madagascar, soit la moitie du temps de reponse de l'API. La passer a
    # false accelere nettement, au prix d'erreurs sporadiques si le pooler
    # ferme une connexion inactive.
    db_pool_pre_ping: bool = _bool("DB_POOL_PRE_PING", True)
    # Duree de mise en cache du profil d'un compte (role, activation), en
    # secondes. Chaque requete relisait ce profil en base : un aller-retour
    # complet, soit environ un tiers du temps de reponse. 0 desactive le cache
    # et retablit la relecture systematique.
    auth_cache_ttl_seconds: int = _int("AUTH_CACHE_TTL_SECONDS", 30)
    # `require` par defaut : Supabase impose TLS. Une instance PostgreSQL
    # locale de developpement n'a pas de certificat, d'ou `disable` — la
    # valeur etait codee en dur, ce qui rendait tout travail hors ligne
    # impossible.
    db_ssl_mode: str = os.getenv("DB_SSL_MODE", "require").strip().lower()
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

    # --- SharePoint (Microsoft Graph, permissions d'application) ---
    # Hote du tenant, ex. « trimetagroup.sharepoint.com ». Vide, l'integration
    # fichiers est simplement inactive : l'import depuis un dossier local
    # continue de fonctionner.
    sharepoint_hostname: str = os.getenv("SHAREPOINT_HOSTNAME", "").strip()
    # Chemin du site, ex. « /sites/DSIO ». Vide = site racine du tenant.
    sharepoint_site_path: str = os.getenv("SHAREPOINT_SITE_PATH", "").strip()
    # Bibliotheque de documents. Vide = bibliotheque par defaut du site.
    sharepoint_drive_name: str = os.getenv("SHAREPOINT_DRIVE_NAME", "").strip()
    sharepoint_root_folder_path: str = os.getenv(
        "SHAREPOINT_ROOT_FOLDER_PATH", ""
    ).strip().strip("/")

    @property
    def sharepoint_configured(self) -> bool:
        return bool(self.sharepoint_hostname)

    # --- RBAC ---
    # Sans ça, le tout premier utilisateur se connecte en `lecteur` et personne
    # ne peut promouvoir personne : /users est réservé aux admins (impasse).
    @property
    def bootstrap_admin_emails(self) -> frozenset[str]:
        return _csv_set("BOOTSTRAP_ADMIN_EMAILS")

    # --- Relances ---
    # Fenêtre d'alerte par défaut : une action est signalée à partir de J-3.
    # Chaque personne peut la redéfinir dans ses préférences de relance.
    relance_horizon_days: int = _int("RELANCE_HORIZON_DAYS", 3)
    # Délai minimal entre deux relances d'un même responsable. Ne concerne que
    # les rappels ponctuels par nature (`/relances/{id}/send`) : le
    # récapitulatif planifié est cadencé par les préférences de chacun, et son
    # garde-fou est « un seul envoi par jour », pas un délai glissant.
    relance_cooldown_days: int = _int("RELANCE_COOLDOWN_DAYS", 3)
    # Fuseau dans lequel s'entendent les heures d'envoi choisies par les
    # utilisateurs. Il doit rester aligné sur celui du planificateur Celery :
    # `send_hour = 8` doit vouloir dire 8 h pour la personne qui l'a réglé,
    # pas 8 h UTC — soit 11 h à Antananarivo.
    relance_timezone: str = os.getenv("RELANCE_TIMEZONE", "Indian/Antananarivo").strip()


settings = Settings()
