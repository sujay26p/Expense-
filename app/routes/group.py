from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlmodel import Session, select
from typing import Optional
from app.db import engine
from app.models.group import Group, GroupMember
from app.models.user import User
from app.models.expense import Expense, ExpenseShare
from app.models.invite import Invite
from app.services.balance_service import compute_group_balances
from app.services.settlement_service import suggest_settlements

router = APIRouter()

def require_user(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user

@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    current_user = request.session.get("user")
    with Session(engine) as s:
        groups = s.exec(select(Group)).all()
    return request.app.templates.TemplateResponse("base.html", {"request": request, "groups": groups, "current_user": current_user})

@router.post("/groups/create")
def create_group(name: str = Form(...), current_user = Depends(require_user)):
    with Session(engine) as s:
        g = Group(name=name)
        s.add(g); s.commit(); s.refresh(g)
        gm = GroupMember(group_id=g.id, user_id=current_user["id"])
        s.add(gm); s.commit()
    return RedirectResponse("/", status_code=303)

@router.get("/group/{group_id}", response_class=HTMLResponse)
def view_group(request: Request, group_id: int):
    current_user = request.session.get("user")
    with Session(engine) as s:
        group = s.get(Group, group_id)
        if not group:
            raise HTTPException(404, "Group not found")
        members = s.exec(select(User).join(GroupMember, User.id == GroupMember.user_id).where(GroupMember.group_id == group_id)).all()
        expenses = s.exec(select(Expense).where(Expense.group_id == group_id).order_by(Expense.created_at)).all()
        exp_rows = []
        for e in expenses:
            shares = s.exec(select(ExpenseShare).where(ExpenseShare.expense_id == e.id)).all()
            parts = []
            for sh in shares:
                name = s.get(User, sh.user_id).name
                parts.append({"name": name, "share": sh.share})
            exp_rows.append({
                "id": e.id, "date": e.created_at.strftime("%Y-%m-%d %H:%M"),
                "payer_name": s.get(User, e.payer_id).name, "amount": e.amount,
                "desc": e.description, "participants": parts
            })
        nets = compute_group_balances(s, group_id)
        balances = [{"id": m.id, "name": m.name, "net": nets.get(m.id, 0.0)} for m in members]
        settlements = suggest_settlements(nets, s)
    return request.app.templates.TemplateResponse("group.html", {"request": request, "group": group, "members": members, "expenses": exp_rows, "balances": balances, "settlements": settlements, "current_user": current_user})

import secrets
from fastapi import Form

@router.post("/group/{group_id}/members/add")
def add_member(group_id: int, name: Optional[str] = Form(None), email: Optional[str] = Form(None), current_user = Depends(require_user)):
    with Session(engine) as s:
        if email:
            existing = s.exec(select(User).where(User.email == email)).first()
            if existing:
                exists = s.exec(select(GroupMember).where(GroupMember.group_id==group_id, GroupMember.user_id==existing.id)).first()
                if not exists:
                    gm = GroupMember(group_id=group_id, user_id=existing.id)
                    s.add(gm); s.commit()
                return RedirectResponse(f"/group/{group_id}", status_code=303)
            else:
                token = secrets.token_urlsafe(24)
                inv = Invite(group_id=group_id, email=email, token=token)
                s.add(inv); s.commit()
                return RedirectResponse(f"/group/{group_id}", status_code=303)
        if not name:
            return RedirectResponse(f"/group/{group_id}", status_code=303)
        u = User(name=name)
        s.add(u); s.commit(); s.refresh(u)
        gm = GroupMember(group_id=group_id, user_id=u.id)
        s.add(gm); s.commit()
    return RedirectResponse(f"/group/{group_id}", status_code=303)
