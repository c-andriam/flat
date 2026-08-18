"""
Parsing des classeurs de suivi de projets DSIO.

Structure réelle des fichiers (constatée sur les 21 classeurs de
`07_Projets_DSIO/Projet encours`) :

  - Le tableau ne commence pas en haut de la feuille. Il est précédé d'un bloc
    de titre, de la composition de l'équipe et de la légende KPI ; la ligne
    d'en-tête se situe entre la ligne 11 et la ligne 19 selon les fichiers.
  - Chaque classeur contient au moins deux feuilles : le planning et un tableau
    de bord `TDB Projet(...)`. Certains en contiennent cinq, avec d'anciennes
    versions du planning. Le nom de la feuille n'est pas fiable — le classeur
    de P32 a gardé le nom de feuille de P29 dont il est la copie.
  - Les lignes de données sont espacées d'une ligne sur deux, à cause de
    fusions verticales.
  - La colonne A porte la phase (« P01 - Cantine - Phase 2 »), fusionnée sur
    tout le bloc : seule la première ligne de la phase la contient.
  - Le tableau mélange des lignes d'action et des lignes de section
    (« FINANCE », « Pointages Tamatave ») qui n'ont ni responsable, ni
    échéance, ni avancement.
  - Les pourcentages sont stockés au format Excel : « 100 % » vaut 1.0.
  - Le numéro est saisi à la main, avec un espacement variable autour des
    tirets, et son préfixe désigne parfois la phase plutôt que le projet
    (dans P01, la phase 2 est numérotée « P02 - 01 »).

Le numéro canonique est celui du fichier consolidé « Liste de tous les
actions.xlsx » : `CODE-PHASE-SEQUENCE` (`P01-02-05`), ou `CODE-SEQUENCE`
(`P04-01`) pour un projet sans phases, ou encore `CODE-N1-N2-SEQUENCE`
(`P10-1-1-01`) pour les projets à deux niveaux de découpage. Le parseur le
reconstruit à partir du code projet, de la phase et du dernier segment du
numéro saisi, ce qui corrige au passage les préfixes erronés.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl

logger = logging.getLogger("excel-parser")

# Segments séparés par des tirets, le dernier étant numérique.
_NUMERO_RE = re.compile(r"^[A-Za-z0-9]+(?:\s*-\s*[A-Za-z0-9]+)+$")
_PHASE_RE = re.compile(r"phase\s*n?°?\s*(\d+)", re.IGNORECASE)

# Séparateurs de responsables : « Meylis / Xavier », « Manda, Xavier »,
# « AndryII - Teknet », « Xavier et Manda ».
_SEP_RESPONSABLES = re.compile(r"\s*(?:/|,|&|\+|\s-\s|\bet\b)\s*", re.IGNORECASE)

# Lignes explorées à la recherche de l'en-tête avant d'abandonner une feuille.
_MAX_HEADER_SCAN = 40

#: Colonnes attendues, repérées par le libellé de l'en-tête plutôt que par
#: leur position : un classeur où une colonne aurait été insérée resterait
#: lisible.
_CHAMPS = {
    "section": ("projets", "projet"),
    "numero": ("ndaction", "ndactions", "naction", "nactions", "numeroaction", "numerodaction", "numero"),
    "description": ("actions", "action", "taches", "tache", "libelle", "intitule"),
    "responsables": ("resprealisation", "responsablerealisation", "respderealisation", "realisateur"),
    "resp_suivi": ("respsuivi", "responsablesuivi", "respdesuivi", "suiveur"),
    "progress": ("progress", "avancement", "progression", "pourcentageavancement"),
    "spi": ("spi",),
    "otd": ("otd",),
    "deadline": ("deadline", "datecible", "echeance", "datedeadline", "dateobjectif"),
    "date_realisation": ("datederealisation", "daterealisation", "realisation", "datereelle"),
    "charges_hj": ("chargeshj", "chargehj", "charges", "charge"),
    "commentaire": ("commentaires", "commentaire", "observation", "observations", "remarques"),
}

#: Champs sans lesquels une feuille n'est pas un planning exploitable.
_CHAMPS_REQUIS = ("numero", "description", "deadline")

#: Un tableau de bord n'est jamais une source d'actions.
_FEUILLES_IGNOREES = re.compile(r"^\s*(tdb|dashboard|tableau de bord)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParsedAction:
    numero: str
    numero_source: str
    phase: str | None
    section: str | None
    description: str
    responsable_names: list[str]
    resp_suivi: str | None
    progress: float
    spi: float
    otd: float
    deadline: date | None
    date_realisation: date | None
    charges_hj: float | None
    commentaire: str | None
    row: int

    def as_dict(self) -> dict:
        return {
            "numero": self.numero,
            "numero_source": self.numero_source,
            "phase": self.phase,
            "section": self.section,
            "description": self.description,
            "responsable_names": list(self.responsable_names),
            "resp_suivi": self.resp_suivi,
            "progress": self.progress,
            "spi": self.spi,
            "otd": self.otd,
            "deadline": self.deadline,
            "date_realisation": self.date_realisation,
            "charges_hj": self.charges_hj,
            "commentaire": self.commentaire,
            "row": self.row,
        }


@dataclass
class ParseResult:
    """Actions extraites et diagnostic de lecture.

    Le diagnostic n'est pas décoratif : un classeur qui ne remonte aucune
    action doit dire pourquoi (feuille introuvable, tableau vide, colonnes
    manquantes) plutôt que de laisser croire à un projet sans travaux.
    """

    actions: list[ParsedAction] = field(default_factory=list)
    sheet_name: str | None = None
    header_row: int | None = None
    project_code: str | None = None
    phases: list[str] = field(default_factory=list)
    section_rows: int = 0
    skipped_rows: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dicts(self) -> list[dict]:
        return [a.as_dict() for a in self.actions]


# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------

def _sans_accents(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn"
    )


def _normaliser_libelle(valeur: Any) -> str:
    """Libellé d'en-tête ramené à une forme comparable.

    Toute la ponctuation et les espaces sont retirés : les classeurs écrivent
    « N° d'actions », « N° d'Action », « Resp. réalisation » ou
    « Charges (h/j) » de façons trop variées pour une comparaison littérale.
    """
    texte = _sans_accents(str(valeur or "")).lower()
    return re.sub(r"[^a-z0-9]", "", texte)


def _safe_float(valeur: Any, default: float | None = 0.0) -> float | None:
    if valeur is None:
        return default
    if isinstance(valeur, str):
        valeur = valeur.strip().replace(",", ".").replace("%", "")
        if not valeur:
            return default
    try:
        return float(valeur)
    except (ValueError, TypeError):
        return default


def _est_pourcentage(cellule) -> bool:
    return "%" in (getattr(cellule, "number_format", "") or "")


def _pourcentage(cellule) -> float:
    """Avancement ramené sur une échelle 0-100.

    Excel stocke une cellule affichée « 100 % » sous la forme du nombre 1.0.
    Lue telle quelle, une action terminée arrivait en base à `progress=1.0`,
    soit 1 % : toutes les actions closes ressortaient « à faire » et le moteur
    de relance les rappelait à leurs responsables.
    """
    valeur = _safe_float(cellule.value if cellule is not None else None)
    if valeur is None:
        return 0.0
    if _est_pourcentage(cellule):
        valeur *= 100.0
    return max(0.0, min(100.0, round(valeur, 2)))


def _ratio(cellule) -> float:
    """SPI / OTD : même stockage en pourcentage, sans plafond à 100."""
    valeur = _safe_float(cellule.value if cellule is not None else None) or 0.0
    if _est_pourcentage(cellule):
        valeur *= 100.0
    return round(max(0.0, valeur), 2)


_FORMATS_DATE = (
    "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y",
    "%d/%m/%y", "%m/%d/%y", "%d.%m.%Y", "%d %m %Y",
)


def _safe_date(valeur: Any) -> date | None:
    if valeur is None:
        return None
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    texte = str(valeur).strip()
    # Les cellules non renseignées contiennent souvent un tiret de remplissage.
    if not texte or texte in {"-", "--", "/", "n/a", "N/A"}:
        return None
    for fmt in _FORMATS_DATE:
        try:
            return datetime.strptime(texte, fmt).date()
        except ValueError:
            continue
    logger.warning("Date non reconnue, ignorée : %r", texte)
    return None


def _est_renseigne(valeur: Any) -> bool:
    """Vrai si la cellule contient autre chose qu'un remplissage de mise en page."""
    if valeur is None:
        return False
    return str(valeur).strip() not in {"", "-", "--", "/", "n/a", "N/A"}


