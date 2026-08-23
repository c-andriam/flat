"""
Rapprochement et découpage des noms de responsables saisis à la main.

Les classeurs de suivi écrivent la même personne de plusieurs façons —
« AndryII », « Andry II », « andry II » — et mettent parfois plusieurs
personnes dans une seule cellule — « Meylis-Hassen », « Manoa -Karine ».
Chaque variante créait sa propre fiche responsable : une charge de travail
éclatée dans les rapports, et des relances qui n'atteignaient personne.

Ce module est la définition unique de ces deux règles. Elles vivaient
auparavant en double, dans le parseur Excel et dans la validation d'API, et
avaient déjà divergé.
"""

import os
import re
import unicodedata

_NON_ALPHANUM = re.compile(r"[^a-z0-9]")

#: Séparateurs qui désignent plusieurs personnes dans une même cellule :
#: « Meylis / Xavier », « Manda, Xavier », « Xavier et Manda ». Le tiret en
#: fait partie — « Meylis-Hassen », « Manoa -Karine » — les classeurs ne
#: l'espaçant pas régulièrement.
#:
#: Les limites de mot autour de « et » sont indispensables : sans elles,
#: « Teknet » et « Peter » seraient coupés en deux.
_SEPARATEURS = re.compile(r"\s*(?:/|,|&|\+|-|\bet\b)\s*", re.IGNORECASE)

#: Séparateurs sans ambiguïté possible — le tiret en est volontairement exclu.
#: Une virgule ou une esperluette dans une entrée de liste trahit un appel
#: fautif ; un tiret peut simplement être un prénom composé.
_SEPARATEURS_FORTS = re.compile(r"\s*(?:/|,|&|\+|\bet\b)\s*", re.IGNORECASE)


def normalize_key(nom: str | None) -> str:
    """Clé de rapprochement d'un nom de personne.

    « Andry II », « AndryII » et « andry-ii » donnent tous `andryii`.
    « Andry I » reste distinct de « Andry II » : seuls les caractères non
    alphanumériques disparaissent, jamais les chiffres ni les lettres.
    """
    texte = unicodedata.normalize("NFD", str(nom or ""))
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return _NON_ALPHANUM.sub("", texte.lower())


def dedupe(noms) -> list[str]:
    """Retire les doublons d'une liste de noms.

    L'ordre et la première graphie rencontrée sont conservés : la clé sert à
    comparer, jamais à réécrire le nom affiché.
    """
    vus: set[str] = set()
    resultat: list[str] = []
    for nom in noms:
        nom = re.sub(r"\s+", " ", str(nom or "")).strip()
        if not nom:
            continue
        cle = normalize_key(nom)
        if not cle or cle in vus:
            continue
        vus.add(cle)
        resultat.append(nom)
    return resultat


def noms_insecables() -> frozenset[str]:
    """Noms à ne jamais découper, sous forme de clés de rapprochement.

    Le tiret sépare deux personnes dans les classeurs, mais il fait aussi
    partie de certains prénoms — « Jean-Pierre ». Le jour où un tel nom
    apparaît, l'inscrire dans `RESPONSABLES_INSECABLES` (séparés par des
    virgules) empêche son découpage, sans toucher au code.
    """
    brut = os.getenv("RESPONSABLES_INSECABLES", "")
    return frozenset(normalize_key(n) for n in brut.split(",") if normalize_key(n))


def split_personnes(libelle: str) -> list[str]:
    """Personnes contenues dans un libellé, dédoublonnées.

    Un libellé inscrit dans `RESPONSABLES_INSECABLES` est renvoyé tel quel.
    """
    libelle = re.sub(r"\s+", " ", str(libelle or "")).strip()
    if not libelle:
        return []
    if normalize_key(libelle) in noms_insecables():
        return [libelle]
    return dedupe(morceau.strip(" .;-") for morceau in _SEPARATEURS.split(libelle))


def contient_separateur_fort(libelle: str) -> bool:
    """Le libellé contient-il un séparateur qui ne peut pas être un nom ?

    Sert à distinguer une erreur d'appel d'une ambiguïté légitime. Dans une
    liste `responsable_names`, l'appelant a déjà séparé les personnes : y
    trouver « Andry, Xavier » est une faute qu'il vaut mieux signaler que
    corriger en silence. Un tiret, lui, ne prouve rien.
    """
    libelle = str(libelle or "").strip()
    if not libelle:
        return False
    return len([m for m in _SEPARATEURS_FORTS.split(libelle) if m.strip()]) > 1


def email_designe(email: str | None, libelle: str) -> bool:
    """L'adresse email désigne-t-elle la personne nommée par ce libellé ?

    La partie locale de l'adresse est normalisée comme un nom — accents et
    ponctuation retirés — puis comparée en préfixe :

        « Jean-Pierre » + jeanpierre.eloi@…   -> vrai  (une personne)
        « karine - hassen » + karine.raz@…    -> faux  (deux personnes)

    Le sens de la comparaison compte. On demande que l'adresse *commence* par
    le nom concaténé, et non l'inverse : « karineraz » ne commence pas par
    « karinehassen », alors que « karinehassen » commencerait bien par
    « karine » et ferait passer deux personnes pour une seule.
    """
    if not email or "@" not in email:
        return False
    local = normalize_key(email.split("@", 1)[0])
    cle = normalize_key(libelle)
    if not local or not cle:
        return False
    return local.startswith(cle)


def personnes_du_libelle(libelle: str, emails_connus) -> list[str]:
    """Personnes désignées par un libellé, à la lumière des emails connus.

    `split_personnes` traite le tiret comme un séparateur, ce qui est correct
    pour « karine - hassen » et faux pour « Jean-Pierre ». Départager les deux
    demande une information que le libellé ne porte pas : l'existence d'une
    adresse email au même nom. C'est pourquoi cette décision ne peut pas être
    prise dans un validateur de schéma, qui s'exécute avant tout accès aux
    données.
    """
    libelle = str(libelle or "").strip()
    if not libelle:
        return []
    morceaux = split_personnes(libelle)
    if len(morceaux) <= 1:
        return morceaux or [libelle]
    if any(email_designe(email, libelle) for email in emails_connus):
        return [libelle]
    return morceaux
