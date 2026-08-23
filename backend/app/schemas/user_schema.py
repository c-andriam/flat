import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import UserRole


class UserUpdate(BaseModel):
    """Seuls le rôle et le statut actif sont modifiables manuellement (admin).

    Les autres champs (email, display_name, azure_object_id) sont la copie
    locale de l'annuaire Entra ID et sont rafraîchis à chaque connexion : les
    modifier ici serait écrasé au prochain login.
    """

    # Typé en énumération : la documentation Swagger annonçait « 'admin',
    # 'user' » alors que les rôles réels sont admin / responsable_si / lecteur.
    role: UserRole | None = Field(
        None,
        description=(
            "Rôle RBAC. `admin` : administration des comptes. "
            "`responsable_si` : lecture + écriture sur projets et actions. "
            "`lecteur` : lecture seule."
        ),
    )
    is_active: bool | None = Field(
        None,
        description=(
            "Désactiver le compte pour empêcher la connexion sans supprimer "
            "l'historique."
        ),
    )


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class LinkedResponsableOut(BaseModel):
    """Fiche responsable rattachée au compte, via l'email."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str


class CurrentUserOut(UserOut):
    """Profil de l'appelant, enrichi de son périmètre de lecture.

    Séparé de `UserOut` : la liste d'administration renvoie des dizaines de
    comptes, et calculer le rattachement de chacun coûterait une requête par
    ligne pour une information que cet écran n'utilise pas.
    """

    sees_all_data: bool = Field(
        ...,
        description=(
            "Vrai pour les rôles `admin` et `dsio`, qui voient l'ensemble du "
            "portefeuille. Faux pour les autres, cloisonnés à leurs propres "
            "actions."
        ),
    )
    linked_responsables: list[LinkedResponsableOut] = Field(
        default_factory=list,
        description=(
            "Fiches responsable portant l'email de ce compte. Vide, un compte "
            "cloisonné ne voit rien : il faut lui associer son adresse."
        ),
    )
