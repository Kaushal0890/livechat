from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database.db import Base


class MessageType(str, enum.Enum):
    TEXT = "text"
    FILE = "file"
    IMAGE = "image"
    SYSTEM = "system"


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    room_id = Column(String(100), nullable=False, index=True)
    message = Column(Text, nullable=False)
    message_type = Column(Enum(MessageType), default=MessageType.TEXT)
    file_url = Column(String(500), nullable=True)
    file_name = Column(String(255), nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    is_deleted = Column(Boolean, default=False)
    is_edited = Column(Boolean, default=False)

    # Read receipts - store comma-separated user IDs who have read this message
    read_by = Column(Text, default="")

    # Relationships
    sender = relationship("User", back_populates="messages", foreign_keys=[sender_id])

    def get_read_by_list(self):
        """Return list of user IDs who have read this message."""
        if not self.read_by:
            return []
        return [int(uid) for uid in self.read_by.split(",") if uid]

    def mark_read_by(self, user_id: int):
        """Mark message as read by a user."""
        read_list = self.get_read_by_list()
        if user_id not in read_list:
            read_list.append(user_id)
            self.read_by = ",".join(str(uid) for uid in read_list)

    def __repr__(self):
        return f"<Message(id={self.id}, sender_id={self.sender_id}, room_id='{self.room_id}')>"
