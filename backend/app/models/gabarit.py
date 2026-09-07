"""
Gabarits de création : valeurs préremplies, politique de champs, actions type.

Créer un projet demandait de ressaisir les mêmes informations à chaque fois,
puis de recréer à la main les quatre ou cinq actions que tout projet
d'infrastructure comporte — cadrage, chiffrage, commande, recette. Rien
n'empêchait non plus d'oublier le responsable de suivi, alors que sans lui
l'action ne déclenche aucune relance.

Un gabarit répond aux deux : il préremplit ce qui est constant, il impose ce
qui ne doit pas être oublié, et il porte la liste des actions à instancier.

Trois notions distinctes, souvent confondues :

  - `valeurs`   : ce qui est proposé, et reste modifiable ;
  - `politique` : ce qui est exigé, masqué ou verrouillé ;
  - `actions`   : ce qui est créé en plus de l'objet lui-même.

Le schéma des projets et des actions reste typé et fixe : un gabarit ne crée
aucun champ, il ne fait que remplir et contraindre ceux qui existent. C'est ce
qui permet aux rapports, aux relances et à l'import Excel de continuer à
fonctionner sans rien savoir des gabarits.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.base import UUIDMixin


class GabaritEntite(str, enum.Enum):
    """Ce qu'un gabarit sait créer."""

    PROJET = "projet"
    ACTION = "action"


class Gabarit(UUIDMixin, Base):
    __tablename__ = "gabarits"

    entite = Column(Enum(GabaritEntite), nullable=False, index=True)
    nom = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    #: Valeurs préremplies, par nom de champ du schéma de création.
    #: Volontairement en JSONB : les champs d'un projet et ceux d'une action
    #: n'ont ni le même nom ni le même type, et une colonne par champ aurait
    #: dû être ajoutée à chaque évolution des deux schémas. Le contenu est
    #: validé à l'écriture contre les champs réellement acceptés, il n'y a
    #: donc pas de clé arbitraire en base.
    valeurs = Column(JSONB, nullable=False, default=dict)

    #: Contraintes de saisie, par nom de champ :
    #: `{"resp_suivi": {"obligatoire": true}, "charges_hj": {"masque": true}}`.
    politique = Column(JSONB, nullable=False, default=dict)

    is_active = Column(Boolean, default=True, nullable=False)

    #: Gabarit proposé d'office à l'ouverture du formulaire. Au plus un par
    #: entité — c'est une aide à la saisie, pas une obligation : le formulaire
    #: reste utilisable sans gabarit.
    is_default = Column(Boolean, default=False, nullable=False)

    position = Column(Integer, default=0, nullable=False)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    actions = relationship(
        "GabaritAction",
        back_populates="gabarit",
        cascade="all, delete-orphan",
        order_by="GabaritAction.position",
    )

    __table_args__ = (
        UniqueConstraint("entite", "nom", name="uq_gabarit_entite_nom"),
        Index("ix_gabarits_liste", "entite", "is_active", "position"),
    )

    def __repr__(self) -> str:
        return f"<Gabarit {self.entite.value}:{self.nom!r}>"


class GabaritAction(UUIDMixin, Base):
    """Une action à créer avec le projet — la partie utile d'un gabarit.

    Préremplir un titre fait gagner quelques secondes ; instancier d'un coup
    les cinq actions de cadrage d'un projet type fait gagner un quart d'heure
    et, surtout, garantit qu'aucune n'est oubliée.

    N'a de sens que sur un gabarit de projet. Un gabarit d'action ne porte pas
    de sous-actions : le modèle n'a pas de hiérarchie d'actions, et en
    introduire une par ce biais l'aurait créée sans que les rapports, les vues
    métier ni les relances le sachent.
    """

    __tablename__ = "gabarit_actions"

    gabarit_id = Column(
        UUID(as_uuid=True), ForeignKey("gabarits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position = Column(Integer, default=0, nullable=False)

    description = Column(Text, nullable=False)
    phase = Column(String(10), nullable=True)
    resp_suivi = Column(String(255), nullable=True)

    #: Noms des responsables de réalisation, séparés par des virgules. Le même
    #: format que la cellule Excel dont ils sortent d'habitude : ils sont
    #: résolus en fiches à l'instanciation, par les règles de rapprochement de
    #: `services/names`.
    responsable_names = Column(Text, nullable=True)

    #: Échéance relative, en jours depuis la création du projet. Une date
    #: absolue dans un gabarit serait périmée dès le deuxième usage.
    delai_jours = Column(Integer, nullable=True)

    charges_hj = Column(Float, nullable=True)

    categorie_id = Column(
        UUID(as_uuid=True), ForeignKey("referentiels.id", ondelete="SET NULL"), nullable=True
    )

    gabarit = relationship("Gabarit", back_populates="actions")

    def __repr__(self) -> str:
        return f"<GabaritAction #{self.position} {self.description[:40]!r}>"
