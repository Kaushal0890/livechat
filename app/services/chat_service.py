from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime

from app.models.message import Message, MessageType
from app.models.user import User
from app.schemas.message_schema import MessageCreate, MessageResponse


class ChatService:
    """Service layer for all chat-related database operations."""

    @staticmethod
    def save_message(
        db: Session,
        sender_id: int,
        room_id: str,
        message: str,
        message_type: MessageType = MessageType.TEXT,
        file_url: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> Message:
        """Save a new message to the database."""
        msg = Message(
            sender_id=sender_id,
            room_id=room_id,
            message=message,
            message_type=message_type,
            file_url=file_url,
            file_name=file_name,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return msg

    @staticmethod
    def get_room_messages(
        db: Session,
        room_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MessageResponse]:
        """Fetch paginated message history for a room."""
        messages = (
            db.query(Message)
            .filter(Message.room_id == room_id, Message.is_deleted == False)
            .order_by(desc(Message.timestamp))
            .offset(offset)
            .limit(limit)
            .all()
        )
        # Reverse so oldest is first
        messages = list(reversed(messages))
        return [ChatService._to_response(db, msg) for msg in messages]

    @staticmethod
    def mark_message_read(db: Session, message_id: int, user_id: int) -> Optional[Message]:
        """Mark a specific message as read by a user."""
        msg = db.query(Message).filter(Message.id == message_id).first()
        if msg:
            msg.mark_read_by(user_id)
            db.commit()
            db.refresh(msg)
        return msg

    @staticmethod
    def mark_room_read(db: Session, room_id: str, user_id: int) -> int:
        """Mark all messages in a room as read by a user. Returns count updated."""
        messages = (
            db.query(Message)
            .filter(Message.room_id == room_id, Message.sender_id != user_id)
            .all()
        )
        count = 0
        for msg in messages:
            if user_id not in msg.get_read_by_list():
                msg.mark_read_by(user_id)
                count += 1
        if count > 0:
            db.commit()
        return count

    @staticmethod
    def delete_message(db: Session, message_id: int, user_id: int) -> bool:
        """Soft-delete a message (only by sender)."""
        msg = db.query(Message).filter(
            Message.id == message_id,
            Message.sender_id == user_id
        ).first()
        if msg:
            msg.is_deleted = True
            msg.message = "[Message deleted]"
            db.commit()
            return True
        return False

    @staticmethod
    def edit_message(db: Session, message_id: int, user_id: int, new_text: str) -> Optional[Message]:
        """Edit a message (only by sender)."""
        msg = db.query(Message).filter(
            Message.id == message_id,
            Message.sender_id == user_id,
            Message.is_deleted == False
        ).first()
        if msg:
            msg.message = new_text
            msg.is_edited = True
            db.commit()
            db.refresh(msg)
        return msg

    @staticmethod
    def get_user(db: Session, user_id: int) -> Optional[User]:
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def _to_response(db: Session, msg: Message) -> MessageResponse:
        """Convert a Message ORM object to a MessageResponse schema."""
        user = db.query(User).filter(User.id == msg.sender_id).first()
        return MessageResponse(
            id=msg.id,
            sender_id=msg.sender_id,
            sender_username=user.username if user else "Unknown",
            room_id=msg.room_id,
            message=msg.message,
            message_type=msg.message_type,
            file_url=msg.file_url,
            file_name=msg.file_name,
            timestamp=msg.timestamp,
            is_deleted=msg.is_deleted,
            is_edited=msg.is_edited,
            read_by=msg.get_read_by_list(),
        )

    @staticmethod
    def message_to_dict(db: Session, msg: Message) -> dict:
        """Convert message to dict for WebSocket broadcast."""
        response = ChatService._to_response(db, msg)
        return {
            "id": response.id,
            "sender_id": response.sender_id,
            "sender_username": response.sender_username,
            "room_id": response.room_id,
            "message": response.message,
            "message_type": response.message_type,
            "file_url": response.file_url,
            "file_name": response.file_name,
            "timestamp": response.timestamp.isoformat(),
            "is_deleted": response.is_deleted,
            "is_edited": response.is_edited,
            "read_by": response.read_by,
        }
