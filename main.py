import os
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from database import db, create_document, get_documents
from schemas import Meeting
from bson import ObjectId

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CreateMeetingRequest(BaseModel):
    host_email: EmailStr
    title: str | None = None
    ttl_minutes: int = 120

class JoinMeetingRequest(BaseModel):
    email: EmailStr
    invite_code: str

@app.get("/")
async def root():
    return {"message": "FortiMeet backend running"}

@app.get("/test")
async def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set"
            response["database_name"] = getattr(db, 'name', 'unknown')
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response

@app.post("/api/meetings")
async def create_meeting(payload: CreateMeetingRequest):
    # Create protected invite that expires
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=payload.ttl_minutes)
    invite_code = ObjectId().__str__()
    data = Meeting(
        title=payload.title,
        host_email=payload.host_email,
        invite_code=invite_code,
        expires_at=expires_at,
        status="active",
        participants=[],
    )
    meeting_id = create_document("meeting", data)
    return {"id": meeting_id, "invite_code": invite_code, "expires_at": expires_at.isoformat()}

@app.post("/api/meetings/join")
async def join_meeting(payload: JoinMeetingRequest):
    # Validate invite and expiration
    docs = get_documents("meeting", {"invite_code": payload.invite_code}, limit=1)
    if not docs:
        raise HTTPException(status_code=404, detail="Invite not found")
    meeting = docs[0]
    if meeting.get("status") != "active":
        raise HTTPException(status_code=400, detail="Meeting not active")
    if meeting.get("expires_at") and meeting["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Invite expired")
    # add participant if not already
    participants = set(meeting.get("participants", []))
    participants.add(str(payload.email))
    db["meeting"].update_one({"_id": meeting["_id"]}, {"$set": {"participants": list(participants), "updated_at": datetime.now(timezone.utc)}})
    return {"ok": True, "meeting_id": str(meeting["_id"]) }

@app.post("/api/meetings/end")
async def end_meeting(invite_code: str):
    docs = get_documents("meeting", {"invite_code": invite_code}, limit=1)
    if not docs:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = docs[0]
    db["meeting"].update_one({"_id": meeting["_id"]}, {"$set": {"status": "ended", "updated_at": datetime.now(timezone.utc)}})
    # Optionally delete at end
    db["meeting"].delete_one({"_id": meeting["_id"]})
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
