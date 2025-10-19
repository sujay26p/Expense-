# app.py
import os
from datetime import datetime
from typing import Optional, List, Dict

from dotenv import load_dotenv
load_dotenv()  # loads .env

from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth

from sqlmodel import Field, SQLModel, create_engine, Session, select

# ----------------------
# Database models
# ----------------------
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: Optional[str] = None
    google_id: Optional[str] = None

class Group(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str

class GroupMember(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id")
    user_id: int = Field(foreign_key="user.id")

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

class Invite(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id")
    email: str
    token: Optional[str] = None  # optional invite token / link
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ----------------------
# App, templates & static
# ----------------------
app = FastAPI()
BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Session middleware for simple server-side session (signed cookie)
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SECRET_KEY", "change-me"))

# ----------------------
# OAuth (Authlib) setup
# ----------------------
oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

# ----------------------
# Database engine
# ----------------------
DB_FILE = os.path.join(BASE_DIR, "db.sqlite")
engine = create_engine(f"sqlite:///{DB_FILE}", echo=False, connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)

# ----------------------
# Utility: require logged-in user
# ----------------------
def require_user(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user

# ----------------------
# Core logic functions
# ----------------------
def compute_group_balances(session: Session, group_id: int) -> Dict[int, float]:
    stmt_users = select(User).join(GroupMember, User.id == GroupMember.user_id).where(GroupMember.group_id == group_id)
    users = session.exec(stmt_users).all()
    nets = {u.id: 0.0 for u in users}

    stmt_exp = select(Expense).where(Expense.group_id == group_id).order_by(Expense.created_at)
    expenses = session.exec(stmt_exp).all()
    for e in expenses:
        shares = session.exec(select(ExpenseShare).where(ExpenseShare.expense_id == e.id)).all()
        if not shares:
            continue

        # Custom-share handling (weights) or equal split
        if any(s.share is not None for s in shares):
            weights = [float(s.share) if s.share is not None and float(s.share) > 0 else 0.0 for s in shares]
            total_weight = sum(weights)
            if total_weight <= 0:
                per_amounts = {s.user_id: round(e.amount / len(shares),2) for s in shares}
            else:
                per_amounts = {}
                for s,w in zip(shares, weights):
                    per_amounts[s.user_id] = round(e.amount * (w / total_weight), 2)
                allocated = round(sum(per_amounts.values()),2)
                remainder = round(e.amount - allocated, 2)
                if remainder != 0:
                    per_amounts[e.payer_id] = per_amounts.get(e.payer_id,0.0) + remainder
        else:
            per_share = round(e.amount / len(shares), 2)
            per_amounts = {s.user_id: per_share for s in shares}
            allocated = round(per_share * len(shares), 2)
            remainder = round(e.amount - allocated, 2)
            if remainder != 0:
                per_amounts[e.payer_id] = per_amounts.get(e.payer_id,0.0) + remainder

        for uid, amt in per_amounts.items():
            nets.setdefault(uid, 0.0)
            nets[uid] -= amt
        nets.setdefault(e.payer_id, 0.0)
        nets[e.payer_id] += e.amount

    for k in nets:
        nets[k] = round(nets[k], 2)
    return nets

def suggest_settlements(nets: Dict[int, float], session: Session) -> List[Dict]:
    creditors = [(uid, amt) for uid, amt in nets.items() if amt > 0.005]
    debtors = [(uid, -amt) for uid, amt in nets.items() if amt < -0.005]
    creditors.sort(key=lambda x: x[1], reverse=True)
    debtors.sort(key=lambda x: x[1], reverse=True)
    i = j = 0
    settlements = []
    while i < len(debtors) and j < len(creditors):
        debtor_id, debt_amt = debtors[i]
        creditor_id, cred_amt = creditors[j]
        pay = round(min(debt_amt, cred_amt), 2)
        if pay > 0:
            settlements.append({"from": debtor_id, "to": creditor_id, "amount": pay})
        debt_amt -= pay
        cred_amt -= pay
        if debt_amt <= 0.005:
            i += 1
        else:
            debtors[i] = (debtor_id, debt_amt)
        if cred_amt <= 0.005:
            j += 1
        else:
            creditors[j] = (creditor_id, cred_amt)
    for s in settlements:
        s["from_name"] = session.get(User, s["from"]).name
        s["to_name"] = session.get(User, s["to"]).name
    return settlements

# ----------------------
# Routes: Auth
# ----------------------
@app.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for('auth')  # callback
    return await oauth.google.authorize_redirect(request, str(redirect_uri))

import logging
logging.basicConfig(level=logging.DEBUG)  # put near top of file (once)

@app.get("/auth")
async def auth(request: Request):
    """
    Robust OAuth callback handler:
    - Uses token['userinfo'] if present (Authlib sometimes already supplies it)
    - Falls back to parse_id_token() if possible
    - If parse_id_token raises KeyError or other issues, calls userinfo endpoint using access_token
    """
    import logging
    logging.debug("Starting /auth callback")

    # 1) Exchange code -> token
    try:
        token = await oauth.google.authorize_access_token(request)
        logging.debug("OAuth token response: %s", token)
    except Exception as e:
        logging.exception("authorize_access_token() failed: %s", e)
        raise HTTPException(status_code=500, detail="OAuth token exchange failed; check server logs")

    userinfo = None
    try:
        # Fast path: some Authlib versions include 'userinfo' inside token already
        if token and isinstance(token, dict) and token.get("userinfo"):
            logging.debug("Using token['userinfo']")
            userinfo = token.get("userinfo")
        # Next try: parse id_token (OIDC) if available
        elif token and "id_token" in token:
            logging.debug("Attempting parse_id_token()")
            try:
                userinfo = await oauth.google.parse_id_token(request, token)
                logging.debug("Parsed id_token -> userinfo: %s", userinfo)
            except KeyError as ke:
                # This is the behavior you hit: parse_id_token may look up request['id_token'] in some authlib versions
                logging.warning("parse_id_token() raised KeyError (fall back to userinfo endpoint). %s", ke)
                resp = await oauth.google.get("userinfo", token=token)
                userinfo = resp.json()
                logging.debug("userinfo endpoint returned: %s", userinfo)
            except Exception as ex_parse:
                logging.exception("parse_id_token() failed with unexpected error: %s", ex_parse)
                # fallback to userinfo endpoint
                resp = await oauth.google.get("userinfo", token=token)
                userinfo = resp.json()
                logging.debug("userinfo endpoint returned: %s", userinfo)
        else:
            # No id_token and no token['userinfo'] — call the userinfo endpoint using access_token
            logging.debug("No id_token or token['userinfo']; calling userinfo endpoint")
            resp = await oauth.google.get("userinfo", token=token)
            # prefer resp.json(); handle different response shapes defensively
            try:
                userinfo = resp.json()
            except Exception:
                # older authlib/httpx versions may need await resp.json()
                try:
                    userinfo = await resp.json()
                except Exception as ex_json:
                    logging.exception("Failed to decode userinfo response: %s", ex_json)
                    raise HTTPException(status_code=500, detail="Failed to retrieve userinfo; see server logs")
            logging.debug("userinfo endpoint returned: %s", userinfo)
    except Exception as e:
        logging.exception("OAuth2 callback parsing failed. token=%s error=%s", token, e)
        raise HTTPException(status_code=500, detail="Authentication failed; check server logs")

    # guard: ensure userinfo is dict-like
    if not userinfo or not isinstance(userinfo, dict):
        logging.exception("userinfo missing or not dict: %s", userinfo)
        raise HTTPException(status_code=500, detail="Authentication failed: invalid userinfo")

    # Normalize fields
    google_id = userinfo.get("sub") or userinfo.get("id")
    email = userinfo.get("email")
    name = userinfo.get("name") or email or "GoogleUser"

    # Save / find local user and put basic info in session
    with Session(engine) as s:
        user = None
        if google_id:
            user = s.exec(select(User).where(User.google_id == google_id)).first()
        if not user and email:
            user = s.exec(select(User).where(User.email == email)).first()
        if not user:
            user = User(name=name, email=email, google_id=google_id)
            s.add(user); s.commit(); s.refresh(user)
        else:
            changed = False
            if google_id and user.google_id != google_id:
                user.google_id = google_id; changed = True
            if email and user.email != email:
                user.email = email; changed = True
            if user.name != name:
                user.name = name; changed = True
            if changed:
                s.add(user); s.commit()
        # set session
        if user.email:
            invites = s.exec(select(Invite).where(Invite.email == user.email)).all()
            for inv in invites:
                # add GroupMember if not already present
                exists = s.exec(select(GroupMember).where(GroupMember.group_id==inv.group_id, GroupMember.user_id==user.id)).first()
                if not exists:
                    s.add(GroupMember(group_id=inv.group_id, user_id=user.id))
                # remove the invite (or mark accepted)
                s.delete(inv)
            s.commit()


        request.session['user'] = {"id": user.id, "name": user.name, "email": user.email}

    return RedirectResponse(url="/")

@app.get("/logout")
def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url="/")

# ----------------------
# Routes: UI & CRUD (require login for mutations)
# ----------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    current_user = request.session.get("user")
    with Session(engine) as s:
        groups = s.exec(select(Group)).all()
    return templates.TemplateResponse("base.html", {"request": request, "groups": groups, "current_user": current_user})

@app.post("/groups/create")
def create_group(name: str = Form(...), current_user = Depends(require_user)):
    with Session(engine) as s:
        g = Group(name=name)
        s.add(g); s.commit(); s.refresh(g)
        # auto-add creator as member
        gm = GroupMember(group_id=g.id, user_id=current_user["id"])
        s.add(gm); s.commit()
    return RedirectResponse("/", status_code=303)

@app.get("/group/{group_id}", response_class=HTMLResponse)
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
    return templates.TemplateResponse("group.html", {"request": request, "group": group, "members": members, "expenses": exp_rows, "balances": balances, "settlements": settlements, "current_user": current_user})

import secrets
from urllib.parse import urlencode

@app.post("/group/{group_id}/members/add")
def add_member(group_id: int, name: Optional[str] = Form(None), email: Optional[str] = Form(None), current_user = Depends(require_user)):
    with Session(engine) as s:
        # If email provided, try to find existing user by email
        if email:
            existing = s.exec(select(User).where(User.email == email)).first()
            if existing:
                # create membership if not already
                exists = s.exec(select(GroupMember).where(GroupMember.group_id==group_id, GroupMember.user_id==existing.id)).first()
                if not exists:
                    gm = GroupMember(group_id=group_id, user_id=existing.id)
                    s.add(gm); s.commit()
                # optionally return success message
                return RedirectResponse(f"/group/{group_id}", status_code=303)
            else:
                # create an Invite
                token = secrets.token_urlsafe(24)  # optional invite token for links
                inv = Invite(group_id=group_id, email=email, token=token)
                s.add(inv); s.commit()
                # Optionally: send email (see notes below). For now we just create invite.
                return RedirectResponse(f"/group/{group_id}", status_code=303)
        # If no email, fallback to name-only member (existing behavior)
        if not name:
            # nothing provided — redirect back
            return RedirectResponse(f"/group/{group_id}", status_code=303)
        # Create new user by name (ad-hoc)
        u = User(name=name)
        s.add(u); s.commit(); s.refresh(u)
        gm = GroupMember(group_id=group_id, user_id=u.id)
        s.add(gm); s.commit()
    return RedirectResponse(f"/group/{group_id}", status_code=303)


@app.post("/group/{group_id}/expense/add")
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

@app.post("/group/{group_id}/expense/{expense_id}/delete")
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

# (Optional) reset endpoint for dev only
@app.get("/reset-all")
def reset_all():
    with Session(engine) as s:
        s.exec("DELETE FROM expenseshare")
        s.exec("DELETE FROM expense")
        s.exec("DELETE FROM groupmember")
        s.exec("DELETE FROM user")
        s.exec("DELETE FROM 'group'")
        s.commit()
    return {"ok": True}
