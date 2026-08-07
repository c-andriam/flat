import uuid

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import UUID


class UUIDMixin:
    """Clé primaire UUID v4 — évite l'énumération d'IDs séquentiels (1,2,3...)."""

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
