from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.db import Base


class PrivateRoom(Base):
    __tablename__ = "private_rooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    invite_code = Column(String(20), unique=True, nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    # Comma-separated user IDs
    members = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def get_members(self):
        if not self.members:
            return []
        return [int(x) for x in self.members.split(",") if x]

    def add_member(self, user_id: int):
        members = self.get_members()
        if user_id not in members:
            members.append(user_id)
            self.members = ",".join(str(x) for x in members)

    def is_member(self, user_id: int) -> bool:
        return user_id in self.get_members()
