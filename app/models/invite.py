from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

class Invite(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id")
    email: str
    token: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
