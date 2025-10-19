import os, logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from sqlmodel import Session, select
from app.db import engine, get_session
from app.models.user import User
from app.models.invite import Invite
from app.models.group import GroupMember

router = APIRouter()
oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)
logging.basicConfig(level=logging.DEBUG)

@router.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for('auth_callback')
    return await oauth.google.authorize_redirect(request, str(redirect_uri))

@router.get("/auth", name="auth_callback")
async def auth(request: Request):
    logging.debug("Starting /auth callback")
    try:
        token = await oauth.google.authorize_access_token(request)
        logging.debug("OAuth token response: %s", token)
    except Exception as e:
        logging.exception("authorize_access_token() failed: %s", e)
        raise HTTPException(status_code=500, detail="OAuth token exchange failed; check server logs")

    # determine userinfo (same robust logic you had)
    userinfo = None
    try:
        if token and isinstance(token, dict) and token.get("userinfo"):
            userinfo = token.get("userinfo")
        elif token and "id_token" in token:
            try:
                userinfo = await oauth.google.parse_id_token(request, token)
            except KeyError:
                resp = await oauth.google.get("userinfo", token=token)
                userinfo = resp.json()
            except Exception:
                resp = await oauth.google.get("userinfo", token=token)
                userinfo = resp.json()
        else:
            resp = await oauth.google.get("userinfo", token=token)
            try:
                userinfo = resp.json()
            except:
                userinfo = await resp.json()
    except Exception as e:
        logging.exception("OAuth2 callback parsing failed. token=%s error=%s", token, e)
        raise HTTPException(status_code=500, detail="Authentication failed; check server logs")

    if not userinfo or not isinstance(userinfo, dict):
        raise HTTPException(status_code=500, detail="Authentication failed: invalid userinfo")

    google_id = userinfo.get("sub") or userinfo.get("id")
    email = userinfo.get("email")
    name = userinfo.get("name") or email or "GoogleUser"

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
        if user.email:
            invites = s.exec(select(Invite).where(Invite.email == user.email)).all()
            for inv in invites:
                exists = s.exec(select(GroupMember).where(GroupMember.group_id==inv.group_id, GroupMember.user_id==user.id)).first()
                if not exists:
                    s.add(GroupMember(group_id=inv.group_id, user_id=user.id))
                s.delete(inv)
            s.commit()
        request.session['user'] = {"id": user.id, "name": user.name, "email": user.email}
    return RedirectResponse(url="/")

@router.get("/logout")
def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url="/")
