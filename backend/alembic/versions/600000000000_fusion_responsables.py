"""cle de rapprochement des responsables et fusion des doublons

Revision ID: 600000000000
Revises: 500000000000
Create Date: 2026-08-19 10:00:00.000000

Les classeurs ecrivent la meme personne de plusieurs facons — « AndryII » et
« Andry II », « Xavier -Hassen » et « Xavier-Hassen ». L'unicite portait sur
`display_name`, qui laissait donc cohabiter ces variantes : une meme personne
apparaissait plusieurs fois dans le plan de charge, et aurait recu plusieurs
relances pour des actions differentes.

Cette migration :
  1. ajoute `name_key`, le nom reduit a ses caracteres alphanumeriques
     minuscules et sans accents ;
  2. fusionne les fiches qui partagent la meme cle, en conservant celle qui
     porte le plus d'actions et en lui rattachant les liens des autres ;
  3. rend `name_key` unique, pour que le probleme ne puisse pas reapparaitre.

La fusion est ecrite en Python plutot qu'en SQL : elle doit reporter des liens
many-to-many en evitant les doublons de cle primaire, et journaliser ce qui a
ete regroupe.
"""
from typing import Sequence, Union
import collections
import re
import unicodedata

from alembic import op
import sqlalchemy as sa

revision: str = '600000000000'
down_revision: Union[str, None] = '500000000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NON_ALPHANUM = re.compile(r"[^a-z0-9]")


def _cle(nom: str) -> str:
    texte = unicodedata.normalize("NFD", str(nom or ""))
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return _NON_ALPHANUM.sub("", texte.lower())


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column("responsables", sa.Column("name_key", sa.String(length=255), nullable=True))

    lignes = conn.execute(
        sa.text(
            """SELECT r.id, r.display_name, r.email, r.is_mapped,
                      (SELECT count(*) FROM action_responsables ar
                        WHERE ar.responsable_id = r.id) AS liens
                 FROM responsables r"""
        )
    ).fetchall()

    groupes = collections.defaultdict(list)
    for ligne in lignes:
        groupes[_cle(ligne.display_name)].append(ligne)

    fusions = 0
    for cle, membres in groupes.items():
        if len(membres) > 1:
            # On conserve la graphie la plus utilisee ; a egalite, la plus
            # longue, qui est en general la forme complete.
            membres = sorted(membres, key=lambda m: (-m.liens, -len(m.display_name), m.display_name))
            garde, doublons = membres[0], membres[1:]

            for double in doublons:
                # Rattacher les actions du doublon, sans recreer un lien qui
                # existe deja (la cle primaire est le couple action/responsable).
                conn.execute(
                    sa.text(
                        """INSERT INTO action_responsables (action_id, responsable_id)
                           SELECT ar.action_id, :garde FROM action_responsables ar
                            WHERE ar.responsable_id = :double
                           ON CONFLICT DO NOTHING"""
                    ),
                    {"garde": garde.id, "double": double.id},
                )
                conn.execute(
                    sa.text("DELETE FROM action_responsables WHERE responsable_id = :double"),
                    {"double": double.id},
                )
                conn.execute(
                    sa.text("UPDATE relance_logs SET responsable_id = :garde WHERE responsable_id = :double"),
                    {"garde": garde.id, "double": double.id},
                )
                # Ne pas perdre un email deja renseigne sur le doublon.
                if double.email and not garde.email:
                    conn.execute(
                        sa.text(
                            "UPDATE responsables SET email = :email, is_mapped = true WHERE id = :garde"
                        ),
                        {"email": double.email, "garde": garde.id},
                    )
                conn.execute(
                    sa.text("DELETE FROM responsables WHERE id = :double"), {"double": double.id}
                )
                fusions += 1
        else:
            garde = membres[0]

        conn.execute(
            sa.text("UPDATE responsables SET name_key = :cle WHERE id = :id"),
            {"cle": cle, "id": garde.id},
        )

    print(f"[600000000000] {fusions} fiche(s) responsable fusionnee(s)")

    op.alter_column("responsables", "name_key", nullable=False)
    op.create_index("ix_responsables_name_key", "responsables", ["name_key"], unique=True)


def downgrade() -> None:
    # Les fiches fusionnees ne sont pas restaurables : la migration inverse se
    # limite a retirer la colonne et son unicite.
    op.drop_index("ix_responsables_name_key", table_name="responsables")
    op.drop_column("responsables", "name_key")
