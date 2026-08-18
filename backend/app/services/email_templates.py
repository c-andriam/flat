"""
Gabarits d'email de relance, au format attendu par Outlook.

Contraintes de rendu — Outlook pour Windows compose le HTML avec le moteur de
Word, pas avec un moteur web :
  - mise en page en `<table>`, jamais en flexbox ni en grid ;
  - styles en ligne sur chaque balise, les feuilles `<style>` étant en partie
    ignorées et les classes CSS non appliquées ;
  - largeur fixe de 600 px, standard courant qui passe sur mobile comme sur
    le volet de lecture ;
  - aucune image distante : les clients de messagerie les bloquent par
    défaut, un gabarit qui en dépend arrive vide.

Chaque email est produit en HTML et en texte brut. La version texte n'est pas
décorative : sans elle, les passerelles anti-spam dégradent la note du message
et les clients en mode texte affichent une page de balises.

Le code couleur reprend celui des classeurs de suivi (bleu planifié, vert
réalisé, rouge bloqué), pour que le mail et le fichier Excel se lisent avec la
même grille.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from html import escape

from app.schemas.report_schema import ActionDigestOut
from app.services.digests import echeance_lisible

# --- Charte ----------------------------------------------------------------
BLEU = "#1F4E9C"       # « Planifié »
ROUGE = "#B3271B"      # « Bloqué » / retard
AMBRE = "#A45B0B"      # échéance proche
VERT = "#226E45"       # « Réalisé »
ENCRE = "#12161D"
ENCRE_DOUCE = "#4E586A"
TRAIT = "#DCE1E9"
FOND = "#F6F7F9"

POLICE = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)


class RelanceKind(str, Enum):
    """Nature du rappel — détermine la sélection des actions et le ton."""

    OVERDUE = "overdue"
    TODAY = "today"
    DUE_SOON = "due_soon"


@dataclass(frozen=True)
class _Ton:
    accent: str
    objet: str
    titre: str
    intro: str
    consigne: str
    colonne_echeance: str


_TONS: dict[RelanceKind, _Ton] = {
    RelanceKind.OVERDUE: _Ton(
        accent=ROUGE,
        objet="Actions en retard — {n} action(s) à régulariser",
        titre="Actions en retard",
        intro=(
            "Les actions ci-dessous ont dépassé leur date cible et ne sont pas "
            "encore terminées."
        ),
        consigne=(
            "Merci de mettre à jour leur avancement, ou de signaler le blocage "
            "à votre responsable de suivi si l'échéance n'est plus tenable."
        ),
        colonne_echeance="Retard",
    ),
    RelanceKind.TODAY: _Ton(
        accent=BLEU,
        objet="Échéance aujourd'hui — {n} action(s)",
        titre="À rendre aujourd'hui",
        intro="Les actions suivantes arrivent à échéance aujourd'hui.",
        consigne=(
            "Si l'une d'elles est déjà terminée, il suffit de passer son "
            "avancement à 100 % pour qu'elle sorte des relances."
        ),
        colonne_echeance="Échéance",
    ),
    RelanceKind.DUE_SOON: _Ton(
        accent=AMBRE,
        objet="Échéances proches — {n} action(s) cette semaine",
        titre="Échéances proches",
        intro="Voici vos actions dont la date cible approche.",
        consigne=(
            "Ce message est un rappel d'anticipation : aucune de ces actions "
            "n'est encore en retard."
        ),
        colonne_echeance="Échéance",
    ),
}


@dataclass(frozen=True)
class EmailMessage:
    """Message prêt à être remis à Outlook."""

    subject: str
    html: str
    text: str
    action_count: int


def _barre_progression(progress: float, accent: str) -> str:
    """Jauge en tableau : les `<div>` à largeur relative ne tiennent pas dans Outlook."""
    pourcent = max(0, min(100, int(round(progress or 0))))
    rempli = max(1, pourcent) if pourcent else 0
    cellules = ""
    if rempli:
        cellules += (
            f'<td width="{rempli}%" bgcolor="{accent}" '
            f'style="height:6px;line-height:6px;font-size:0;">&nbsp;</td>'
        )
    if pourcent < 100:
        cellules += (
            f'<td width="{100 - pourcent}%" bgcolor="{TRAIT}" '
            f'style="height:6px;line-height:6px;font-size:0;">&nbsp;</td>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="width:100%;border-collapse:collapse;">'
        f"<tr>{cellules}</tr></table>"
    )


def _ligne_action(action: ActionDigestOut, ton: _Ton, index: int) -> str:
    fond = "#FFFFFF" if index % 2 == 0 else FOND
    projet = escape(action.project_code or "—")
    numero = escape(action.numero)
    description = escape(action.description or "")
    echeance = escape(echeance_lisible(action))
    date_cible = action.deadline.strftime("%d/%m/%Y") if action.deadline else "—"
    pourcent = int(round(action.progress or 0))

    return f"""
      <tr>
        <td bgcolor="{fond}" style="padding:14px 20px;border-bottom:1px solid {TRAIT};
            font-family:{POLICE};vertical-align:top;">
          <div style="font-size:12px;color:{ENCRE_DOUCE};letter-spacing:.04em;
              text-transform:uppercase;margin-bottom:3px;">
            {projet} &middot; {numero}
          </div>
          <div style="font-size:15px;color:{ENCRE};font-weight:600;line-height:1.4;">
            {description}
          </div>
          <div style="font-size:13px;color:{ENCRE_DOUCE};margin-top:8px;">
            Avancement {pourcent}&nbsp;% &middot; date cible {date_cible}
          </div>
          <div style="margin-top:6px;max-width:260px;">{_barre_progression(action.progress, ton.accent)}</div>
        </td>
        <td bgcolor="{fond}" align="right" style="padding:14px 20px;border-bottom:1px solid {TRAIT};
            font-family:{POLICE};font-size:14px;font-weight:600;color:{ton.accent};
            white-space:nowrap;vertical-align:top;">
          {echeance}
        </td>
      </tr>"""


def build_email(
    kind: RelanceKind,
    responsable_name: str,
    actions: list[ActionDigestOut],
    *,
    app_url: str | None = None,
    today: date | None = None,
) -> EmailMessage:
    """Construit le message correspondant à une nature de rappel."""
    ton = _TONS[kind]
    sujet = ton.objet.format(n=len(actions))
    prenom = escape((responsable_name or "").split()[0] if responsable_name else "")

    lignes = "".join(_ligne_action(a, ton, i) for i, a in enumerate(actions))

    bouton = ""
    if app_url:
        bouton = f"""
          <tr>
            <td style="padding:4px 24px 28px;font-family:{POLICE};">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td bgcolor="{ton.accent}" style="padding:11px 22px;">
                    <a href="{escape(app_url)}" style="color:#FFFFFF;font-size:14px;
                        font-weight:600;text-decoration:none;font-family:{POLICE};">
                      Ouvrir le suivi de projet
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(sujet)}</title>
</head>
<body style="margin:0;padding:0;background-color:{FOND};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       bgcolor="{FOND}" style="background-color:{FOND};">
  <tr>
    <td align="center" style="padding:24px 12px;">

      <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
             style="width:600px;max-width:600px;background-color:#FFFFFF;
                    border:1px solid {TRAIT};border-collapse:collapse;">

        <tr>
          <td bgcolor="{ton.accent}" style="height:4px;line-height:4px;font-size:0;">&nbsp;</td>
        </tr>

        <tr>
          <td style="padding:26px 24px 4px;font-family:{POLICE};">
            <div style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;
                color:{ENCRE_DOUCE};">
              Trimeta Group &middot; Suivi de projets DSI
            </div>
            <h1 style="margin:8px 0 0;font-size:23px;line-height:1.25;color:{ENCRE};
                font-weight:700;">{escape(ton.titre)}</h1>
          </td>
        </tr>

        <tr>
          <td style="padding:14px 24px 0;font-family:{POLICE};font-size:15px;
              line-height:1.6;color:{ENCRE};">
            <p style="margin:0 0 12px;">Bonjour {prenom},</p>
            <p style="margin:0 0 12px;color:{ENCRE_DOUCE};">{escape(ton.intro)}</p>
          </td>
        </tr>

        <tr>
          <td style="padding:12px 24px 0;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                   border="0" style="width:100%;border-collapse:collapse;
                   border:1px solid {TRAIT};">
              <tr>
                <th align="left" bgcolor="{FOND}" style="padding:9px 20px;font-family:{POLICE};
                    font-size:11px;letter-spacing:.1em;text-transform:uppercase;
                    color:{ENCRE_DOUCE};font-weight:600;border-bottom:1px solid {TRAIT};">
                  Action
                </th>
                <th align="right" bgcolor="{FOND}" style="padding:9px 20px;font-family:{POLICE};
                    font-size:11px;letter-spacing:.1em;text-transform:uppercase;
                    color:{ENCRE_DOUCE};font-weight:600;border-bottom:1px solid {TRAIT};
                    white-space:nowrap;">
                  {escape(ton.colonne_echeance)}
                </th>
              </tr>
              {lignes}
            </table>
          </td>
        </tr>

        <tr>
          <td style="padding:18px 24px 6px;font-family:{POLICE};font-size:14px;
              line-height:1.6;color:{ENCRE_DOUCE};">
            {escape(ton.consigne)}
          </td>
        </tr>
        {bouton}

        <tr>
          <td style="padding:16px 24px 24px;border-top:1px solid {TRAIT};
              font-family:{POLICE};font-size:12px;line-height:1.6;color:{ENCRE_DOUCE};">
            Message automatique du suivi de projets DSI &mdash; merci de ne pas y
            répondre. Pour signaler une erreur sur une action, contacter votre
            responsable de suivi.
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""

    return EmailMessage(
        subject=sujet,
        html=html,
        text=_texte_brut(ton, responsable_name, actions, app_url),
        action_count=len(actions),
    )


def _texte_brut(
    ton: _Ton,
    responsable_name: str,
    actions: list[ActionDigestOut],
    app_url: str | None,
) -> str:
    prenom = (responsable_name or "").split()[0] if responsable_name else ""
    lignes = []
    for action in actions:
        projet = action.project_code or "—"
        pourcent = int(round(action.progress or 0))
        cible = action.deadline.strftime("%d/%m/%Y") if action.deadline else "—"
        lignes.append(
            f"  - [{projet} {action.numero}] {action.description}\n"
            f"    {echeance_lisible(action)} (date cible {cible}) — avancement {pourcent} %"
        )

    corps = [
        f"Bonjour {prenom},".rstrip(),
        "",
        ton.intro,
        "",
        f"{ton.titre.upper()} ({len(actions)})",
        "",
        "\n".join(lignes),
        "",
        ton.consigne,
    ]
    if app_url:
        corps += ["", f"Suivi de projet : {app_url}"]
    corps += [
        "",
        "--",
        "Message automatique du suivi de projets DSI — merci de ne pas y répondre.",
    ]
    return "\n".join(corps)
