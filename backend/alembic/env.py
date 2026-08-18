import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Permet d'importer "app.*" quand alembic est lancé depuis backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SQLALCHEMY_DATABASE_URL, Base  # noqa: E402
from app import models  # noqa: E402,F401  (enregistre tous les modèles sur Base.metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    """DSN de migration, dérivé de la configuration applicative.

    L'URL était reconstruite ici à partir des variables d'environnement, en
    double de `app.database` — avec un défaut `POSTGRES_HOST=postgres` qui
    n'existe pas dans ce déploiement (base Supabase distante) : une variable
    oubliée faisait migrer dans le vide au lieu d'échouer.

    `sslmode=require` est passé dans l'URL car `engine_from_config` ne
    transmet pas les `connect_args` du moteur applicatif.
    """
    separator = "&" if "?" in SQLALCHEMY_DATABASE_URL else "?"
    return f"{SQLALCHEMY_DATABASE_URL}{separator}sslmode=require"


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_database_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Détecte aussi les changements de type de colonne, sinon un
            # String(50) passé à String(100) ne génère aucune migration.
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
