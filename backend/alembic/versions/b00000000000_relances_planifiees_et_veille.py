"""relances planifiees par personne, responsable de suivi joignable, mise en veille

Revision ID: b00000000000
Revises: a00000000000
Create Date: 2026-09-07 09:00:00.000000

Trois manques rendaient les relances inexploitables en l'etat.

1. Le responsable de *suivi* (colonne E) n'etait qu'une chaine de caracteres.
   Aucune adresse email ne lui etait rattachee, donc la personne qui pilote
   reellement une action ne pouvait jamais etre relancee — seuls les
   realisateurs (colonne D) l'etaient. `action_resp_suivi` resout ce libelle
   en fiches responsables, avec les memes regles de decoupage et de
   rapprochement que la colonne D. La colonne texte est conservee : c'est la
   cellule brute du classeur, et elle fait foi a chaque relecture du fichier.

2. La cadence etait la meme pour tout le monde, figee dans le code du beat.
   `relance_preferences` la rend propre a chaque personne : jours d'envoi
   (deux par semaine par defaut), heure, perimetre et contenu du
   recapitulatif.

3. Un projet suspendu — budget gele, prestataire en attente — continuait
   d'accumuler des actions en retard que personne ne pouvait solder. Elles
   gonflaient chaque relance jusqu'a noyer les vraies urgences. `is_standby`
   sort ces lignes des rappels sans les faire disparaitre des tableaux de
   bord, ce que `is_active=False` aurait fait.

La logique de normalisation des noms est recopiee ici plutot qu'importee :
une migration doit produire le meme resultat dans dix ans, meme si le code
applicatif a evolue. C'est la meme convention que la revision 700000000000.
"""
from typing import Sequence, Union
import os
import re
import unicodedata

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b00000000000'
down_revision: Union[str, None] = 'a00000000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NON_ALPHANUM = re.compile(r"[^a-z0-9]")
_SEPARATEURS = re.compile(r"\s*(?:/|,|&|\+|-|\bet\b)\s*", re.IGNORECASE)


def _cle(nom: str) -> str:
    texte = unicodedata.normalize("NFD", str(nom or ""))
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return _NON_ALPHANUM.sub("", texte.lower())


def _insecables() -> frozenset:
    brut = os.getenv("RESPONSABLES_INSECABLES", "")
    return frozenset(_cle(n) for n in brut.split(",") if _cle(n))


def _email_designe(email: str, libelle: str) -> bool:
    """L'adresse designe-t-elle la personne nommee par ce libelle ?

    « Jean-Pierre » + jeanpierre.eloi@... -> vrai, donc pas de decoupage sur
    le tiret. « karine - hassen » + karine.raz@... -> faux, deux personnes.
    """
    if not email or "@" not in email:
        return False
    local = _cle(email.split("@", 1)[0])
    cle = _cle(libelle)
    return bool(local and cle and local.startswith(cle))


def _personnes(libelle: str, emails_connus) -> list:
    """Personnes designees par un libelle, dedoublonnees."""
    libelle = re.sub(r"\s+", " ", str(libelle or "")).strip()
    if not libelle:
        return []
    if _cle(libelle) in _insecables():
        return [libelle]

    vues = set()
    morceaux = []
    for morceau in _SEPARATEURS.split(libelle):
        morceau = re.sub(r"\s+", " ", morceau).strip(" .;-")
        cle = _cle(morceau)
        if not cle or cle in vues:
            continue
        vues.add(cle)
        morceaux.append(morceau)

    if len(morceaux) <= 1:
        return morceaux or [libelle]
    # Un tiret peut aussi etre un prenom compose : seule l'existence d'une
    # adresse au nom complet permet de trancher.
    if any(_email_designe(email, libelle) for email in emails_connus):
        return [libelle]
    return morceaux


