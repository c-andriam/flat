# ==============================================================================
# Variables
# ==============================================================================
COMPOSE		= podman-compose
PODMAN		= podman

# Couleurs pour un affichage plus lisible
GREEN		= \033[1;32m
YELLOW		= \033[1;33m
RED			= \033[1;31m
NC			= \033[0m

# ==============================================================================
# Règles principales
# ==============================================================================
.PHONY: all build up down start stop status logs clean fclean re migrate makemigrations db-update db-shell test test-unit

# Règle par défaut
all: up

# Construit ou reconstruit les services
build:
	@echo "$(YELLOW) Construction des images Podman...$(NC)"
	$(COMPOSE) build

# Crée et démarre les conteneurs en arrière-plan
up:
	@echo "$(GREEN) Démarrage de l'infrastructure en arrière-plan...$(NC)"
	$(COMPOSE) up -d

# Arrête et supprime les conteneurs, réseaux et volumes
down:
	@echo "$(RED) Arrêt et suppression des conteneurs...$(NC)"
	$(COMPOSE) down

# Démarre les conteneurs existants (sans les recréer)
start:
	@echo "$(GREEN) Démarrage des services...$(NC)"
	$(COMPOSE) start

# Arrête les conteneurs sans les détruire
stop:
	@echo "$(YELLOW) Mise en pause des services...$(NC)"
	$(COMPOSE) stop

# Affiche l'état des conteneurs
status:
	@echo "$(GREEN) État des conteneurs :$(NC)"
	$(PODMAN) ps

# Suit les logs en temps réel
logs:
	@echo "$(YELLOW) Affichage des logs (Ctrl+C pour quitter)...$(NC)"
	$(COMPOSE) logs -f

# ==============================================================================
# Migrations Alembic
# ==============================================================================

# Génère une nouvelle migration à partir des modèles SQLAlchemy (m="message")
makemigrations:
	@echo "$(YELLOW) Génération de la migration Alembic...$(NC)"
	$(PODMAN) exec dsio-core-api alembic revision --autogenerate -m "$(m)"

# Applique les migrations en attente
migrate:
	@echo "$(GREEN) Application des migrations Alembic...$(NC)"
	$(PODMAN) exec dsio-core-api alembic upgrade head

# Alias pour plus de clarté
db-update: migrate

# Ouvre un shell psql sur la base Supabase.
# L'ancienne cible visait un conteneur `db` qui n'existe pas (la base est
# hébergée chez Supabase) et codait en dur l'identifiant du projet ; on passe
# maintenant par un conteneur jetable qui lit les identifiants dans .env.
db-shell:
	@echo "$(YELLOW) Connexion à la base de données PostgreSQL (Supabase)...$(NC)"
	$(PODMAN) run --rm -it --env-file .env --network dsio-internal-net postgres:16-alpine 		sh -c 'PGPASSWORD="$$POSTGRES_PASSWORD" psql -h "$$POSTGRES_HOST" -p "$${POSTGRES_PORT:-5432}" -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

# ==============================================================================
# Tests automatisés
# ==============================================================================

# Lance la suite complète (unitaire + intégration) contre la stack démarrée.
# Le gateway redirige HTTP vers HTTPS : l'ancienne URL http://gateway:80 faisait
# échouer tous les tests sur la validation du certificat auto-signé.
test:
	@echo "$(YELLOW) Installation des dépendances de test...$(NC)"
	$(PODMAN) exec dsio-core-api pip install --quiet -r requirements-dev.txt
	@echo "$(GREEN) Lancement des tests...$(NC)"
	$(PODMAN) exec -e DSIO_TEST_BASE_URL=https://gateway dsio-core-api python3 -m pytest

# Tests unitaires seuls : ni base de données ni stack démarrée, utilisables
# en pré-commit ou en CI sur un simple `pip install -r requirements.txt`.
test-unit:
	@echo "$(GREEN) Tests unitaires (sans infrastructure)...$(NC)"
	$(PODMAN) exec dsio-core-api python3 -m pytest tests/test_unit_*.py

# ==============================================================================
# Règles de nettoyage
# ==============================================================================

# Nettoie les conteneurs arrêtés et les réseaux non utilisés
clean: down
	@echo "$(RED) Nettoyage des ressources orphelines...$(NC)"
	$(PODMAN) container prune -f
	$(PODMAN) network prune -f

# Nettoyage profond : supprime TOUT (images, volumes, conteneurs)
fclean: clean
	@echo "$(RED) Suppression totale (images, volumes, cache)...$(NC)"
	$(PODMAN) system prune -a --volumes -f

# Recompile et relance l'infrastructure à neuf
re: fclean build up
