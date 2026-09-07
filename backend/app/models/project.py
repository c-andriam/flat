import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.base import UUIDMixin

# ---------------------------------------------------------------------------
# Table d'association Action <-> Responsable (many-to-many)
# ---------------------------------------------------------------------------
action_responsables = Table(
    "action_responsables",
    Base.metadata,
    Column("action_id", UUID(as_uuid=True), ForeignKey("actions.id", ondelete="CASCADE"), primary_key=True),
    Column("responsable_id", UUID(as_uuid=True), ForeignKey("responsables.id", ondelete="CASCADE"), primary_key=True),
    # La cle primaire (action_id, responsable_id) ne sert que dans ce sens :
    # « les actions d'un responsable » faisait un parcours complet de la table.
    Index("ix_action_responsables_responsable_id", "responsable_id"),
)


# ---------------------------------------------------------------------------
# Table d'association Action <-> Responsable de suivi (colonne E)
# ---------------------------------------------------------------------------
# `Action.resp_suivi` reste la cellule brute du classeur : c'est du texte
# libre, parfois composite (« Andry II, Xavier »), et c'est lui qui fait foi a
# la relecture du fichier. Mais un nom ne porte pas d'adresse email : tant que
# la colonne E n'existait que sous cette forme, aucun responsable de suivi ne
# pouvait etre relance. Cette table resout le libelle en fiches reelles, avec
# les memes regles de rapprochement que la colonne D.
action_resp_suivi = Table(
    "action_resp_suivi",
    Base.metadata,
    Column("action_id", UUID(as_uuid=True), ForeignKey("actions.id", ondelete="CASCADE"), primary_key=True),
    Column("responsable_id", UUID(as_uuid=True), ForeignKey("responsables.id", ondelete="CASCADE"), primary_key=True),
    # Meme raison que pour la colonne D : le moteur de relance interroge
    # « les actions suivies par cette personne », soit le sens inverse de la
    # cle primaire.
    Index("ix_action_resp_suivi_responsable_id", "responsable_id"),
)


# Horodatages en `timestamptz`. Les valeurs par défaut sont conscientes du
# fuseau (`datetime.now(timezone.utc)`) : les stocker dans un `TIMESTAMP
# WITHOUT TIME ZONE` faisait échouer asyncpg — donc toute écriture passant
# par l'API — avec « can't subtract offset-naive and offset-aware
# datetimes », pendant que psycopg2 (les workers Celery) l'acceptait en
# supprimant silencieusement le fuseau.


