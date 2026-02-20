## Main application entry point

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth.routes import router as auth_router
from app.routes import router as app_router
from app.auth.deps import NotAuthenticated
from app.roadmaps.routes import router as roadmaps_router
from app.generation.routes import router as generation_router

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.get("/",response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, exc: NotAuthenticated):
    # Preserve where the user was going (optional)
    next_url = request.url.path
    return RedirectResponse(url=f"/login?next={next_url}", status_code=303)

app.include_router(auth_router)
app.include_router(app_router)
app.include_router(roadmaps_router)
app.include_router(generation_router)