import json
import asyncio
from typing import Dict, Set, Optional
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.routers.auth import decode_token, get_current_user
from app.services.chat_service import ChatService
from app.models.message import MessageType
from app.database.db import SessionLocal


# ─── Connection Manager ─────────────────────────────────────────────────────────

class ConnectionManager:
    """
    Manages all active WebSocket connections.
    
    Structure:
        rooms: { room_id: { user_id: WebSocket } }
        typing: { room_id: set(username) }
        user_rooms: { user_id: set(room_id) }
    """

    def __init__(self):
        self.rooms: Dict[str, Dict[int, WebSocket]] = {}
        self.typing: Dict[str, Set[str]] = {}
        self.user_info: Dict[int, dict] = {}  # user_id -> {username, ...}

    async def connect(self, websocket: WebSocket, room_id: str, user_id: int, username: str):
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {}
            self.typing[room_id] = set()
        self.rooms[room_id][user_id] = websocket
        self.user_info[user_id] = {"username": username, "user_id": user_id}

        # Notify others in the room
        await self.broadcast_to_room(room_id, {
            "event": "user_joined",
            "data": {
                "user_id": user_id,
                "username": username,
                "online_users": self.get_online_users(room_id),
            }
        }, exclude_user=user_id)

    def disconnect(self, room_id: str, user_id: int):
        if room_id in self.rooms:
            self.rooms[room_id].pop(user_id, None)
            # Clean up typing status
            if room_id in self.typing:
                username = self.user_info.get(user_id, {}).get("username", "")
                self.typing[room_id].discard(username)
            # Clean empty rooms
            if not self.rooms[room_id]:
                del self.rooms[room_id]
                self.typing.pop(room_id, None)

    def get_online_users(self, room_id: str) -> list:
        if room_id not in self.rooms:
            return []
        return [
            self.user_info.get(uid, {}).get("username", str(uid))
            for uid in self.rooms[room_id].keys()
        ]

    def get_room_count(self, room_id: str) -> int:
        return len(self.rooms.get(room_id, {}))

    async def send_personal(self, websocket: WebSocket, data: dict):
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    async def broadcast_to_room(self, room_id: str, data: dict, exclude_user: Optional[int] = None):
        if room_id not in self.rooms:
            return
        dead = []
        for uid, ws in self.rooms[room_id].items():
            if uid == exclude_user:
                continue
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.rooms[room_id].pop(uid, None)

    async def broadcast_to_all_in_room(self, room_id: str, data: dict):
        await self.broadcast_to_room(room_id, data, exclude_user=None)


# Global singleton
manager = ConnectionManager()


# ─── WebSocket Event Handler ────────────────────────────────────────────────────

