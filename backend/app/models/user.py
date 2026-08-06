import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.base import UUIDMixin


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    RESPONSABLE_SI = "responsable_si"
    LECTEUR = "lecteur"


class User(UUIDMixin, Base):
    """
    Compte interne authentifié via SSO Microsoft (MSAL/Azure AD).
    Distinct de `Responsable` (models/project.py), qui est le nom
    "Resp. réalisation" extrait des fichiers Excel — un Responsable
    n'a pas forcément de compte applicatif.
    """

    __tablename__ = "users"

    azure_object_id = Column(String(36), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.LECTEUR, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role}>"
