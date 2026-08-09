import calendar
from datetime import date, datetime, timezone, timedelta
import holidays

# Madagascar timezone (UTC+3)
MG_TZ = timezone(timedelta(hours=3))

# Translation map from Malagasy to French for holidays package
MG_TO_FR = {
    "Taom-baovao": "Jour de l'An",
    "Fetin'ny vehivavy": "Journée de la Femme",
    "Fetin'ny mahery fo": "Fête des Martyrs",
    "Fetin'ny paska": "Pâques",
    "Alatsinain'ny paska": "Lundi de Pâques",
    "Fetin'ny asa": "Fête du Travail",
    "Fiakaran'ny Jesosy kristy tany an-danitra": "Ascension",
    "Pentekosta": "Pentecôte",
    "Alatsinain'ny pentekosta": "Lundi de Pentecôte",
    "Fetin'ny reny": "Fête des Mères",
    "Fetin'ny ray": "Fête des Pères",
    "Fetin'ny fahaleovantena": "Fête de l'Indépendance",
    "Fiakaran'ny Masina Maria tany an-danitra": "Assomption",
    "Fetin'ny olo-masina": "Toussaint",
    "Fetin'ny Repoblika": "Fête de la République",
    "Fetin'ny noely": "Noël"
}

def get_calendar_grid(year: int, month: int):
    cal = calendar.Calendar(firstweekday=0)
    today = datetime.now(MG_TZ).date()
    mg_holidays = holidays.country_holidays('MG', years=[year, year-1, year+1])
    
    grid = []
    weeks = cal.monthdatescalendar(year, month)
    
    # Force exactly 6 weeks (42 days) for stable UI height
    while len(weeks) < 6:
        last_day = weeks[-1][-1]
        next_week = [last_day + timedelta(days=i) for i in range(1, 8)]
        weeks.append(next_week)
    
    for week in weeks:
        week_data = []
        for d in week:
            is_current = (d.month == month)
            is_today = (d == today)
            day_holidays = []
            if d in mg_holidays:
                mg_name = mg_holidays.get(d)
                fr_name = MG_TO_FR.get(mg_name, mg_name)
                day_holidays.append(fr_name)
                
            week_data.append({
                "date": d.isoformat(),
                "day": d.day,
                "is_current_month": is_current,
                "is_today": is_today,
                "holidays": day_holidays
            })
        grid.append(week_data)
        
    return grid

def get_month_name_fr(month: int) -> str:
    months = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
    return months[month - 1]
