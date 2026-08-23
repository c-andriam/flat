# ==============================================================================
# Variables
# ==============================================================================
COMPOSE		= podman-compose
PODMAN		= podman
# Point d'entrée public de la stack (gateway nginx, TLS auto-signé)
FRONTEND_URL	= https://localhost:8443

# Couleurs pour un affichage plus lisible
GREEN		= \033[1;32m
YELLOW		= \033[1;33m
RED			= \033[1;31m
NC			= \033[0m

# ==============================================================================
# Règles principales
# ==============================================================================
.PHONY: all build up down start stop status logs clean fclean re migrate makemigrations db-update db-shell test test-unit token doctor up-local down-local migrate-local import front-install front-dev front-build front-lint front-check ensure-backend-image login

# Règle par défaut
all: up

# Construit ou reconstruit les services.
# Deux images seulement : `dsio-backend` (partagée par les six conteneurs
# Python) et le frontend. Les cinq services backend sans `build:` la
# réutilisent, voir le commentaire sur core-api dans compose.yml.
build:
	@echo "$(YELLOW) Construction des images Podman...$(NC)"
	$(COMPOSE) build

# Garde-fou : les services backend autres que core-api n'ont pas de `build:`.
# Sans cette vérification, un `make up` sur une machine fraîche tenterait de
# tirer `dsio-backend:latest` depuis un registre distant, où elle n'existe pas.
ensure-backend-image:
	@$(PODMAN) image exists dsio-backend:latest 2>/dev/null || { \
		echo "$(YELLOW) Image backend absente — construction préalable...$(NC)"; \
		$(COMPOSE) build core-api; \
	}

# Crée et démarre les conteneurs en arrière-plan
up: ensure-backend-image
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
	$(PODMAN) run --rm -it --env-file .env --network dsio-internal-net postgres:16-alpine sh -c 'PGPASSWORD="$$POSTGRES_PASSWORD" psql -h "$$POSTGRES_HOST" -p "$${POSTGRES_PORT:-5432}" -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

# ==============================================================================
# Base de donnees locale (developpement hors Supabase)
# ==============================================================================

LOCAL_DB = -f compose.yml -f compose.local-db.yml

# Demarre la stack avec un PostgreSQL en conteneur au lieu de Supabase.
# Utile quand le projet Supabase est en pause, supprime, ou pour developper
# sans toucher aux donnees reelles.
up-local:
	@echo "$(GREEN) Demarrage avec une base PostgreSQL locale...$(NC)"
	$(COMPOSE) $(LOCAL_DB) up -d
	@echo "$(YELLOW) Attente de la base, puis migrations...$(NC)"
	@sleep 8
	@$(MAKE) --no-print-directory migrate-local
	@echo "$(GREEN) Pret. Creez un compte : make token EMAIL=vous@trimetagroup.mg$(NC)"

# Applique les migrations sur la base locale.
migrate-local:
	$(PODMAN) exec dsio-core-api alembic upgrade head

# Arrete la stack locale. Le volume de donnees survit : pour repartir de zero,
# ajouter `podman volume rm dsio_postgres_local_data`.
down-local:
	@echo "$(RED) Arret de la stack locale...$(NC)"
	$(COMPOSE) $(LOCAL_DB) down

# ==============================================================================
# Import du dossier de suivi (arborescence SharePoint synchronisee)
# ==============================================================================

# Cree les projets et importe leurs actions depuis un dossier
# « P01 - Libelle / classeur.xlsx ». Simulation par defaut.
#   make import DIR="/data/Projet encours"
#   make import DIR="/data/Projet encours" APPLY=1
#   make import DIR="/data/Projet encours" ONLY=P10
# Le dossier doit etre visible depuis le conteneur : monter le repertoire
# SharePoint synchronise dans compose.yml (volumes) avant de lancer.
APPLY ?=
ONLY ?=
import:
	@if [ -z "$(DIR)" ]; then 		echo "$(RED) DIR est requis.$(NC)"; 		echo "   exemple : make import DIR=\"/data/Projet encours\""; 		exit 1; 	fi
	@$(PODMAN) exec dsio-core-api python3 scripts/import_folder.py "$(DIR)" 		$(if $(APPLY),--apply,) $(if $(ONLY),--only $(ONLY),)

# ==============================================================================
# Diagnostic
# ==============================================================================

# Verifie en une page ce qui empeche la plateforme de fonctionner :
# variables d'environnement, DNS, PostgreSQL, Redis, SSO, amorcage RBAC.
# A lancer en premier devant toute erreur de demarrage ou de connexion.
doctor:
	@$(PODMAN) exec dsio-core-api python3 scripts/check_config.py

# ==============================================================================
# Jeton d'accès (tests manuels via Swagger / curl / Postman)
# ==============================================================================

# Emet un JWT pour un compte donne, sans passer par le SSO Microsoft.
# Indispensable tant que l'application Entra ID n'est pas configuree, puisque
# toutes les routes metier exigent desormais un jeton.
#   make token EMAIL=prenom.nom@trimeta.mg
#   make token EMAIL=lecteur@trimeta.mg ROLE=lecteur
# Roles : admin | responsable_si | lecteur | dsio
# `dsio` est le seul (avec `admin`) a pouvoir ouvrir des creneaux de
# rendez-vous et arbitrer les demandes.
ROLE ?= admin
token:
	@if [ -z "$(EMAIL)" ]; then \
		echo "$(RED) EMAIL est requis.$(NC)"; \
		echo "   exemple : make token EMAIL=prenom.nom@trimeta.mg"; \
		exit 1; \
	fi
	@$(PODMAN) exec dsio-core-api python3 scripts/issue_token.py "$(EMAIL)" --role "$(ROLE)"

# Ouvre la SPA déjà authentifiée, sans passer par le SSO Microsoft.
# Le jeton part dans le fragment d'URL (#token=...), exactement comme le fait
# /auth/callback : la SPA le consomme au premier rendu puis nettoie la barre
# d'adresse. Réservé au poste de développement — un jeton vaut un mot de passe.
#   make login EMAIL=prenom.nom@trimeta.mg
#   make login EMAIL=lecteur@trimeta.mg ROLE=lecteur
#   make login EMAIL=dsio@trimeta.mg ROLE=dsio   (vue « ouvrir des creneaux »)
login:
	@if [ -z "$(EMAIL)" ]; then \
		echo "$(RED) EMAIL est requis.$(NC)"; \
		echo "   exemple : make login EMAIL=prenom.nom@trimeta.mg"; \
		exit 1; \
	fi
	@$(PODMAN) container exists dsio-core-api 2>/dev/null || { \
		echo "$(RED) La stack n'est pas démarrée — lancer d'abord : make up$(NC)"; \
		exit 1; \
	}
	@TOKEN=$$($(PODMAN) exec dsio-core-api python3 scripts/issue_token.py "$(EMAIL)" --role "$(ROLE)" --quiet) \
		&& URL="$(FRONTEND_URL)/#token=$$TOKEN" \
		&& echo "$(GREEN) Ouverture de la SPA authentifiée ($(EMAIL), rôle $(ROLE))...$(NC)" \
		&& (xdg-open "$$URL" >/dev/null 2>&1 &) \
		&& echo "   Si rien ne s'ouvre, coller cette URL dans le navigateur :" \
		&& echo "   $$URL"

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
# Frontend (SPA React + TypeScript)
# ==============================================================================

FRONT_DIR	= frontend

# Installe les dépendances npm en local (hors conteneur)
front-install:
	@echo "$(YELLOW) Installation des dépendances du frontend...$(NC)"
	cd $(FRONT_DIR) && npm ci

# Serveur de développement Vite avec rechargement à chaud.
# /api et /ws sont proxifiés vers la gateway (VITE_DEV_GATEWAY, .env.example).
front-dev:
	@echo "$(GREEN) Vite en écoute sur http://localhost:5173 ...$(NC)"
	cd $(FRONT_DIR) && npm run dev

# Compile la SPA dans frontend/dist (ce que fait aussi l'image Docker)
front-build:
	@echo "$(YELLOW) Compilation de la SPA...$(NC)"
	cd $(FRONT_DIR) && npm run build

front-lint:
	cd $(FRONT_DIR) && npm run lint

# Contrôle complet avant commit : typage strict puis règles ESLint
front-check:
	@echo "$(GREEN) Vérification du typage et du lint...$(NC)"
	cd $(FRONT_DIR) && npm run typecheck && npm run lint

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
