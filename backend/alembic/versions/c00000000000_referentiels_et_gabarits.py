"""referentiels administrables et gabarits de creation

Revision ID: c00000000000
Revises: b00000000000
Create Date: 2026-09-07 15:00:00.000000

Deux manques de souplesse, symetriques.

1. Aucune liste de valeurs n'etait administrable. Les natures de projet et
   d'action n'existaient pas, et les salles de reunion non plus. Ajouter une
   valeur aurait demande une migration, la renommer un deploiement.
   `referentiels` est une table unique pour toutes ces listes : leur forme est
   identique (code, libelle, ordre, couleur, actif), une table par liste
   aurait multiplie par cinq le meme modele, les memes routes et le meme ecran.

2. Creer un projet imposait de ressaisir les memes valeurs, puis de recreer a
   la main les quatre ou cinq actions que tout projet du meme type comporte.
   `gabarits` porte les valeurs prereplies, la politique de saisie (ce qui est
   obligatoire, masque ou verrouille) et, dans `gabarit_actions`, la liste des
   actions a instancier.

Le schema des projets et des actions reste typé : un gabarit ne cree aucun
champ, il remplit et contraint ceux qui existent. Les rapports, les relances
et l'import Excel continuent donc de fonctionner sans rien savoir des gabarits.

Deux colonnes de rattachement seulement — `projects.type_id` et
`actions.categorie_id` — toutes deux en `SET NULL` : desactiver ou supprimer
une valeur de liste ne doit jamais emporter les objets qui s'y referaient.

Aucune donnee n'est creee ici. Les listes naissent vides, et le premier ecran
d'administration sert precisement a les remplir : livrer des valeurs
d'exemple aurait impose un vocabulaire que personne n'a demande, et qu'il
aurait fallu supprimer une par une.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c00000000000'
down_revision: Union[str, None] = 'b00000000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----------------------------------------------------------- referentiels
    op.create_table(
        'referentiels',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        # Le type de liste est une chaine, pas un type enumere PostgreSQL :
        # cette liste s'allonge a chaque fonctionnalite, et `ALTER TYPE ... ADD
        # VALUE` ne s'execute pas dans la transaction d'une migration (voir la
        # revision 400000000000). Le caractere ferme est tenu par les schemas
        # Pydantic, ou l'erreur est lisible par l'appelant.
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('color', sa.String(length=7), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('attributs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        # Auto-reference pour les listes a deux niveaux. `SET NULL` : supprimer
        # un parent degrade la hierarchie, il ne supprime pas ses enfants.
        sa.ForeignKeyConstraint(['parent_id'], ['referentiels.id'], ondelete='SET NULL'),
        # Le code identifie la valeur au sein de sa liste, pas au-dela : deux
        # listes peuvent legitimement contenir un « autre ».
        sa.UniqueConstraint('type', 'code', name='uq_referentiel_type_code'),
    )
    op.create_index('ix_referentiels_type', 'referentiels', ['type'])
    # Requete dominante : « les valeurs actives de cette liste, dans l'ordre »,
    # emise a chaque ouverture d'un formulaire.
    op.create_index(
        'ix_referentiels_liste', 'referentiels', ['type', 'is_active', 'position']
    )

    # --------------------------------------------------------------- gabarits
    entite = postgresql.ENUM('PROJET', 'ACTION', name='gabaritentite', create_type=False)
    entite.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'gabarits',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('entite', entite, nullable=False),
        sa.Column('nom', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        # Valeurs prereplies et politique de saisie, par nom de champ. En JSONB
        # parce que les champs d'un projet et ceux d'une action n'ont ni les
        # memes noms ni les memes types : une colonne par champ aurait du etre
        # ajoutee a chaque evolution des deux schemas. Le contenu est valide a
        # l'ecriture contre les champs reellement acceptes.
        sa.Column('valeurs', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column('politique', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('entite', 'nom', name='uq_gabarit_entite_nom'),
    )
    op.create_index('ix_gabarits_entite', 'gabarits', ['entite'])
    op.create_index('ix_gabarits_liste', 'gabarits', ['entite', 'is_active', 'position'])
    # Au plus un gabarit propose d'office par entite. Index unique partiel
    # plutot qu'un controle applicatif : deux enregistrements concurrents
    # peuvent tous deux se croire seuls a cocher la case.
    op.create_index(
        'uq_gabarit_defaut_par_entite',
        'gabarits',
        ['entite'],
        unique=True,
        postgresql_where=sa.text('is_default'),
    )

    op.create_table(
        'gabarit_actions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('gabarit_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('phase', sa.String(length=10), nullable=True),
        sa.Column('resp_suivi', sa.String(length=255), nullable=True),
        sa.Column('responsable_names', sa.Text(), nullable=True),
        # Echeance relative, en jours depuis la creation du projet : une date
        # absolue dans un gabarit serait perimee des le deuxieme usage.
        sa.Column('delai_jours', sa.Integer(), nullable=True),
        sa.Column('charges_hj', sa.Float(), nullable=True),
        sa.Column('categorie_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['gabarit_id'], ['gabarits.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['categorie_id'], ['referentiels.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_gabarit_actions_gabarit_id', 'gabarit_actions', ['gabarit_id'])

    # ------------------------------------------------- rattachement des objets
    op.add_column(
        'projects', sa.Column('type_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        'fk_projects_type_id', 'projects', 'referentiels', ['type_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_projects_type_id', 'projects', ['type_id'])

    op.add_column(
        'actions', sa.Column('categorie_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        'fk_actions_categorie_id', 'actions', 'referentiels', ['categorie_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_actions_categorie_id', 'actions', ['categorie_id'])


def downgrade() -> None:
    op.drop_index('ix_actions_categorie_id', table_name='actions')
    op.drop_constraint('fk_actions_categorie_id', 'actions', type_='foreignkey')
    op.drop_column('actions', 'categorie_id')

    op.drop_index('ix_projects_type_id', table_name='projects')
    op.drop_constraint('fk_projects_type_id', 'projects', type_='foreignkey')
    op.drop_column('projects', 'type_id')

    op.drop_index('ix_gabarit_actions_gabarit_id', table_name='gabarit_actions')
    op.drop_table('gabarit_actions')

    op.drop_index('uq_gabarit_defaut_par_entite', table_name='gabarits')
    op.drop_index('ix_gabarits_liste', table_name='gabarits')
    op.drop_index('ix_gabarits_entite', table_name='gabarits')
    op.drop_table('gabarits')
    postgresql.ENUM(name='gabaritentite').drop(op.get_bind(), checkfirst=True)

    op.drop_index('ix_referentiels_liste', table_name='referentiels')
    op.drop_index('ix_referentiels_type', table_name='referentiels')
    op.drop_table('referentiels')
