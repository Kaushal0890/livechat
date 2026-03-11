from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from app.models.message import MessageType


# ─── Message Schemas ───────────────────────────────────────────────────────────

class MessageBase(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    room_id: str = Field(..., min_length=1, max_length=100)
    message_type: MessageType = MessageType.TEXT


class MessageCreate(MessageBase):
    file_url: Optional[str] = None
    file_name: Optional[str] = None


class MessageResponse(BaseModel):
    id: int
    sender_id: int
    sender_username: str
    room_id: str
    message: str
    message_type: MessageType
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    timestamp: datetime
    is_deleted: bool
    is_edited: bool
    read_by: List[int] = []

    class Config:
        from_attributes = True


# ─── WebSocket Event Schemas ────────────────────────────────────────────────────

class WSEventType(str):
    MESSAGE = "message"
    TYPING = "typing"
    STOP_TYPING = "stop_typing"
    READ_RECEIPT = "read_receipt"
    JOIN_ROOM = "join_room"
    LEAVE_ROOM = "leave_room"
    USER_ONLINE = "user_online"
    USER_OFFLINE = "user_offline"
    ERROR = "error"
    FILE_SHARE = "file_share"


class WebSocketMessage(BaseModel):
    event: str
    data: dict = {}


class TypingEvent(BaseModel):
    room_id: str
    username: str
    is_typing: bool


class ReadReceiptEvent(BaseModel):
    message_id: int
    room_id: str
    user_id: int
    username: str


# ─── Room Schemas ───────────────────────────────────────────────────────────────

class RoomInfo(BaseModel):
    room_id: str
    name: str
    member_count: int
    online_users: List[str] = []


# ─── User Schemas ───────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=100)
    mobile: Optional[str] = Field(None, max_length=20)  # allow +country prefix
    password: str = Field(..., min_length=6)


class UserLogin(BaseModel):
    # login field accepts: username OR mobile number
    login: str = Field(..., description="Username or mobile number")
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    mobile: Optional[str] = None
    is_active: bool
    is_admin: bool = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