async def handle_websocket(websocket: WebSocket, room_id: str, token: str):
    """
    Main WebSocket handler.
    
    Chat Flow:
        User A sends message
            → WebSocket API receives event
            → Save message in DB
            → Broadcast to all users in room
            → User B receives instantly
    """
    db: Session = SessionLocal()
    user = None

    try:
        # ── Authenticate via JWT token ──────────────────────────────────────
        try:
            user = get_current_user(token, db)
        except Exception:
            await websocket.accept()
            await websocket.send_json({"event": "error", "data": {"detail": "Unauthorized"}})
            await websocket.close(code=4001)
            return

        # ── Connect user to room ────────────────────────────────────────────
        # Auth check for private rooms and DMs
        if room_id.startswith("private_"):
            from app.models.private_room import PrivateRoom
            room_db_id = int(room_id.replace("private_", ""))
            pr = db.query(PrivateRoom).filter(PrivateRoom.id == room_db_id).first()
            if not pr or not pr.is_member(user.id):
                await websocket.accept()
                await websocket.send_json({"event": "error", "data": {"detail": "Not a member of this room"}})
                await websocket.close(code=4003)
                return
        elif room_id.startswith("dm_"):
            parts = room_id.replace("dm_", "").split("_")
            if len(parts) == 2:
                allowed_ids = [int(p) for p in parts]
                if user.id not in allowed_ids:
                    await websocket.accept()
                    await websocket.send_json({"event": "error", "data": {"detail": "Not authorized for this DM"}})
                    await websocket.close(code=4003)
                    return

        await manager.connect(websocket, room_id, user.id, user.username)

        # ── Send message history on join ────────────────────────────────────
        history = ChatService.get_room_messages(db, room_id, limit=50)
        await manager.send_personal(websocket, {
            "event": "history",
            "data": {
                "messages": [msg.model_dump(mode="json") for msg in history],
                "room_id": room_id,
                "online_users": manager.get_online_users(room_id),
            }
        })

        # ── Listen for incoming events ──────────────────────────────────────
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send_personal(websocket, {
                    "event": "error",
                    "data": {"detail": "Invalid JSON"}
                })
                continue

            event = payload.get("event", "")
            data = payload.get("data", {})

            # ── EVENT: Send message ─────────────────────────────────────────
            if event == "message":
                text = data.get("message", "").strip()
                if not text:
                    continue

                msg_type = MessageType(data.get("message_type", "text"))
                file_url = data.get("file_url")
                file_name = data.get("file_name")

                # Save to DB
                saved_msg = ChatService.save_message(
                    db=db,
                    sender_id=user.id,
                    room_id=room_id,
                    message=text,
                    message_type=msg_type,
                    file_url=file_url,
                    file_name=file_name,
                )

                # Broadcast to all users in room (including sender)
                broadcast_data = ChatService.message_to_dict(db, saved_msg)
                await manager.broadcast_to_all_in_room(room_id, {
                    "event": "message",
                    "data": broadcast_data
                })

            # ── EVENT: Typing indicator ─────────────────────────────────────
            elif event == "typing":
                is_typing = data.get("is_typing", True)
                typing_set = manager.typing.get(room_id, set())

                if is_typing:
                    typing_set.add(user.username)
                else:
                    typing_set.discard(user.username)

                manager.typing[room_id] = typing_set

                await manager.broadcast_to_room(room_id, {
                    "event": "typing",
                    "data": {
                        "username": user.username,
                        "is_typing": is_typing,
                        "typing_users": list(typing_set),
                    }
                }, exclude_user=user.id)

            # ── EVENT: Read receipt ─────────────────────────────────────────
            elif event == "read_receipt":
                message_id = data.get("message_id")
                if message_id:
                    ChatService.mark_message_read(db, message_id, user.id)
                    await manager.broadcast_to_room(room_id, {
                        "event": "read_receipt",
                        "data": {
                            "message_id": message_id,
                            "user_id": user.id,
                            "username": user.username,
                        }
                    })

            # ── EVENT: Mark room as read ────────────────────────────────────
            elif event == "mark_room_read":
                count = ChatService.mark_room_read(db, room_id, user.id)
                await manager.send_personal(websocket, {
                    "event": "room_marked_read",
                    "data": {"room_id": room_id, "messages_updated": count}
                })

            # ── EVENT: Delete message ───────────────────────────────────────
            elif event == "delete_message":
                message_id = data.get("message_id")
                if message_id and ChatService.delete_message(db, message_id, user.id):
                    await manager.broadcast_to_all_in_room(room_id, {
                        "event": "message_deleted",
                        "data": {"message_id": message_id, "room_id": room_id}
                    })

            # ── EVENT: Edit message ─────────────────────────────────────────
            elif event == "edit_message":
                message_id = data.get("message_id")
                new_text = data.get("message", "").strip()
                if message_id and new_text:
                    edited = ChatService.edit_message(db, message_id, user.id, new_text)
                    if edited:
                        await manager.broadcast_to_all_in_room(room_id, {
                            "event": "message_edited",
                            "data": ChatService.message_to_dict(db, edited)
                        })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await manager.send_personal(websocket, {
                "event": "error",
                "data": {"detail": str(e)}
            })
        except Exception:
            pass
    finally:
        if user:
            manager.disconnect(room_id, user.id)
            # Notify room of departure
            await manager.broadcast_to_room(room_id, {
                "event": "user_left",
                "data": {
                    "user_id": user.id,
                    "username": user.username,
                    "online_users": manager.get_online_users(room_id),
                }
            })
        db.close()
