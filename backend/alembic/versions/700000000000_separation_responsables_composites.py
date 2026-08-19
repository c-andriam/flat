"""separation des fiches responsables composites

Revision ID: 700000000000
Revises: 600000000000
Create Date: 2026-08-19 12:00:00.000000

Les classeurs mettent parfois plusieurs personnes dans la meme cellule
« Resp. realisation », separees par un tiret sans espacement regulier :
« Meylis-Hassen », « Xavier -Hassen », « Manoa -Karine », « Xavier-Hassen-MDC ».
Le parseur ne coupait que sur « espace tiret espace », ces cellules ont donc
produit une fiche responsable par combinaison — sept fiches portant 21 actions,
alors que chaque partie existait deja comme responsable a part entiere.

Consequences : une charge de travail invisible dans le plan de charge (les
actions de « Xavier -Hassen » ne comptaient ni pour Xavier ni pour Hassen), et
aucune relance possible puisque la fiche composite n'aura jamais d'email.

Cette migration rattache chaque action aux personnes reelles, puis supprime la
fiche composite.

Les fiches sans aucune action sont laissees telles quelles : ce sont des
comptes techniques (« Auto-… », « stagiaire.system-it ») que le decoupage
abimerait sans benefice.

La logique de normalisation est recopiee ici plutot qu'importee : une
migration doit produire le meme resultat dans dix ans, meme si le code
applicatif a evolue.
"""
from typing import Sequence, Union
import re
import unicodedata

from alembic import op
import sqlalchemy as sa

revision: str = '700000000000'
down_revision: Union[str, None] = '600000000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NON_ALPHANUM = re.compile(r"[^a-z0-9]")
_SEPARATEURS = re.compile(r"\s*(?:/|,|&|\+|-|\bet\b)\s*", re.IGNORECASE)


def _cle(nom: str) -> str:
    texte = unicodedata.normalize("NFD", str(nom or ""))
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return _NON_ALPHANUM.sub("", texte.lower())


def _parties(nom: str) -> list[str]:
    """Personnes contenues dans un libelle, dedoublonnees."""
    vues: set[str] = set()
    resultat: list[str] = []
    for morceau in _SEPARATEURS.split(nom):
        morceau = re.sub(r"\s+", " ", morceau).strip(" .;-")
        cle = _cle(morceau)
        if not cle or cle in vues:
            continue
        vues.add(cle)
        resultat.append(morceau)
    return resultat


def upgrade() -> None:
    conn = op.get_bind()

    composites = conn.execute(
        sa.text(
            """SELECT r.id, r.display_name, r.email,
                      (SELECT count(*) FROM action_responsables ar
                        WHERE ar.responsable_id = r.id) AS liens
                 FROM responsables r
                ORDER BY r.display_name"""
        )
    ).fetchall()

    separees = 0
    for fiche in composites:
        # Une fiche sans action ne gagne rien a etre decoupee, et il s'agit en
        # pratique de comptes techniques.
        if fiche.liens == 0:
            continue
        parties = _parties(fiche.display_name)
        if len(parties) < 2:
            continue

        cibles = []
        for nom in parties:
            cle = _cle(nom)
            existant = conn.execute(
                sa.text("SELECT id FROM responsables WHERE name_key = :cle"), {"cle": cle}
            ).fetchone()
            if existant is None:
                nouveau = conn.execute(
                    sa.text(
                        """INSERT INTO responsables
                                  (id, display_name, name_key, email, is_mapped,
                                   created_at, updated_at)
                           VALUES (gen_random_uuid(), :nom, :cle, NULL, false, now(), now())
                        RETURNING id"""
                    ),
                    {"nom": nom, "cle": cle},
                ).fetchone()
                cibles.append(nouveau.id)
            else:
                cibles.append(existant.id)

        for cible in cibles:
            conn.execute(
                sa.text(
                    """INSERT INTO action_responsables (action_id, responsable_id)
                       SELECT ar.action_id, :cible FROM action_responsables ar
                        WHERE ar.responsable_id = :composite
                       ON CONFLICT DO NOTHING"""
                ),
                {"cible": cible, "composite": fiche.id},
            )

        # Une relance deja tracee est rattachee a la premiere personne du
        # libelle : la supprimer ferait perdre l'historique d'envoi.
        conn.execute(
            sa.text("UPDATE relance_logs SET responsable_id = :cible WHERE responsable_id = :composite"),
            {"cible": cibles[0], "composite": fiche.id},
        )
        conn.execute(
            sa.text("DELETE FROM action_responsables WHERE responsable_id = :composite"),
            {"composite": fiche.id},
        )
        conn.execute(
            sa.text("DELETE FROM responsables WHERE id = :composite"), {"composite": fiche.id}
        )
        separees += 1
        print(
            f"[700000000000] {fiche.display_name!r} ({fiche.liens} actions) "
            f"-> {parties}"
        )

    print(f"[700000000000] {separees} fiche(s) composite(s) separee(s)")


def downgrade() -> None:
    # Les fiches composites ne sont pas reconstituables : on ne saurait pas
    # quelles actions leur appartenaient en propre.
    pass