def _nettoyer_nom(nom: str) -> str:
    """Espaces, retours à la ligne et ponctuation résiduelle."""
    return re.sub(r"\s+", " ", nom.replace("\n", " ")).strip(" .;-")


def _parse_responsables(valeur: Any) -> list[str]:
    """Liste des responsables, dédoublonnée sans tenir compte de la casse.

    « xavier » et « Xavier » désignent la même personne : les compter pour
    deux créerait deux fiches responsable, donc deux relances distinctes.
    """
    if not valeur:
        return []
    noms: list[str] = []
    vus: set[str] = set()
    for morceau in _SEP_RESPONSABLES.split(str(valeur)):
        nom = _nettoyer_nom(morceau)
        if not nom:
            continue
        cle = _sans_accents(nom).lower()
        if cle in vus:
            continue
        vus.add(cle)
        noms.append(nom)
    return noms


def normalize_numero(brut: Any) -> str:
    """« Po1 -02- 05 » et « P01-02-05 » désignent la même action."""
    texte = re.sub(r"\s+", " ", str(brut or "").replace("\n", " ")).strip()
    if not texte:
        return ""
    return "-".join(segment.strip() for segment in texte.split("-") if segment.strip())


def _segments(numero: str) -> list[str]:
    return [s for s in numero.split("-") if s]


