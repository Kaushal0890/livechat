from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime

from app.database.db import get_db
from app.models.user import User
from app.models.message import Message
from app.routers.auth import get_current_user

router = APIRouter(prefix="/admin", tags=["Admin"])


def require_admin(token: str, db: Session) -> User:
    user = get_current_user(token, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats(token: str, db: Session = Depends(get_db)):
    admin = require_admin(token, db)
    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active == True).count()
    banned_users = db.query(User).filter(User.is_active == False).count()
    total_messages = db.query(Message).filter(Message.is_deleted == False).count()
    # Messages today
    today = datetime.utcnow().date()
    msgs_today = db.query(Message).filter(
        func.date(Message.timestamp) == today,
        Message.is_deleted == False
    ).count()
    # Rooms with activity
    rooms = db.query(Message.room_id, func.count(Message.id).label('count'))\
        .filter(Message.is_deleted == False)\
        .group_by(Message.room_id)\
        .order_by(func.count(Message.id).desc())\
        .limit(5).all()

    return {
        "total_users": total_users,
        "active_users": active_users,
        "banned_users": banned_users,
        "total_messages": total_messages,
        "messages_today": msgs_today,
        "top_rooms": [{"room": r.room_id, "messages": r.count} for r in rooms]
    }


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users")
def get_all_users(token: str, db: Session = Depends(get_db), search: str = ""):
    require_admin(token, db)
    query = db.query(User)
    if search:
        query = query.filter(
            User.username.ilike(f"%{search}%") | User.email.ilike(f"%{search}%")
        )
    users = query.order_by(User.id).all()
    return [{
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "mobile": u.mobile,
        "is_active": u.is_active,
        "is_admin": u.is_admin,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_seen": u.last_seen.isoformat() if u.last_seen else None,
        "message_count": db.query(Message).filter(Message.sender_id == u.id, Message.is_deleted == False).count()
    } for u in users]


# ── Ban / Unban ───────────────────────────────────────────────────────────────

@router.post("/users/{user_id}/ban")
def ban_user(user_id: int, token: str, db: Session = Depends(get_db)):
    admin = require_admin(token, db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot ban yourself")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot ban another admin")
    user.is_active = False
    db.commit()
    return {"success": True, "message": f"{user.username} has been banned"}


@router.post("/users/{user_id}/unban")
def unban_user(user_id: int, token: str, db: Session = Depends(get_db)):
    require_admin(token, db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    db.commit()
    return {"success": True, "message": f"{user.username} has been unbanned"}


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/users/{user_id}")
def delete_user(user_id: int, token: str, db: Session = Depends(get_db)):
    admin = require_admin(token, db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete another admin")
    # Delete user's messages first
    db.query(Message).filter(Message.sender_id == user_id).delete()
    db.delete(user)
    db.commit()
    return {"success": True, "message": f"{user.username} has been deleted"}


# ── Make Admin / Remove Admin ─────────────────────────────────────────────────

@router.post("/users/{user_id}/make-admin")
def make_admin(user_id: int, token: str, db: Session = Depends(get_db)):
    require_admin(token, db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = True
    db.commit()
    return {"success": True, "message": f"{user.username} is now an admin"}


@router.post("/users/{user_id}/remove-admin")
def remove_admin(user_id: int, token: str, db: Session = Depends(get_db)):
    admin = require_admin(token, db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot remove your own admin")
    user.is_admin = False
    db.commit()
    return {"success": True, "message": f"{user.username} admin removed"}


# ── Delete all messages in a room ─────────────────────────────────────────────

@router.delete("/rooms/{room_id}/messages")
def clear_room_messages(room_id: str, token: str, db: Session = Depends(get_db)):
    require_admin(token, db)
    count = db.query(Message).filter(Message.room_id == room_id).count()
    db.query(Message).filter(Message.room_id == room_id).delete()
    db.commit()
    return {"success": True, "deleted": count}


# ── Create Test User ──────────────────────────────────────────────────────────

@router.post("/create-test-user")
def create_test_user(
    username: str,
    token: str,
    password: str = "test1234",
    email: str = "",
    db: Session = Depends(get_db)
):
    """Admin creates a test user without mobile number or OTP."""
    require_admin(token, db)

    username = username.strip().lower()
    if not username or len(username) < 2:
        raise HTTPException(status_code=400, detail="Username too short (min 2 chars)")
    if len(username) > 30:
        raise HTTPException(status_code=400, detail="Username too long (max 30 chars)")

    # Auto-generate email if not provided
    if not email:
        email = f"{username}@test.nexchat.local"

    # Check duplicates
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail=f"Username '@{username}' already taken")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail=f"Email already in use")

    import bcrypt as _bcrypt
    hashed = _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()

    user = User(
        username=username,
        email=email,
        password=hashed,
        mobile=None,
        is_active=True,
        is_admin=False,
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "success": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "password_plain": password,
            "mobile": None,
        },
        "message": f"Test user @{username} created. Login with username + password (no OTP needed if no mobile)."
    }
