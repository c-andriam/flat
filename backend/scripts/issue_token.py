#!/usr/bin/env python3
"""
Émet un JWT applicatif pour un compte donné, sans passer par le SSO Microsoft.

À quoi ça sert
--------------
Toutes les routes métier exigent un jeton depuis l'audit de sécurité. Or le
seul émetteur normal est `/api/v1/auth/login`, qui suppose une application
Entra ID configurée. Tant que `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` /
`AZURE_CLIENT_SECRET` ne sont pas renseignés — et pour tout test hors ligne —
ce script est la façon prévue d'obtenir un jeton.

Le compte créé ici est un compte applicatif ordinaire : à la première
connexion SSO avec la même adresse, `/auth/callback` le rattache au compte
Entra ID au lieu d'en créer un second.

À exécuter dans le conteneur core-api (il y trouve SECRET_KEY et la base) :

    podman exec -it dsio-core-api python3 scripts/issue_token.py vous@trimeta.mg

ou, plus court :

    make token EMAIL=vous@trimeta.mg

Le jeton affiché donne un accès complet à l'API pour sa durée de validité :
le traiter comme un mot de passe, ne pas le coller dans un ticket ni un chat.
"""

import argparse
import sys
import uuid
from pathlib import Path

# Permet `python3 scripts/issue_token.py` depuis /app comme depuis backend/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services.security import create_access_token  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Émet un jeton Bearer pour tester l'API (Swagger, curl, Postman).",
    )
    parser.add_argument("email", help="Adresse email du compte (créé s'il n'existe pas).")
    parser.add_argument(
        "--role",
        default=UserRole.ADMIN.value,
        choices=[r.value for r in UserRole],
        help="Rôle attribué au compte (défaut : admin).",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Nom affiché (défaut : partie locale de l'email).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="N'afficher que le jeton, sans texte autour (pour un pipe).",
    )
    args = parser.parse_args()

    email = args.email.strip().lower()
    if "@" not in email:
        parser.error(f"Adresse email invalide : {email!r}")

    role = UserRole(args.role)
    display_name = args.name or email.split("@")[0]

    db = SessionLocal()
    try:
        try:
            user = db.query(User).filter(User.email == email).first()
        except OperationalError as exc:
            # Une erreur de configuration ne mérite pas 100 lignes de trace
            # SQLAlchemy : on renvoie la ligne utile et où aller plus loin.
            detail = str(exc.orig).strip().splitlines()[0] if exc.orig else str(exc)
            print(f"\n  Base de données injoignable : {detail}\n", file=sys.stderr)
            print(
                "  Diagnostic complet :  python3 scripts/check_config.py"
                "  (ou : make doctor)\n",
                file=sys.stderr,
            )
            return 1
        if user is None:
            # Pas d'`oid` Entra ID tant que la personne ne s'est pas connectée
            # en SSO : on pose un identifiant local, que le callback remplacera
            # par le vrai `oid` à la première connexion Microsoft.
            user = User(
                azure_object_id=f"local-{uuid.uuid4().hex[:24]}",
                email=email,
                display_name=display_name,
                role=role,
            )
            db.add(user)
            created = True
        else:
            user.role = role
            user.is_active = True
            created = False

        db.commit()
        db.refresh(user)
        token = create_access_token(user)
    finally:
        db.close()

    if args.quiet:
        print(token)
        return 0

    print()
    print(f"  Compte    : {user.email}  ({'créé' if created else 'mis à jour'})")
    print(f"  Rôle      : {user.role.value}")
    print(f"  Validité  : {settings.access_token_expire_minutes} minutes")
    print()
    print("  Jeton (à coller dans le bouton « Authorize » de Swagger) :")
    print()
    print(f"    {token}")
    print()
    print("  Swagger   : https://localhost:8443/api/v1/docs")
    print("  curl      : curl -k -H \"Authorization: Bearer <jeton>\" \\")
    print("                   https://localhost:8443/api/v1/projects")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