def canonical_numero(project_code: str | None, phase: str | None, numero_source: str) -> str:
    """Reconstruit le numéro sous la forme du fichier consolidé.

    `CODE-PHASE-SEQUENCE`, ou `CODE-SEQUENCE` sans phase. Le préfixe saisi est
    ignoré : dans le classeur de P01, la phase 2 est numérotée « P02 - 01 », ce
    qui produirait un numéro faisant référence à un autre projet.
    """
    normalise = normalize_numero(numero_source)
    segments = _segments(normalise)
    if not segments:
        return ""
    sequence = segments[-1]
    if not project_code:
        return normalise
    if phase:
        return f"{project_code}-{phase}-{sequence}"
    return f"{project_code}-{sequence}"


def split_phase(numero: str) -> str | None:
    """Segments intermédiaires d'un numéro : `P10-1-1-01` -> `1-1`."""
    segments = _segments(numero)
    if len(segments) >= 3:
        return "-".join(segments[1:-1])
    return None


def _niveau_section(token: str, pile: list[str]) -> str:
    """Rétablit les tirets manquants dans le niveau d'une section.

    Les classeurs alternent entre `P10-1-1` et `P10-12` pour désigner la même
    profondeur, et le fichier consolidé retient partout la forme à tirets. On
    la reconstitue à partir de la section parente : sous « P10-1 », le niveau
    « 12 » est « 1-2 ». Sans cette normalisation, une même sous-section porte
    deux identifiants selon la façon dont elle a été saisie.
    """
    compact = token.replace("-", "")
    for parent in reversed(pile):
        parent_compact = parent.replace("-", "")
        if compact != parent_compact and compact.startswith(parent_compact):
            return f"{parent}-{compact[len(parent_compact):]}"
    return token


def _phase_depuis_libelle(libelle: Any) -> str | None:
    """« P01 - Cantine - Phase 2 » -> « 02 »."""
    correspondance = _PHASE_RE.search(str(libelle or ""))
    if not correspondance:
        return None
    return correspondance.group(1).zfill(2)


# ---------------------------------------------------------------------------
# Repérage du tableau
# ---------------------------------------------------------------------------

def _mapper_colonnes(ligne) -> dict[str, str]:
    """Associe chaque champ attendu à sa lettre de colonne."""
    colonnes: dict[str, str] = {}
    for cellule in ligne:
        libelle = _normaliser_libelle(cellule.value)
        if not libelle:
            continue
        for champ, alias in _CHAMPS.items():
            if champ in colonnes:
                continue
            if libelle in alias:
                colonnes[champ] = cellule.column_letter
                break
    return colonnes