def upgrade() -> None:
    conn = op.get_bind()

    # ---------------------------------------------------------------- veille
    op.add_column(
        'projects',
        sa.Column('is_standby', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('projects', sa.Column('standby_reason', sa.Text(), nullable=True))
    op.create_index('ix_projects_is_standby', 'projects', ['is_standby'])

    op.add_column(
        'actions',
        sa.Column('is_standby', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('actions', sa.Column('standby_reason', sa.Text(), nullable=True))
    op.create_index('ix_actions_is_standby', 'actions', ['is_standby'])

    # ------------------------------------------------ historique des relances
    op.add_column(
        'relance_logs',
        sa.Column('kind', sa.String(length=20), nullable=False, server_default='digest'),
    )
    op.add_column(
        'relance_logs',
        sa.Column('action_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_relance_logs_kind', 'relance_logs', ['kind'])
    # Les envois anterieurs etaient tous des rappels « actions en retard » :
    # les etiqueter `digest` laisserait croire qu'un recapitulatif planifie a
    # deja circule, et le garde-fou d'idempotence sauterait le premier envoi.
    op.execute("UPDATE relance_logs SET kind = 'overdue'")
    # `action_ids` est une liste separee par des virgules ; une chaine vide
    # compte zero action, pas une.
    op.execute(
        "UPDATE relance_logs SET action_count = CASE "
        "WHEN coalesce(action_ids, '') = '' THEN 0 "
        "ELSE array_length(string_to_array(action_ids, ','), 1) END"
    )

    # ------------------------------------------------ preferences de relance
    perimetre = postgresql.ENUM(
        'SUIVI', 'REALISATION', 'LES_DEUX', name='relanceperimetre', create_type=False
    )
    perimetre.create(conn, checkfirst=True)

    op.create_table(
        'relance_preferences',
        # Pas de `server_default` sur l'identifiant : les lignes naissent
        # toujours par l'ORM, dont `UUIDMixin` porte le défaut. C'est la
        # convention des tables créées par les révisions précédentes.
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('responsable_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        # Le type énuméré déjà créé est réutilisé tel quel. `sa.Enum(...,
        # create_type=False)` ne fait *pas* la même chose : SQLAlchemy y voit
        # un argument positionnel de plus et produit un VARCHAR(1), qui
        # tronquerait silencieusement chaque valeur à sa première lettre.
        sa.Column('perimeter', perimetre, nullable=False, server_default='SUIVI'),
        sa.Column('days_of_week', sa.String(length=20), nullable=False, server_default='0,3'),
        sa.Column('send_hour', sa.Integer(), nullable=False, server_default='8'),
        sa.Column('include_overdue', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('include_today', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('include_due_soon', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('include_pending', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('horizon_days', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['responsable_id'], ['responsables.id'], ondelete='CASCADE'),
        # Une seule ligne par personne : deux reglages concurrents rendraient
        # l'envoi dependant de l'ordre de lecture.
        sa.UniqueConstraint('responsable_id', name='uq_relance_preferences_responsable'),
    )
    op.create_index(
        'ix_relance_preferences_responsable_id', 'relance_preferences', ['responsable_id']
    )
    # Le beat interroge « qui doit recevoir un rappel a cette heure-ci ? » :
    # sans cet index il parcourt toute la table a chaque heure ronde.
    op.create_index(
        'ix_relance_preferences_envoi', 'relance_preferences', ['enabled', 'send_hour']
    )

    # -------------------------------------- responsables de suivi joignables
    op.create_table(
        'action_resp_suivi',
        sa.Column('action_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('responsable_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['responsable_id'], ['responsables.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('action_id', 'responsable_id'),
    )
    op.create_index(
        'ix_action_resp_suivi_responsable_id', 'action_resp_suivi', ['responsable_id']
    )

    _backfill_resp_suivi(conn)


def _backfill_resp_suivi(conn) -> None:
    """Resout les libelles « Resp. suivi » deja en base en fiches responsables.

    Sans cette reprise, la table de liaison naitrait vide : aucun responsable
    de suivi ne serait relance tant qu'un classeur n'aurait pas ete
    reimporte — c'est-a-dire jamais pour un projet cloture ou archive.
    """
    emails_connus = [
        ligne.email
        for ligne in conn.execute(
            sa.text("SELECT email FROM responsables WHERE email IS NOT NULL")
        ).fetchall()
    ]

    # Index des fiches existantes, tenu a jour au fil des creations : une
    # fiche inseree ici doit etre reutilisee par l'action suivante, sinon la
    # contrainte d'unicite sur `name_key` fait echouer la migration.
    fiches = {
        ligne.name_key: ligne.id
        for ligne in conn.execute(
            sa.text("SELECT id, name_key FROM responsables")
        ).fetchall()
    }

    lignes = conn.execute(
        sa.text(
            "SELECT id, resp_suivi FROM actions "
            "WHERE resp_suivi IS NOT NULL AND btrim(resp_suivi) <> ''"
        )
    ).fetchall()

    liens = crees = 0
    for action in lignes:
        for nom in _personnes(action.resp_suivi, emails_connus):
            cle = _cle(nom)
            if not cle:
                continue
            cible = fiches.get(cle)
            if cible is None:
                cible = conn.execute(
                    sa.text(
                        "INSERT INTO responsables "
                        "(id, display_name, name_key, email, is_mapped, "
                        " created_at, updated_at) "
                        "VALUES (gen_random_uuid(), :nom, :cle, NULL, false, now(), now()) "
                        "RETURNING id"
                    ),
                    {"nom": nom, "cle": cle},
                ).scalar_one()
                fiches[cle] = cible
                crees += 1
            conn.execute(
                sa.text(
                    "INSERT INTO action_resp_suivi (action_id, responsable_id) "
                    "VALUES (:action, :resp) ON CONFLICT DO NOTHING"
                ),
                {"action": action.id, "resp": cible},
            )
            liens += 1

    print(
        f"[b00000000000] {len(lignes)} action(s) avec un resp. suivi -> "
        f"{liens} lien(s), {crees} fiche(s) creee(s)"
    )


def downgrade() -> None:
    op.drop_index('ix_action_resp_suivi_responsable_id', table_name='action_resp_suivi')
    op.drop_table('action_resp_suivi')

    op.drop_index('ix_relance_preferences_envoi', table_name='relance_preferences')
    op.drop_index('ix_relance_preferences_responsable_id', table_name='relance_preferences')
    op.drop_table('relance_preferences')
    postgresql.ENUM(name='relanceperimetre').drop(op.get_bind(), checkfirst=True)

    op.drop_index('ix_relance_logs_kind', table_name='relance_logs')
    op.drop_column('relance_logs', 'action_count')
    op.drop_column('relance_logs', 'kind')

    op.drop_index('ix_actions_is_standby', table_name='actions')
    op.drop_column('actions', 'standby_reason')
    op.drop_column('actions', 'is_standby')

    op.drop_index('ix_projects_is_standby', table_name='projects')
    op.drop_column('projects', 'standby_reason')
    op.drop_column('projects', 'is_standby')
