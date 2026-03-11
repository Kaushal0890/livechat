import os
import aiofiles
import uuid
from pathlib import Path
from fastapi import FastAPI, WebSocket, Query, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional

from app.database.db import get_db, create_tables
from app.routers.auth import router as auth_router, get_current_user
from app.routers.rooms import router as rooms_router
from app.routers.admin import router as admin_router
from app.websocket.chat import handle_websocket, manager
from app.services.chat_service import ChatService
from app.schemas.message_schema import MessageResponse

# ─── App Init ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Real-Time Chat API",
    description="WebSocket-powered chat application with JWT auth, rooms, and advanced features",
    version="1.0.0",
)

# ─── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Uploads Directory ─────────────────────────────────────────────────────────
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# ─── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup():
    create_tables()
    print("✅ Database tables created")
    print("🚀 Real-Time Chat Server is running")

# ─── Include Routers ───────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(rooms_router)
app.include_router(admin_router)

# ─── WebSocket Endpoint ─────────────────────────────────────────────────────────
@app.websocket("/ws/{room_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_id: str,
    token: str = Query(..., description="JWT auth token"),
):
    """
    WebSocket endpoint for real-time chat.
    
    Chat Flow:
        User A sends message
            ↓
        WebSocket API (this endpoint)
            ↓
        Save message in DB
            ↓
        Broadcast message to room
            ↓
        User B receives instantly
    
    Connect: ws://localhost:8000/ws/{room_id}?token=<jwt>
    
    Events you can send:
        { "event": "message",      "data": { "message": "Hello!" } }
        { "event": "typing",       "data": { "is_typing": true } }
        { "event": "read_receipt", "data": { "message_id": 42 } }
        { "event": "edit_message", "data": { "message_id": 42, "message": "Edited!" } }
        { "event": "delete_message","data": { "message_id": 42 } }
        { "event": "mark_room_read","data": {} }
    """
    await handle_websocket(websocket, room_id, token)


# ─── REST Endpoints ─────────────────────────────────────────────────────────────

@app.get("/rooms/{room_id}/messages", response_model=list[MessageResponse])
def get_messages(
    room_id: str,
    limit: int = 50,
    offset: int = 0,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Fetch paginated message history for a room."""
    get_current_user(token, db)  # auth guard
    return ChatService.get_room_messages(db, room_id, limit=limit, offset=offset)


@app.get("/rooms/{room_id}/online")
def get_online_users(room_id: str):
    """Get currently online users in a room."""
    return {
        "room_id": room_id,
        "online_users": manager.get_online_users(room_id),
        "count": manager.get_room_count(room_id),
    }


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Upload a file for sharing in chat (image, PDF, etc.)."""
    user = get_current_user(token, db)

    # Validate size (10MB limit)
    MAX_SIZE = 10 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    # Save with unique name
    ext = Path(file.filename).suffix
    unique_name = f"{uuid.uuid4()}{ext}"
    file_path = UPLOAD_DIR / unique_name

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    file_url = f"/uploads/{unique_name}"
    return {
        "file_url": file_url,
        "file_name": file.filename,
        "size": len(content),
        "uploaded_by": user.username,
    }


@app.get("/health")
def health():
    return {"status": "ok", "active_rooms": len(manager.rooms)}


# ─── Demo UI ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def demo_ui():
    """Serve the chat demo UI."""
    html_path = Path("app/static/index.html")
    if html_path.exists():
        return html_path.read_text()
    return HTMLResponse("""
    <html><body>
    <h2>Chat API is running!</h2>
    <p>Docs: <a href="/docs">/docs</a></p>
    <p>WebSocket: <code>ws://localhost:8000/ws/{room_id}?token=JWT</code></p>
    </body></html>
    """)
