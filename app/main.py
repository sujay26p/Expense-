import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .db import init_db
from .auth import router as auth_router
from .routes.group import router as group_router
from .routes.expense import router as expense_router

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

app = FastAPI(title="Expense Splitter")

# templates & static 
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.templates = templates
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Session middleware
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SECRET_KEY", "change-me"))

# include routers
app.include_router(auth_router)
app.include_router(group_router)
app.include_router(expense_router)


@app.on_event("startup")
def on_startup():
    init_db()