def _trouver_tableau(worksheet) -> tuple[int, dict[str, str]] | None:
    limite = min(_MAX_HEADER_SCAN, worksheet.max_row)
    for ligne in worksheet.iter_rows(min_row=1, max_row=limite, max_col=20):
        colonnes = _mapper_colonnes(ligne)
        if all(champ in colonnes for champ in _CHAMPS_REQUIS):
            return ligne[0].row, colonnes
    return None


def _choisir_feuille(workbook) -> tuple[Any, int, dict[str, str]] | None:
    """Feuille de planning du classeur.

    `workbook.active` n'est pas fiable : plusieurs classeurs embarquent un
    tableau de bord et d'anciennes copies du planning, et le classeur de P32 a
    conservé le nom de feuille de P29 dont il est issu. On retient la feuille
    qui contient réellement un tableau d'actions.
    """
    candidates = []
    for nom in workbook.sheetnames:
        if _FEUILLES_IGNOREES.match(nom):
            continue
        worksheet = workbook[nom]
        trouve = _trouver_tableau(worksheet)
        if trouve:
            entete, colonnes = trouve
            candidates.append(
                (len(colonnes), -workbook.sheetnames.index(nom), nom, entete, colonnes)
            )
    if not candidates:
        return None
    # Le plus de colonnes reconnues gagne ; à égalité, la feuille la plus à
    # gauche, qui est le planning courant (les copies sont ajoutées après).
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    _, _, nom, entete, colonnes = candidates[0]
    return workbook[nom], entete, colonnes


def _valeurs_fusionnees(worksheet) -> dict[tuple[int, int], Any]:
    """Valeur de la cellule haut-gauche pour chaque cellule d'une fusion.

    La phase n'est écrite que sur la première ligne de son bloc (`A16:A47`) ;
    sans cette résolution, toutes les actions suivantes la perdent.
    """
    valeurs: dict[tuple[int, int], Any] = {}
    for plage in worksheet.merged_cells.ranges:
        origine = worksheet.cell(row=plage.min_row, column=plage.min_col).value
        if origine is None:
            continue
        for ligne in range(plage.min_row, plage.max_row + 1):
            for colonne in range(plage.min_col, plage.max_col + 1):
                valeurs[(ligne, colonne)] = origine
    return valeurs


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------

