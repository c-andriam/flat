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
