import os
from sqlmodel import SQLModel, create_engine, Session
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DB_FILE = os.path.join(BASE_DIR, "db.sqlite")
engine = create_engine(f"sqlite:///{DB_FILE}", echo=False, connect_args={"check_same_thread": False})

def init_db():
    # Import models so SQLModel.metadata includes them
    import app.models.user, app.models.group, app.models.expense, app.models.invite
    SQLModel.metadata.create_all(engine)

def get_session():
    return Session(engine)
