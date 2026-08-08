import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import date, datetime, timezone, timedelta
from .services.calendar_service import get_calendar_grid, get_month_name_fr

_MG_TZ = timezone(timedelta(hours=3))

app = FastAPI(title="DSI TRIMETA Frontend")

# Mount static files (Tailwind CSS, images, JS)
app.mount("/static", StaticFiles(directory="/app/app/static"), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="/app/app/templates")


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    Renders the landing page for the DSI Project Management app.
    """
    return templates.TemplateResponse(
        request=request, name="index.html", context={}
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def read_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"active_page": "dashboard"})

@app.get("/projects", response_class=HTMLResponse)
async def read_projects(request: Request):
    return templates.TemplateResponse(request=request, name="projects.html", context={"active_page": "projects"})

@app.get("/actions", response_class=HTMLResponse)
async def read_actions(request: Request):
    return templates.TemplateResponse(request=request, name="actions.html", context={"active_page": "actions"})

@app.get("/agenda", response_class=HTMLResponse)
async def read_agenda(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    today = datetime.now(_MG_TZ).date()
    target_year = year or today.year
    target_month = month or today.month
    
    # Calculate prev/next month
    prev_month = target_month - 1 if target_month > 1 else 12
    prev_year = target_year if target_month > 1 else target_year - 1
    
    next_month = target_month + 1 if target_month < 12 else 1
    next_year = target_year if target_month < 12 else target_year + 1

    weeks = get_calendar_grid(target_year, target_month)
    month_name = get_month_name_fr(target_month)
    
    context = {
        "active_page": "agenda",
        "weeks": weeks,
        "current_year": target_year,
        "current_month": target_month,
        "month_name": month_name,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "today_year": today.year,
        "today_month": today.month
    }
    
    return templates.TemplateResponse(request=request, name="agenda.html", context=context)

@app.get("/responsables", response_class=HTMLResponse)
async def read_responsables(request: Request):
    return templates.TemplateResponse(request=request, name="responsables.html", context={"active_page": "responsables"})

@app.get("/rapports", response_class=HTMLResponse)
async def read_rapports(request: Request):
    return templates.TemplateResponse(request=request, name="rapports.html", context={"active_page": "rapports"})

@app.get("/slots", response_class=HTMLResponse)
async def read_slots(request: Request, week_offset: int = 0):
    now = datetime.now(_MG_TZ)
    today = now.date()
    current_hour = now.hour
    current_minute = now.minute
    
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    sunday = monday + timedelta(days=6)
    
    day_keys = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
    day_names = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
    
    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        days.append({
            "key": day_keys[i],
            "name": day_names[i],
            "date": d.day,
            "month": d.month,
            "iso": d.isoformat(),
            "is_today": d == today,
            "is_past": d < today,
        })
    
    from .services.calendar_service import get_month_name_fr
    mon_month = get_month_name_fr(monday.month)
    sun_month = get_month_name_fr(sunday.month)
    
    if monday.month == sunday.month:
        week_label = f"{monday.day} — {sunday.day} {mon_month} {monday.year}"
    else:
        week_label = f"{monday.day} {mon_month} — {sunday.day} {sun_month} {sunday.year}"
    
    context = {
        "active_page": "slots",
        "days": days,
        "week_label": week_label,
        "week_offset": week_offset,
        "prev_offset": week_offset - 1,
        "next_offset": week_offset + 1,
        "current_hour": current_hour,
        "current_minute": current_minute,
        "today_iso": today.isoformat(),
    }
    return templates.TemplateResponse(request=request, name="slots.html", context=context)
