# NexChat — Real-Time Chat Application

A production-ready WebSocket chat application built with **FastAPI**, **SQLAlchemy**, and **SQLite**.

---

## 🗂️ Project Structure

```
chat_app/
├── app/
│   ├── main.py                  # FastAPI app, routes, startup
│   ├── websocket/
│   │   └── chat.py              # WebSocket handler + ConnectionManager
│   ├── models/
│   │   ├── user.py              # User SQLAlchemy model
│   │   └── message.py           # Message SQLAlchemy model
│   ├── schemas/
│   │   └── message_schema.py    # Pydantic schemas
│   ├── database/
│   │   └── db.py                # SQLAlchemy engine, session, Base
│   ├── routers/
│   │   └── auth.py              # JWT auth (register/login/me)
│   ├── services/
│   │   └── chat_service.py      # DB operations business logic
│   └── static/
│       └── index.html           # Built-in chat UI
├── requirements.txt
└── README.md
```

---

## 🗄️ Database Schema (SQLAlchemy + SQLite)

### `users` table
| Column     | Type        | Description              |
|------------|-------------|--------------------------|
| id         | Integer PK  | Auto-incremented ID       |
| username   | String(50)  | Unique username           |
| email      | String(100) | Unique email              |
| password   | String(255) | Bcrypt hashed password    |
| is_active  | Boolean     | Account active status     |
| created_at | DateTime    | Registration timestamp    |
| last_seen  | DateTime    | Last login time           |

### `messages` table
| Column       | Type        | Description                          |
|--------------|-------------|--------------------------------------|
| id           | Integer PK  | Auto-incremented ID                   |
| sender_id    | Integer FK  | References users.id                   |
| room_id      | String(100) | Chat room identifier                  |
| message      | Text        | Message content                       |
| message_type | Enum        | text / file / image / system         |
| file_url     | String      | URL for shared files                  |
| file_name    | String      | Original filename                     |
| timestamp    | DateTime    | Message creation time (auto)          |
| is_deleted   | Boolean     | Soft delete flag                      |
| is_edited    | Boolean     | Edit flag                             |
| read_by      | Text        | Comma-separated user IDs (receipts)   |

---

## 🔄 Chat Flow Architecture

```
User A sends message
        ↓
WebSocket API  (ws://host/ws/{room_id}?token=JWT)
        ↓
Authenticate JWT token
        ↓
Save message in DB (SQLAlchemy → SQLite)
        ↓
Broadcast message to all users in room
        ↓
User B receives instantly via WebSocket
```

---

## 🚀 Running the Server

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
cd chat_app
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open your browser at: **http://localhost:8000**

API Docs: **http://localhost:8000/docs**

---

## 🔌 WebSocket API

**Connect:** `ws://localhost:8000/ws/{room_id}?token=<JWT>`

### Events you can **send**:

| Event             | Data                                              |
|-------------------|---------------------------------------------------|
| `message`         | `{ message, message_type?, file_url?, file_name? }` |
| `typing`          | `{ is_typing: true/false }`                        |
| `read_receipt`    | `{ message_id: 42 }`                               |
| `mark_room_read`  | `{}`                                              |
| `edit_message`    | `{ message_id: 42, message: "new text" }`          |
| `delete_message`  | `{ message_id: 42 }`                               |

### Events you **receive**:

| Event            | Description                            |
|------------------|----------------------------------------|
| `history`        | Last 50 messages + online users        |
| `message`        | New message broadcast                  |
| `typing`         | Who is typing in the room              |
| `read_receipt`   | Message read by a user                 |
| `user_joined`    | Someone joined the room                |
| `user_left`      | Someone left the room                  |
| `message_edited` | A message was edited                   |
| `message_deleted`| A message was soft-deleted             |
| `error`          | Error event with detail                |

---

## 🔐 REST API Endpoints

| Method | Path                        | Description                  |
|--------|-----------------------------|------------------------------|
| POST   | `/auth/register`            | Register new user + get JWT  |
| POST   | `/auth/login`               | Login + get JWT              |
| GET    | `/auth/me?token=`           | Get current user info        |
| GET    | `/rooms/{id}/messages`      | Paginated message history    |
| GET    | `/rooms/{id}/online`        | Online users in room         |
| POST   | `/upload?token=`            | Upload file (max 10MB)       |
| GET    | `/health`                   | Server health check          |

---

## ✨ Advanced Features

- **JWT Authentication** — All WebSocket & REST endpoints are protected
- **Chat Rooms** — Multiple named rooms with isolated member tracking
- **Message Storage** — All messages persisted in SQLite via SQLAlchemy
- **Typing Status** — Real-time typing indicators per room
- **File Sharing** — Upload & share images and files (10MB limit)
- **Read Receipts** — Track who has read each message
- **Message Editing** — Edit your own messages (broadcasts to room)
- **Soft Delete** — Delete messages (marked deleted, not removed from DB)
- **Message History** — Last 50 messages loaded on room join
- **Online Users** — Live online user list per room
- **Auto Read** — Messages auto-marked as read when received
# livechat
# livechat
# livechat
# livechat
# livechat
