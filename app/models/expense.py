from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

class Expense(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id")
    payer_id: int = Field(foreign_key="user.id")
    amount: float
    description: Optional[str] = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ExpenseShare(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    expense_id: int = Field(foreign_key="expense.id")
    user_id: int = Field(foreign_key="user.id")
    share: Optional[float] = None