class Responsable(UUIDMixin, Base):
    """Personne responsable d'actions (colonne D - Resp. réalisation)."""

    __tablename__ = "responsables"

    display_name = Column(String(255), unique=True, nullable=False, index=True)
    # Clé de rapprochement : le nom sans casse, accents, espaces ni
    # ponctuation. « AndryII » et « Andry II » désignent la même personne, et
    # l'unicité sur `display_name` seule les laissait cohabiter — d'où une
    # charge éclatée dans les rapports et deux relances pour un seul agent.
    name_key = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True)
    is_mapped = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # `lazy="noload"` : ce côté de la relation n'est jamais lu par
    # l'application — les rapports passent par la table d'association. Le
    # laisser chargeable exposerait à un chargement de toutes les actions d'un
    # responsable au moindre rattachement, soit une IO impossible à effectuer
    # en contexte asynchrone (MissingGreenlet) et de toute façon inutile.
    actions = relationship(
        "Action",
        secondary=action_responsables,
        back_populates="responsables",
        lazy="noload",
    )
    # Actions dont cette personne assure le suivi (colonne E). Meme
    # `lazy="noload"` que `actions`, et pour la meme raison : ce cote n'est
    # jamais parcouru depuis une fiche, seulement filtre depuis une requete.
    actions_suivies = relationship(
        "Action",
        secondary=action_resp_suivi,
        back_populates="suiveurs",
        lazy="noload",
    )
    relances = relationship("RelanceLog", back_populates="responsable", cascade="all, delete-orphan")
    preference_relance = relationship(
        "RelancePreference",
        back_populates="responsable",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Responsable id={self.id} display_name={self.display_name!r} mapped={self.is_mapped}>"


class Project(UUIDMixin, Base):
    __tablename__ = "projects"

    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    source_file_path = Column(String(1024), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    has_phases = Column(Boolean, default=False, nullable=False)  # active le format P01-01-01
    # Mise en veille : le projet reste actif et visible, mais ses retards ne
    # declenchent plus de relance. Un projet suspendu par decision de la
    # direction — budget gele, prestataire en attente — accumulait des actions
    # en retard que personne ne pouvait solder, et noyait les vraies urgences
    # dans les rappels hebdomadaires. `is_active=False` n'etait pas la bonne
    # reponse : il fait disparaitre le projet des tableaux de bord, alors
    # qu'un projet en veille doit rester sous les yeux.
    is_standby = Column(Boolean, default=False, nullable=False, index=True)
    standby_reason = Column(Text, nullable=True)

    # Nature du projet, prise dans le référentiel `type_projet`. `SET NULL` :
    # désactiver ou supprimer une valeur de liste ne doit pas emporter les
    # projets qui s'y rattachaient.
    type_id = Column(
        UUID(as_uuid=True), ForeignKey("referentiels.id", ondelete="SET NULL"), nullable=True
    )

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)

    actions = relationship("Action", back_populates="project", cascade="all, delete-orphan")
    type = relationship("Referentiel", foreign_keys=[type_id], lazy="noload")

    def __repr__(self) -> str:
        return f"<Project id={self.id} code={self.code!r} name={self.name!r}>"


class ActionStatus(str, enum.Enum):
    A_FAIRE = "a_faire"
    EN_COURS = "en_cours"
    EN_RETARD = "en_retard"
    # « Bloqué » figure dans la légende des classeurs de suivi (code couleur
    # rouge) mais n'existait pas dans le modèle : une action à l'arrêt ne
    # pouvait être distinguée d'une action simplement en retard.
    BLOQUE = "bloque"
    TERMINE = "termine"

    @property
    def is_open(self) -> bool:
        """Action encore à traiter (par opposition à terminée)."""
        return self is not ActionStatus.TERMINE


class Action(UUIDMixin, Base):
    __tablename__ = "actions"
    __table_args__ = (
        UniqueConstraint("project_id", "numero", name="uq_action_project_numero"),
        # Index partiel dedie au filtre « actions en retard » : il ne porte que
        # sur les actions ouvertes, donc reste petit meme quand l'historique
        # des actions terminees grossit.
        Index(
            "ix_actions_open_deadline",
            "deadline",
            postgresql_where=text("progress < 100.0"),
        ),
    )

    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)

    numero = Column(String(50), nullable=False)               # B - "P01-01" ou "P01-01-01" si phase
    phase = Column(String(10), nullable=True)                  # phase du projet (ex: "01"), si has_phases
    description = Column(Text, nullable=False)                 # C
    # D "Resp. réalisation" -> via la relation responsables (many-to-many)
    resp_suivi = Column(String(255), nullable=True)            # E
    progress = Column(Float, default=0.0, nullable=False)      # F
    spi = Column(Float, default=0.0, nullable=False)          # G
    otd = Column(Float, default=0.0, nullable=False)          # H
    deadline = Column(Date, nullable=True, index=True)         # I
    date_realisation = Column(Date, nullable=True)             # J
    charges_hj = Column(Float, nullable=True)                  # K - Charges (h/j)
    commentaire = Column(Text, nullable=True)                  # L
    status = Column(Enum(ActionStatus), default=ActionStatus.A_FAIRE, nullable=False, index=True)  # champ interne, pas dans le tableau Excel
    # Mise en veille au grain de l'action, meme role que sur le projet : une
    # action en attente d'un tiers reste comptee dans les tableaux de bord
    # mais sort des relances.
    is_standby = Column(Boolean, default=False, nullable=False, index=True)
    standby_reason = Column(Text, nullable=True)

    # Nature de l'action, prise dans le référentiel `categorie_action`. Elle
    # ne vient pas des classeurs Excel, qui n'ont pas cette colonne : c'est
    # une information propre à l'outil, que l'import doit donc préserver.
    categorie_id = Column(
        UUID(as_uuid=True), ForeignKey("referentiels.id", ondelete="SET NULL"), nullable=True
    )

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    project = relationship("Project", back_populates="actions")
    responsables = relationship("Responsable", secondary=action_responsables, back_populates="actions")  # D
    # Resolution de la colonne E en fiches responsables : c'est elle qui rend
    # le responsable de suivi joignable par email.
    suiveurs = relationship(
        "Responsable", secondary=action_resp_suivi, back_populates="actions_suivies"
    )
    categorie = relationship("Referentiel", foreign_keys=[categorie_id], lazy="noload")

    @property
    def project_code(self) -> str | None:
        """Code du projet porteur, ou None si la relation n'est pas chargée.

        Lu dans `__dict__` plutôt que par `self.project` : sur une session
        asynchrone, l'accès à une relation non chargée déclencherait un
        lazy-load hors contexte greenlet (MissingGreenlet). Les routes qui
        exposent ce champ chargent la relation explicitement.
        """
        projet = self.__dict__.get("project")
        return projet.code if projet is not None else None

    @property
    def project_name(self) -> str | None:
        """Nom du projet porteur — mêmes précautions que `project_code`."""
        projet = self.__dict__.get("project")
        return projet.name if projet is not None else None

    def is_overdue(self, today: date | None = None) -> bool:
        """Échéance dépassée et action non terminée.

        Le retard commence le lendemain de l'échéance : livrer le jour J
        compte comme tenu du point de vue de l'OTD, donc ne pas avoir fini
        le jour J n'est pas encore un retard.
        """
        today = today or datetime.now(timezone.utc).date()
        return self.deadline is not None and self.deadline < today and self.progress < 100.0

    def __repr__(self) -> str:
        return f"<Action id={self.id} numero={self.numero!r} progress={self.progress}>"

class SyncStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class SyncLog(UUIDMixin, Base):
    __tablename__ = "sync_logs"

    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Enum(SyncStatus), default=SyncStatus.RUNNING, nullable=False)
    files_processed = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<SyncLog id={self.id} status={self.status} files={self.files_processed}>"


#: Jours d'envoi par defaut : lundi et jeudi. La demande est « deux fois par
#: semaine » ; deux jours espaces valent mieux que deux jours consecutifs, et
#: le lundi precede la reunion de suivi.
DEFAULT_JOURS_ENVOI = "0,3"

#: Heure d'envoi par defaut, dans le fuseau du beat (Indian/Antananarivo).
DEFAULT_HEURE_ENVOI = 8


class RelancePerimetre(str, enum.Enum):
    """Quelles actions une personne recoit dans sa relance.

    Une meme personne est souvent responsable de suivi sur certaines actions
    et responsable de realisation sur d'autres. Confondre les deux enverrait
    au suiveur des actions qu'il ne pilote pas, et au realisateur des actions
    qu'il ne fait pas — dans les deux cas un mail qu'on apprend a ignorer.
    """

    #: Actions dont la personne assure le suivi (colonne E). Valeur par defaut.
    SUIVI = "suivi"
    #: Actions que la personne doit realiser (colonne D).
    REALISATION = "realisation"
    LES_DEUX = "les_deux"


