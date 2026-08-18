"""
Limiteur de débit partagé.

`auth_main.py` et `routers/auth.py` instanciaient chacun leur propre
`Limiter`. Les décorateurs comptaient donc sur un stockage différent de celui
enregistré dans `app.state.limiter`, et le compteur repartait de zéro selon le
chemin de code — un même client pouvait dépasser la limite annoncée.
"""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Stockage mémoire par défaut : propre à chaque process uvicorn, donc la limite
# réelle est multipliée par le nombre de workers/réplicas. Renseigner
# `RATELIMIT_STORAGE_URI=redis://redis:6379/1` donne un compteur partagé — au
# prix d'une dépendance de plus sur le chemin de connexion (si Redis tombe,
# plus personne ne se connecte), d'où le choix de ne pas l'activer par défaut.
_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")

limiter = Limiter(key_func=get_remote_address, storage_uri=_STORAGE_URI)