def parse_workbook(
    file_path: str | Path,
    project_code: str | None = None,
    sheet_name: str | None = None,
) -> ParseResult:
    """Lit un classeur de suivi et renvoie ses actions avec un diagnostic."""
    chemin = Path(file_path)
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")
    if chemin.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError(f"Format non supporté : {chemin.suffix} (attendu .xlsx ou .xlsm)")

    try:
        # Pas de `read_only` : ce mode n'expose pas les cellules fusionnées, or
        # la phase n'existe que dans la cellule d'origine de la fusion. Les
        # classeurs font au plus quelques centaines de lignes.
        workbook = openpyxl.load_workbook(str(chemin), data_only=True)
    except Exception as exc:
        raise ValueError(f"Impossible de lire le fichier Excel {chemin.name}: {exc}") from exc

    resultat = ParseResult(project_code=project_code)
    try:
        if sheet_name is not None:
            if sheet_name not in workbook.sheetnames:
                raise ValueError(f"Feuille introuvable: {sheet_name}")
            worksheet = workbook[sheet_name]
            trouve = _trouver_tableau(worksheet)
            if not trouve:
                resultat.warnings.append(
                    f"Aucun tableau d'actions reconnu dans la feuille {sheet_name!r}."
                )
                return resultat
            entete, colonnes = trouve
        else:
            choix = _choisir_feuille(workbook)
            if choix is None:
                resultat.warnings.append(
                    "Aucune feuille ne contient de tableau d'actions reconnaissable "
                    f"(feuilles : {', '.join(workbook.sheetnames)}). Vérifier que la "
                    "ligne d'en-tête comporte bien « N° d'action », « Actions » et "
                    "« Deadline »."
                )
                return resultat
            worksheet, entete, colonnes = choix

        resultat.sheet_name = worksheet.title
        resultat.header_row = entete

        manquantes = [c for c in _CHAMPS if c not in colonnes]
        if manquantes:
            resultat.warnings.append(
                "Colonnes absentes de l'en-tête, valeurs par défaut appliquées : "
                + ", ".join(manquantes)
            )

        fusions = _valeurs_fusionnees(worksheet)

        def valeur(ligne: int, champ: str):
            lettre = colonnes.get(champ)
            if not lettre:
                return None
            cellule = worksheet[f"{lettre}{ligne}"]
            if cellule.value is not None:
                return cellule.value
            # La résolution des fusions ne vaut que pour la colonne « Projets »,
            # où la phase est écrite une seule fois pour tout son bloc. Étendue
            # aux autres colonnes, elle ferait hériter à la ligne de
            # continuation d'une fusion verticale le numéro de la ligne
            # au-dessus : chaque action était alors lue deux fois.
            if champ == "section":
                return fusions.get((ligne, cellule.column))
            return None

        def cellule_de(ligne: int, champ: str):
            lettre = colonnes.get(champ)
            return worksheet[f"{lettre}{ligne}"] if lettre else None

        phase_courante: str | None = None
        section_courante: str | None = None
        pile_sections: list[str] = []
        code_projet = project_code

        for ligne in range(entete + 1, worksheet.max_row + 1):
            numero_source = normalize_numero(valeur(ligne, "numero"))
            description = _nettoyer_nom(str(valeur(ligne, "description") or ""))
            libelle_section = valeur(ligne, "section")

            # Phase portée par la colonne « Projets », fusionnée sur le bloc.
            phase_libelle = _phase_depuis_libelle(libelle_section)
            if phase_libelle:
                phase_courante = phase_libelle

            if not numero_source or not _NUMERO_RE.match(numero_source):
                # Ligne vide, ou ligne de total en pied de tableau.
                resultat.skipped_rows += 1
                continue

            # Le code projet se déduit du premier numéro rencontré, faute de
            # mieux — mais l'appelant devrait le fournir : dans P01 la phase 2
            # est numérotée « P02 - 01 », et dans P02 la première action porte
            # « P01 - 01 » par erreur de saisie.
            if code_projet is None:
                code_projet = _segments(numero_source)[0]
                resultat.project_code = code_projet
                resultat.warnings.append(
                    f"Code projet non fourni, déduit du premier numéro : {code_projet!r}."
                )

            # Une ligne de section n'a ni responsable, ni échéance, ni
            # avancement : elle sert de titre à un groupe d'actions
            # (« FINANCE », « Pointages Tamatave »).
            porte_des_donnees = any(
                valeur(ligne, champ) is not None
                for champ in ("responsables", "deadline", "progress", "resp_suivi")
            )
            if not porte_des_donnees:
                section_courante = description or section_courante
                resultat.section_rows += 1
                # Le numéro d'une section encode le niveau de découpage
                # (« P10-1-1 ») : il devient la phase des actions qui suivent.
                segments_section = _segments(numero_source)
                if len(segments_section) >= 2 and not phase_libelle:
                    niveau = _niveau_section("-".join(segments_section[1:]), pile_sections)
                    if niveau not in pile_sections:
                        pile_sections.append(niveau)
                    phase_courante = niveau
                continue

            if not description:
                resultat.warnings.append(
                    f"Ligne {ligne} ignorée : numéro {numero_source!r} sans description."
                )
                resultat.skipped_rows += 1
                continue

            # La section englobante fait autorité sur le numéro saisi : dans
            # P10, les actions de la section « P10-13 » sont numérotées
            # « P02 -13 - 1 », avec un préfixe qui désigne un autre projet.
            # Le numéro de l'action ne sert que faute de section.
            phase = phase_courante or split_phase(numero_source)

            deadline_brute = valeur(ligne, "deadline")
            deadline = _safe_date(deadline_brute)
            if deadline is None and _est_renseigne(deadline_brute):
                # Une échéance illisible sort l'action de toutes les vues de
                # retard et de prévision : le silence serait pire que le bruit.
                resultat.warnings.append(
                    f"Ligne {ligne} ({numero_source}) : échéance illisible "
                    f"{deadline_brute!r}, action sans date cible."
                )

            resultat.actions.append(
                ParsedAction(
                    numero=canonical_numero(code_projet, phase, numero_source),
                    numero_source=numero_source,
                    phase=phase,
                    section=section_courante,
                    description=description,
                    responsable_names=_parse_responsables(valeur(ligne, "responsables")),
                    resp_suivi=_nettoyer_nom(str(valeur(ligne, "resp_suivi") or "")) or None,
                    progress=_pourcentage(cellule_de(ligne, "progress")),
                    spi=_ratio(cellule_de(ligne, "spi")),
                    otd=_ratio(cellule_de(ligne, "otd")),
                    deadline=deadline,
                    date_realisation=_safe_date(valeur(ligne, "date_realisation")),
                    charges_hj=_safe_float(valeur(ligne, "charges_hj"), default=None),
                    commentaire=_nettoyer_nom(str(valeur(ligne, "commentaire") or "")) or None,
                    row=ligne,
                )
            )

        # Quand un projet est découpé en phases, un bloc laissé sans libellé
        # appartient à la première phase : dans P06 seule la phase 2 est
        # annoncée en colonne A, et sans ce rattrapage ses premières actions
        # obtiendraient un numéro `P06-01` incompatible avec le `P06-01-01` du
        # fichier consolidé.
        phases_connues = sorted({a.phase for a in resultat.actions if a.phase})
        if phases_connues:
            # « 01 » quand le projet numérote ses phases sur deux chiffres,
            # sinon la plus petite connue. Prendre le minimum dans tous les cas
            # rattacherait les actions de P06 à sa phase 2, la seule annoncée.
            defaut = (
                "01"
                if all(re.fullmatch(r"\d{2}", ph) for ph in phases_connues)
                else min(phases_connues, key=lambda ph: (len(ph), ph))
            )
            rattrapees = 0
            for index, action in enumerate(resultat.actions):
                if action.phase:
                    continue
                resultat.actions[index] = replace(
                    action,
                    phase=defaut,
                    numero=canonical_numero(code_projet, defaut, action.numero_source),
                )
                rattrapees += 1
            if rattrapees:
                resultat.warnings.append(
                    f"{rattrapees} action(s) sans phase explicite rattachée(s) à la "
                    f"phase {defaut!r}, la première du projet."
                )

        resultat.phases = sorted({a.phase for a in resultat.actions if a.phase})

        # Doublons de numéro : la contrainte unique (project_id, numero) les
        # rejetterait un par un côté worker, avec un message peu parlant.
        vus: dict[str, int] = {}
        for action in resultat.actions:
            if action.numero in vus:
                resultat.warnings.append(
                    f"Numéro en double : {action.numero!r} lignes {vus[action.numero]} "
                    f"et {action.row}. Une seule des deux actions sera conservée."
                )
            else:
                vus[action.numero] = action.row

        if not resultat.actions:
            resultat.warnings.append(
                f"Tableau trouvé (feuille {resultat.sheet_name!r}, en-tête ligne "
                f"{entete}) mais aucune ligne d'action renseignée."
            )

        logger.info(
            "'%s' : %d actions (feuille %r, en-tête L%s, phases %s), "
            "%d lignes de section, %d lignes ignorées, %d avertissement(s)",
            chemin.name, len(resultat.actions), resultat.sheet_name, entete,
            resultat.phases or "aucune", resultat.section_rows,
            resultat.skipped_rows, len(resultat.warnings),
        )
        for avertissement in resultat.warnings:
            logger.warning("%s : %s", chemin.name, avertissement)

        return resultat
    finally:
        workbook.close()


def parse_excel_file(
    file_path: str | Path,
    sheet_name: str | None = None,
    project_code: str | None = None,
) -> list[dict]:
    """Actions d'un classeur, sous forme de dictionnaires.

    Conserve l'interface attendue par le worker d'ingestion ; utiliser
    `parse_workbook` pour disposer en plus du diagnostic de lecture.
    """
    return parse_workbook(file_path, project_code=project_code, sheet_name=sheet_name).as_dicts()