class RelancePreference(UUIDMixin, Base):
    """Regles d'envoi propres a une personne.

    Le moteur envoyait le meme rappel a tout le monde, aux memes heures, sur
    un decoupage fige en trois natures. Une relance utile n'a pas la meme
    cadence pour un chef de projet qui suit quarante actions et pour un
    intervenant qui en porte deux : sans reglage, le premier finit par filtrer
    l'expediteur. Chaque personne fixe donc ses jours, son heure et le contenu
    de son recapitulatif.

    L'absence de ligne vaut acceptation des valeurs par defaut : personne n'a
    besoin de configurer quoi que ce soit pour etre relance.
    """

    __tablename__ = "relance_preferences"

    responsable_id = Column(
        UUID(as_uuid=True),
        ForeignKey("responsables.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    #: Coupe toute relance automatique, sans effacer le reglage.
    enabled = Column(Boolean, default=True, nullable=False)
    perimeter = Column(
        Enum(RelancePerimetre), default=RelancePerimetre.SUIVI, nullable=False
    )

    #: Jours d'envoi, en indices Python (0 = lundi … 6 = dimanche), separes
    #: par des virgules. Le nombre de jours *est* la frequence hebdomadaire :
    #: stocker les deux serait s'exposer a ce qu'ils se contredisent.
    days_of_week = Column(String(20), default=DEFAULT_JOURS_ENVOI, nullable=False)
    send_hour = Column(Integer, default=DEFAULT_HEURE_ENVOI, nullable=False)

    # Sections du recapitulatif. Elles sont disjointes : une action apparait
    # dans une seule, sinon la meme ligne serait comptee deux fois dans le
    # total annonce en objet.
    include_overdue = Column(Boolean, default=True, nullable=False)
    include_today = Column(Boolean, default=True, nullable=False)
    include_due_soon = Column(Boolean, default=True, nullable=False)
    #: Actions ouvertes hors des trois fenetres ci-dessus : sans echeance, ou
    #: a echeance lointaine. C'est le « en attente » du reste de l'outil.
    include_pending = Column(Boolean, default=True, nullable=False)

    #: Fenetre de la section « echeance proche », en jours.
    horizon_days = Column(Integer, default=3, nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    responsable = relationship("Responsable", back_populates="preference_relance")

    @property
    def jours(self) -> list[int]:
        """Jours d'envoi, tries et dedoublonnes."""
        return parse_jours(self.days_of_week)

    @property
    def frequence_hebdomadaire(self) -> int:
        return len(self.jours)

    def __repr__(self) -> str:
        return (
            f"<RelancePreference responsable_id={self.responsable_id} "
            f"jours={self.days_of_week!r} h={self.send_hour} "
            f"perimetre={self.perimeter}>"
        )


def parse_jours(brut: str | None) -> list[int]:
    """Lit « 0,3 » en [0, 3], en ignorant tout ce qui n'est pas un jour valide.

    Tolerante par construction : cette valeur traverse une colonne texte, et
    une relance ne doit pas s'arreter parce qu'un reglage est mal forme — au
    pire elle ne part pas ce jour-la.
    """
    jours: set[int] = set()
    for morceau in (brut or "").split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        try:
            valeur = int(morceau)
        except ValueError:
            continue
        if 0 <= valeur <= 6:
            jours.add(valeur)
    return sorted(jours)


class RelanceLog(UUIDMixin, Base):
    __tablename__ = "relance_logs"

    responsable_id = Column(UUID(as_uuid=True), ForeignKey("responsables.id", ondelete="CASCADE"), nullable=False, index=True)
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    action_ids = Column(Text, nullable=False)
    email_status = Column(String(50), default="sent", nullable=False)
    #: Nature de l'envoi : `digest` pour le recapitulatif planifie, sinon la
    #: valeur de `RelanceKind`. Sans elle, impossible de distinguer dans
    #: l'historique un envoi automatique d'un rappel declenche a la main — ni
    #: de rendre le beat idempotent, ce qui demande de savoir si *ce* type de
    #: message est deja parti aujourd'hui.
    kind = Column(String(20), default="digest", nullable=False, index=True)
    action_count = Column(Integer, default=0, nullable=False)

    responsable = relationship("Responsable", back_populates="relances")

    def __repr__(self) -> str:
        return f"<RelanceLog id={self.id} responsable_id={self.responsable_id} sent_at={self.sent_at}>"
