from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import random, string

from app.database.db import get_db
from app.models.user import User
from app.models.private_room import PrivateRoom
from app.routers.auth import get_current_user

router = APIRouter(prefix="/rooms", tags=["Rooms"])


def gen_invite_code(length=8) -> str:
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))


def dm_room_id(user_id_a: int, user_id_b: int) -> str:
    """Deterministic DM room ID for two users."""
    return "dm_" + "_".join(str(x) for x in sorted([user_id_a, user_id_b]))


# ── Search users ──────────────────────────────────────────────────────────────

@router.get("/users/search")
def search_users(q: str, token: str, db: Session = Depends(get_db)):
    """Search users by username."""
    me = get_current_user(token, db)
    if len(q) < 1:
        raise HTTPException(status_code=400, detail="Query too short")
    users = db.query(User).filter(
        User.username.ilike(f"%{q}%"),
        User.id != me.id,
        User.is_active == True
    ).limit(10).all()
    return [{"id": u.id, "username": u.username, "email": u.email, "mobile": u.mobile, "is_admin": u.is_admin} for u in users]


# ── DM ────────────────────────────────────────────────────────────────────────

@router.post("/dm/{username}")
def get_or_create_dm(username: str, token: str, db: Session = Depends(get_db)):
    """Get DM room ID for two users. Creates it if it doesn't exist."""
    me = get_current_user(token, db)
    other = db.query(User).filter(User.username == username).first()
    if not other:
        raise HTTPException(status_code=404, detail="User not found")
    if other.id == me.id:
        raise HTTPException(status_code=400, detail="Can't DM yourself")
    room_id = dm_room_id(me.id, other.id)
    return {
        "room_id": room_id,
        "with_user": {"id": other.id, "username": other.username}
    }


# ── Private Rooms ─────────────────────────────────────────────────────────────

@router.post("/create-private")
def create_private_room(name: str, token: str, db: Session = Depends(get_db)):
    """Create a private room. Returns invite code."""
    me = get_current_user(token, db)
    if not name or len(name.strip()) < 1:
        raise HTTPException(status_code=400, detail="Room name required")
    # Generate unique invite code
    code = gen_invite_code()
    while db.query(PrivateRoom).filter(PrivateRoom.invite_code == code).first():
        code = gen_invite_code()
    room = PrivateRoom(
        name=name.strip().lower().replace(" ", "-"),
        invite_code=code,
        created_by=me.id,
        members=str(me.id)
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return {
        "room_id": f"private_{room.id}",
        "name": room.name,
        "invite_code": room.invite_code,
        "members": [me.username]
    }


@router.post("/join-private")
def join_private_room(invite_code: str, token: str, db: Session = Depends(get_db)):
    """Join a private room using invite code."""
    me = get_current_user(token, db)
    room = db.query(PrivateRoom).filter(PrivateRoom.invite_code == invite_code.upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    room.add_member(me.id)
    db.commit()
    # Get member usernames
    member_ids = room.get_members()
    members = db.query(User).filter(User.id.in_(member_ids)).all()
    return {
        "room_id": f"private_{room.id}",
        "name": room.name,
        "invite_code": room.invite_code,
        "members": [u.username for u in members]
    }


@router.get("/my-private-rooms")
def get_my_private_rooms(token: str, db: Session = Depends(get_db)):
    """Get all private rooms the user is a member of."""
    me = get_current_user(token, db)
    all_rooms = db.query(PrivateRoom).all()
    my_rooms = [r for r in all_rooms if r.is_member(me.id)]
    result = []
    for r in my_rooms:
        member_ids = r.get_members()
        members = db.query(User).filter(User.id.in_(member_ids)).all()
        result.append({
            "room_id": f"private_{r.id}",
            "name": r.name,
            "invite_code": r.invite_code,
            "members": [u.username for u in members],
            "created_by": r.created_by
        })
    return result


@router.get("/my-dms")
def get_my_dms(token: str, db: Session = Depends(get_db)):
    """Get all DM conversations for the user (based on message history)."""
    me = get_current_user(token, db)
    from app.models.message import Message
    from sqlalchemy import or_
    # Find all DM room IDs that involve this user
    msgs = db.query(Message.room_id).filter(
        Message.room_id.like(f"dm_%{me.id}%"),
        Message.is_deleted == False
    ).distinct().all()
    result = []
    seen = set()
    for (room_id,) in msgs:
        if room_id in seen:
            continue
        seen.add(room_id)
        parts = room_id.replace("dm_", "").split("_")
        if len(parts) == 2:
            try:
                other_id = int(parts[0]) if int(parts[1]) == me.id else int(parts[1])
                other = db.query(User).filter(User.id == other_id).first()
                if other:
                    result.append({
                        "room_id": room_id,
                        "with_user": {"id": other.id, "username": other.username}
                    })
            except:
                pass
    return result


@router.post("/exit-private")
def exit_private_room(room_id: str, token: str, db: Session = Depends(get_db)):
    """Exit a private room (remove self from members)."""
    me = get_current_user(token, db)
    db_id = int(room_id.replace("private_", ""))
    room = db.query(PrivateRoom).filter(PrivateRoom.id == db_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    members = room.get_members()
    if me.id in members:
        members.remove(me.id)
        room.members = ",".join(str(x) for x in members)
        db.commit()
    return {"success": True}
