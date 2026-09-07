"""
Référentiels : les listes de valeurs administrables par l'utilisateur.

Types de projet, catégories d'action, salles de réunion — autant de listes qui
n'existaient qu'en dur dans le code ou pas du tout. Ajouter une salle imposait
une migration ; renommer une catégorie, un déploiement.

Une table générique plutôt qu'une table par liste : les cinq listes ont
exactement la même forme (code, libellé, ordre, couleur, actif) et les mêmes
opérations. Cinq tables auraient signifié cinq modèles, cinq jeux de routes et
cinq écrans d'administration rigoureusement identiques — et la sixième liste
aurait coûté le même prix que la première.

Le *type* de liste, lui, reste fermé (`ReferentielType`). C'est la distinction
qui fait fonctionner ce genre de paramétrage : ajouter une *valeur* est un acte
d'administration, ajouter un *type* est un développement, puisqu'il faut du
code pour le consommer. Laisser inventer des types produirait des listes que
rien ne lit.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
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


class ReferentielType(str, enum.Enum):
    """Listes administrables reconnues par l'application.

    Stockées en `String` et non en type énuméré PostgreSQL : cette liste est
    faite pour s'allonger au fil des fonctionnalités, et `ALTER TYPE ... ADD
    VALUE` ne s'exécute pas dans la transaction d'une migration (voir la
    révision 400000000000, qui a dû recourir à un bloc autocommit pour ajouter
    un seul statut). Le caractère fermé est garanti à l'écriture par les
    schémas Pydantic, là où l'erreur est lisible par l'appelant.
    """

    #: Nature d'un projet — « Infrastructure », « Métier », « Support ».
    TYPE_PROJET = "type_projet"
    #: Nature d'une action — « Étude », « Déploiement », « Formation ».
    CATEGORIE_ACTION = "categorie_action"
    #: Salles de réunion physiques. `attributs` y porte la capacité.
    SALLE = "salle"
    #: Nature d'une réunion — « Comité de pilotage », « Point hebdomadaire ».
    TYPE_REUNION = "type_reunion"


#: Libellés d'administration, affichés en tête de chaque liste.
REFERENTIEL_LABELS: dict[ReferentielType, str] = {
    ReferentielType.TYPE_PROJET: "Types de projet",
    ReferentielType.CATEGORIE_ACTION: "Catégories d'action",
    ReferentielType.SALLE: "Salles de réunion",
    ReferentielType.TYPE_REUNION: "Types de réunion",
}


class Referentiel(UUIDMixin, Base):
    """Une valeur d'une liste administrable."""

    __tablename__ = "referentiels"

    type = Column(String(50), nullable=False, index=True)

    #: Identifiant stable, insensible au renommage. C'est lui qu'on inscrit
    #: dans un gabarit ou une règle : renommer « Infra » en
    #: « Infrastructure » ne doit pas casser ce qui s'y référait.
    code = Column(String(50), nullable=False)
    label = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    #: Couleur du badge, en `#RRGGBB`. Facultative : sans elle, l'interface
    #: retombe sur la teinte neutre.
    color = Column(String(7), nullable=True)

    #: Ordre d'affichage. L'ordre alphabétique ne convient pas à une liste
    #: métier : « Critique » doit précéder « Faible ».
    position = Column(Integer, default=0, nullable=False)

    #: Désactiver plutôt que supprimer : une valeur retirée reste référencée
    #: par les projets et actions passés, qu'on ne veut pas orphelins. Les
    #: valeurs inactives disparaissent des formulaires mais restent lisibles
    #: sur l'historique.
    is_active = Column(Boolean, default=True, nullable=False)

    #: Hiérarchie facultative, pour les listes à deux niveaux (catégorie et
    #: sous-catégorie). Auto-référence : le parent est une valeur du même type.
    parent_id = Column(
        UUID(as_uuid=True), ForeignKey("referentiels.id", ondelete="SET NULL"), nullable=True
    )

    #: Propriétés intrinsèques de la valeur : capacité et étage d'une salle,
    #: durée par défaut d'un type de réunion.
    #:
    #: Ce n'est pas un moteur de champs personnalisés — il n'y en a pas dans
    #: l'application, le schéma reste typé. C'est le contenu propre d'une
    #: valeur de liste, qui n'a de sens que pour son type et qu'aucune requête
    #: ne filtre. Lui dédier des colonnes aurait rempli la table de champs
    #: nuls pour tous les autres types.
    attributs = Column(JSONB, nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    parent = relationship("Referentiel", remote_side="Referentiel.id", lazy="noload")

    __table_args__ = (
        # Le code identifie la valeur au sein de sa liste, pas au-delà : deux
        # listes peuvent légitimement contenir un « autre ».
        UniqueConstraint("type", "code", name="uq_referentiel_type_code"),
        # Requête dominante : « les valeurs actives de cette liste, dans
        # l'ordre » — émise à chaque ouverture d'un formulaire.
        Index("ix_referentiels_liste", "type", "is_active", "position"),
    )

    def __repr__(self) -> str:
        return f"<Referentiel {self.type}:{self.code} {self.label!r}>"
