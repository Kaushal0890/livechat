from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from jose import JWTError, jwt
import bcrypt, random, os
from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient
from app.database.db import get_db
from app.models.user import User
from app.schemas.message_schema import UserCreate, UserLogin, UserResponse, TokenResponse

load_dotenv()
router = APIRouter(prefix="/auth", tags=["Authentication"])

# ─── Config ────────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "nexchat-default-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# ─── Twilio ──────────────────────────────────────────────────────────────────
TWILIO_SID   = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM  = os.getenv("TWILIO_FROM_NUMBER")

# ─── OTP Store: { key: {otp, expires, data} } ────────────────────────────────
otp_store: dict = {}


# ─── Helpers ───────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    # Truncate to 72 bytes — bcrypt hard limit
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    pwd_bytes = plain.encode("utf-8")[:72]
    return bcrypt.checkpw(pwd_bytes, hashed.encode("utf-8"))


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(token: str, db: Session) -> User:
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


# ─── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    """Register a new user and return JWT token."""
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if payload.mobile:
        # Normalize: keep digits only
        mobile_clean = ''.join(filter(str.isdigit, payload.mobile))
        if db.query(User).filter(User.mobile == mobile_clean).first():
            raise HTTPException(status_code=400, detail="Mobile number already registered")
    else:
        mobile_clean = None

    user = User(
        username=payload.username,
        email=payload.email,
        mobile=mobile_clean,
        password=hash_password(payload.password),
        created_at=datetime.utcnow(),  # Set explicitly — SQLite server_default can be unreliable
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """
    Login with username OR mobile number + password.
    - If login field is all digits → treat as mobile number
    - Otherwise → treat as username
    """
    login_val = payload.login.strip()

    # Try mobile first if input looks like a number, then fallback to username
    is_mobile = login_val.replace('+', '').replace('-', '').replace(' ', '').isdigit()

    user = None
    if is_mobile:
        mobile_clean = ''.join(filter(str.isdigit, login_val))
        user = db.query(User).filter(User.mobile == mobile_clean).first()

    # Fallback: try username (handles case where digits-only username exists, or mobile not registered)
    if not user:
        user = db.query(User).filter(User.username == login_val).first()

    # Also try email
    if not user:
        user = db.query(User).filter(User.email == login_val).first()

    if not user:
        raise HTTPException(status_code=401, detail="No account found with this username, mobile, or email")

    if not verify_password(payload.password, user.password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    user.last_seen = datetime.utcnow()
    # Fix NULL created_at for users registered with old code
    if not user.created_at:
        user.created_at = datetime.utcnow()
    db.commit()

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
def get_me(token: str, db: Session = Depends(get_db)):
    """Get current authenticated user info."""
    user = get_current_user(token, db)
    # Fix NULL created_at for legacy users
    if not user.created_at:
        user.created_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
    return UserResponse.model_validate(user)


@router.post("/update-mobile")
def update_mobile(token: str, mobile: str, db: Session = Depends(get_db)):
    """Update mobile number for logged-in user."""
    user = get_current_user(token, db)
    mobile_clean = ''.join(filter(str.isdigit, mobile))
    if not mobile_clean or len(mobile_clean) < 7:
        raise HTTPException(status_code=400, detail="Invalid mobile number")
    # Check if already taken by another user
    existing = db.query(User).filter(User.mobile == mobile_clean, User.id != user.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Mobile number already registered")
    user.mobile = mobile_clean
    db.commit()
    return {"success": True, "mobile": mobile_clean}


# ─── OTP Helpers ─────────────────────────────────────────────────────────────

def send_sms_otp(mobile: str, otp: str):
    """Send OTP via Twilio SMS."""
    client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
    client.messages.create(
        body=f"Your NexChat OTP is: {otp}. Valid for 5 minutes. Do not share.",
        from_=TWILIO_FROM,
        to=f"+{mobile}"
    )


def generate_otp() -> str:
    return str(random.randint(100000, 999999))


# ─── OTP Routes ──────────────────────────────────────────────────────────────

@router.post("/send-otp")
def send_otp(payload: dict, db: Session = Depends(get_db)):
    """
    Send OTP for login or registration.
    For login:        { "type": "login", "mobile": "9999999999" }
    For registration: { "type": "register", "mobile": "...", "username": "...", "email": "...", "password": "..." }
    """
    otp_type = payload.get("type")
    mobile = ''.join(filter(str.isdigit, payload.get("mobile", "")))

    if not mobile or len(mobile) < 7:
        raise HTTPException(status_code=400, detail="Valid mobile number required")

    if otp_type == "login":
        # Mobile must exist in DB
        user = db.query(User).filter(User.mobile == mobile).first()
        if not user:
            raise HTTPException(status_code=404, detail="No account found with this mobile number")

    elif otp_type == "register":
        # Mobile must NOT already exist
        if db.query(User).filter(User.mobile == mobile).first():
            raise HTTPException(status_code=400, detail="Mobile number already registered")
        if db.query(User).filter(User.username == payload.get("username")).first():
            raise HTTPException(status_code=400, detail="Username already taken")
        if db.query(User).filter(User.email == payload.get("email")).first():
            raise HTTPException(status_code=400, detail="Email already registered")
    else:
        raise HTTPException(status_code=400, detail="type must be 'login' or 'register'")

    otp = generate_otp()
    otp_store[mobile] = {
        "otp": otp,
        "expires": datetime.utcnow() + timedelta(minutes=5),
        "type": otp_type,
        "data": payload  # store full payload for register
    }

    try:
        send_sms_otp(mobile, otp)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send OTP: {str(e)}")

    return {"success": True, "message": f"OTP sent to +{mobile}"}


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp(payload: dict, db: Session = Depends(get_db)):
    """
    Verify OTP and complete login or registration.
    { "mobile": "9999999999", "otp": "123456" }
    """
    mobile = ''.join(filter(str.isdigit, payload.get("mobile", "")))
    otp_input = str(payload.get("otp", "")).strip()

    entry = otp_store.get(mobile)
    if not entry:
        raise HTTPException(status_code=400, detail="OTP not found. Please request a new one.")
    if datetime.utcnow() > entry["expires"]:
        del otp_store[mobile]
        raise HTTPException(status_code=400, detail="OTP expired. Please request a new one.")
    if entry["otp"] != otp_input:
        raise HTTPException(status_code=400, detail="Incorrect OTP")

    # OTP verified — clear it
    stored_type = entry["type"]
    stored_data = entry["data"]
    del otp_store[mobile]

    if stored_type == "login":
        user = db.query(User).filter(User.mobile == mobile).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.last_seen = datetime.utcnow()
        if not user.created_at:
            user.created_at = datetime.utcnow()
        db.commit()

    elif stored_type == "register":
        user = User(
            username=stored_data["username"],
            email=stored_data["email"],
            mobile=mobile,
            password=hash_password(stored_data["password"]),
            created_at=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/login-preflight")
def login_preflight(payload: dict, db: Session = Depends(get_db)):
    """
    Step 1 of login: verify credentials, return mobile for OTP.
    Does NOT return a token — just confirms credentials are correct.
    """
    login_val = payload.get("login", "").strip()
    password = payload.get("password", "")

    user = None
    is_mobile = login_val.replace('+','').replace('-','').replace(' ','').isdigit()
    if is_mobile:
        mobile_clean = ''.join(filter(str.isdigit, login_val))
        user = db.query(User).filter(User.mobile == mobile_clean).first()
    if not user:
        user = db.query(User).filter(User.username == login_val).first()
    if not user:
        user = db.query(User).filter(User.email == login_val).first()
    if not user:
        raise HTTPException(status_code=401, detail="No account found")
    if not verify_password(password, user.password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Return mobile so frontend can send OTP
    # If no mobile, return token directly (fallback)
    if user.mobile:
        return {"has_mobile": True, "mobile": user.mobile}
    else:
        # No mobile — do direct login
        if not user.created_at:
            user.created_at = datetime.utcnow()
        user.last_seen = datetime.utcnow()
        db.commit()
        token = create_access_token({"sub": str(user.id), "username": user.username})
        return {"has_mobile": False, "access_token": token, "token_type": "bearer",
                "user": UserResponse.model_validate(user).model_dump()}
