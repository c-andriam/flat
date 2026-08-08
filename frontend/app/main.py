import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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
