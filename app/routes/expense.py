from fastapi import APIRouter, Form, Depends
from fastapi.responses import RedirectResponse
from typing import Optional, List
from sqlmodel import Session, select
from app.db import engine
from app.models.expense import Expense, ExpenseShare
from app.routes.group import require_user

router = APIRouter()

@router.post("/group/{group_id}/expense/add")
def add_expense(
    group_id: int,
    payer_id: int = Form(...),
    amount: float = Form(...),
    description: str = Form(""),
    participants: Optional[List[int]] = Form(None),
    shares: Optional[List[str]] = Form(None),
    current_user = Depends(require_user)
):
    if participants is None:
        participants = [payer_id]
    participants = [int(p) for p in participants]
    parsed_shares = []
    if shares:
        for s in shares:
            if s is None or str(s).strip() == "":
                parsed_shares.append(None)
            else:
                try:
                    parsed_shares.append(float(s))
                except:
                    parsed_shares.append(None)
    else:
        parsed_shares = [None]*len(participants)

    with Session(engine) as s:
        e = Expense(group_id=group_id, payer_id=payer_id, amount=round(amount,2), description=description)
        s.add(e); s.commit(); s.refresh(e)
        for uid, sh in zip(participants, parsed_shares):
            es = ExpenseShare(expense_id=e.id, user_id=uid, share=(None if sh is None else round(float(sh),4)))
            s.add(es)
        s.commit()
    return RedirectResponse(f"/group/{group_id}", status_code=303)

@router.post("/group/{group_id}/expense/{expense_id}/delete")
def delete_expense(group_id: int, expense_id: int, current_user = Depends(require_user)):
    with Session(engine) as s:
        e = s.get(Expense, expense_id)
        if e:
            shares = s.exec(select(ExpenseShare).where(ExpenseShare.expense_id==expense_id)).all()
            for sh in shares:
                s.delete(sh)
            s.delete(e)
            s.commit()
    return RedirectResponse(f"/group/{group_id}", status_code=303)
