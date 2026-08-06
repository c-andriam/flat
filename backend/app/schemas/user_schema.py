import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserUpdate(BaseModel):
    """Seuls le rôle et le statut actif sont modifiables manuellement (admin)."""

    role: str | None = None
    is_active: bool | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None
