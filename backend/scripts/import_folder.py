#!/usr/bin/env python3
"""
Importe un dossier de suivi complet (l'arborescence SharePoint synchronisée).

Le worker Celery `sync_project_file` traite un fichier pour un projet déjà
existant en base. Il n'existait aucun moyen de partir du dossier
`07_Projets_DSIO/Projet encours` et d'en tirer les projets *et* leurs actions —
c'est-à-dire d'amorcer la base.

    # Simulation, rien n'est écrit (comportement par défaut)
    podman exec -it dsio-core-api python3 scripts/import_folder.py "/data/Projet encours"

    # Écriture réelle
    podman exec -it dsio-core-api python3 scripts/import_folder.py "/data/Projet encours" --apply

    make import DIR="/data/Projet encours"          # simulation
    make import DIR="/data/Projet encours" APPLY=1  # écriture

Le dossier doit contenir un sous-dossier par projet, nommé `P01 - Libellé`,
avec le classeur de suivi à l'intérieur. Le code projet est repris du nom du
dossier : c'est lui qui fait autorité pour la numérotation des actions, les
numéros saisis dans les classeurs comportant des préfixes erronés.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.services.excel_parser import parse_workbook  # noqa: E402
from app.workers.ingestion import _upsert_action  # noqa: E402

_CODE_RE = re.compile(r"^\s*(P\d+)", re.IGNORECASE)


def _classeur_du_dossier(dossier: Path) -> Path | None:
    """Classeur de suivi d'un dossier projet.

    On écarte les fichiers temporaires d'Excel (`~$…`) et, en cas de fichiers
    multiples, on retient le plus récemment modifié.
    """
    candidats = [
        f for f in dossier.glob("*.xls*")
        if not f.name.startswith("~$") and f.suffix.lower() in (".xlsx", ".xlsm")
    ]
    if not candidats:
        return None
    return max(candidats, key=lambda f: f.stat().st_mtime)


def _libelle(nom_dossier: str) -> str:
    """« P01 - Projet Cantine » -> « Projet Cantine ».

    Le séparateur varie : le dossier de P06 s'appelle « P06 _ Voix IP ».
    """
    reste = re.sub(r"^\s*P\d+\s*[-_]\s*", "", nom_dossier, flags=re.IGNORECASE)
    return reste.strip() or nom_dossier.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Importe les projets et actions d'un dossier de suivi.",
    )
    parser.add_argument("dossier", help="Dossier contenant un sous-dossier par projet.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Écrire en base. Sans cette option, rien n'est modifié.",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Ne traiter qu'un projet, par son code (ex: P10).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Afficher tous les avertissements de lecture.",
    )
    args = parser.parse_args()

    racine = Path(args.dossier)
    if not racine.is_dir():
        print(f"Dossier introuvable : {racine}", file=sys.stderr)
        return 1

    dossiers = sorted(d for d in racine.iterdir() if d.is_dir() and _CODE_RE.match(d.name))
    if args.only:
        dossiers = [d for d in dossiers if _CODE_RE.match(d.name).group(1).upper() == args.only.upper()]
    if not dossiers:
        print(f"Aucun dossier projet reconnu dans {racine} (attendu « P01 - Libellé »).")
        return 1

    mode = "ÉCRITURE" if args.apply else "SIMULATION (utiliser --apply pour écrire)"
    print(f"\n  {len(dossiers)} projet(s) — mode {mode}\n")
    print(f"  {'code':6} {'actions':>8} {'créées':>7} {'màj':>5} {'err':>4}  {'phases':14} projet")
    print("  " + "-" * 104)

    db = SessionLocal()
    totaux = {"actions": 0, "created": 0, "updated": 0, "errors": 0}
    alertes: list[tuple[str, str]] = []
    try:
        for dossier in dossiers:
            code = _CODE_RE.match(dossier.name).group(1).upper()
            classeur = _classeur_du_dossier(dossier)
            if classeur is None:
                print(f"  {code:6} {'—':>8} {'':>7} {'':>5} {'':>4}  {'':14} aucun classeur trouvé")
                continue

            try:
                lecture = parse_workbook(classeur, project_code=code)
            except Exception as exc:
                print(f"  {code:6} {'ERREUR':>8} {'':>7} {'':>5} {'':>4}  {'':14} {exc}")
                continue

            alertes += [(code, w) for w in lecture.warnings]
            totaux["actions"] += len(lecture.actions)

            crees = maj = erreurs = 0
            if args.apply:
                projet = db.query(Project).filter(Project.code == code).first()
                if projet is None:
                    projet = Project(
                        code=code,
                        name=_libelle(dossier.name),
                        source_file_path=str(classeur.relative_to(racine.parent)),
                        has_phases=bool(lecture.phases),
                    )
                    db.add(projet)
                    db.flush()
                else:
                    projet.source_file_path = str(classeur.relative_to(racine.parent))
                    # `has_phases` ne bascule que dans le sens de l'ajout : le
                    # retirer invaliderait la numérotation des actions déjà en
                    # base, dont le numéro encode la phase.
                    if lecture.phases and not projet.has_phases:
                        projet.has_phases = True
                db.commit()

                for action in lecture.actions:
                    try:
                        if _upsert_action(db, projet, action):
                            crees += 1
                        else:
                            maj += 1
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        erreurs += 1
                        alertes.append((code, f"action {action.numero} : {exc.__class__.__name__}"))

            totaux["created"] += crees
            totaux["updated"] += maj
            totaux["errors"] += erreurs

            print(
                f"  {code:6} {len(lecture.actions):>8} {crees:>7} {maj:>5} {erreurs:>4}  "
                f"{','.join(lecture.phases)[:14]:14} {_libelle(dossier.name)[:44]}"
            )

    except OperationalError as exc:
        detail = str(exc.orig).strip().splitlines()[0] if exc.orig else str(exc)
        print(f"\n  Base de données injoignable : {detail}", file=sys.stderr)
        print("  Diagnostic : python3 scripts/check_config.py\n", file=sys.stderr)
        return 1
    finally:
        db.close()

    print("  " + "-" * 104)
    print(
        f"  {'TOTAL':6} {totaux['actions']:>8} {totaux['created']:>7} "
        f"{totaux['updated']:>5} {totaux['errors']:>4}"
    )

    if alertes:
        print(f"\n  {len(alertes)} avertissement(s) de lecture :")
        for code, message in (alertes if args.verbose else alertes[:15]):
            print(f"    [{code}] {message}")
        if not args.verbose and len(alertes) > 15:
            print(f"    … {len(alertes) - 15} de plus (--verbose pour tout voir)")

    if not args.apply:
        print("\n  Aucune écriture effectuée. Relancer avec --apply pour importer.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
