import os
import secrets
import hashlib
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime, timezone

from database import db, create_document, get_documents
from bson import ObjectId

app = FastAPI(title="SaaS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utilities

def _hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    h = hashlib.sha256()
    h.update((salt + password).encode("utf-8"))
    return h.hexdigest(), salt


def _now():
    return datetime.now(timezone.utc)


# Models
class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=6)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|archived)$")


class ProjectOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: str
    owner_email: EmailStr
    created_at: datetime
    updated_at: datetime


# Auth helpers

def get_user_by_email(email: str) -> Optional[dict]:
    return db["user"].find_one({"email": email}) if db else None


def get_user_by_api_key(api_key: str) -> Optional[dict]:
    return db["user"].find_one({"api_key": api_key}) if db else None


# Routes
@app.get("/")
def root():
    return {"name": "SaaS Starter", "version": "1.0.0"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
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


@app.post("/auth/signup")
def signup(payload: SignupRequest):
    if get_user_by_email(payload.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    password_hash, salt = _hash_password(payload.password)
    api_key = secrets.token_hex(24)
    doc = {
        "name": payload.name,
        "email": str(payload.email),
        "plan": "free",
        "password_hash": password_hash,
        "password_salt": salt,
        "api_key": api_key,
        "created_at": _now(),
        "updated_at": _now(),
    }
    inserted_id = db["user"].insert_one(doc).inserted_id
    return {"id": str(inserted_id), "api_key": api_key, "plan": "free", "name": payload.name, "email": payload.email}


@app.post("/auth/login")
def login(payload: LoginRequest):
    user = get_user_by_email(payload.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    expected_hash, _ = _hash_password(payload.password, user.get("password_salt"))
    if expected_hash != user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "api_key": user.get("api_key"),
        "plan": user.get("plan", "free"),
        "name": user.get("name"),
        "email": user.get("email"),
    }


@app.get("/me")
def me(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    user = get_user_by_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {
        "name": user.get("name"),
        "email": user.get("email"),
        "plan": user.get("plan", "free"),
        "api_key": user.get("api_key"),
    }


# Projects CRUD (authenticated via API key header)

def require_user(x_api_key: Optional[str]) -> dict:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    user = get_user_by_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return user


@app.get("/projects", response_model=List[ProjectOut])
def list_projects(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    user = require_user(x_api_key)
    docs = db["project"].find({"owner_email": user["email"]}).sort("created_at", -1)
    results: List[ProjectOut] = []
    for d in docs:
        results.append(
            ProjectOut(
                id=str(d.get("_id")),
                name=d.get("name"),
                description=d.get("description"),
                status=d.get("status", "active"),
                owner_email=d.get("owner_email"),
                created_at=d.get("created_at", _now()),
                updated_at=d.get("updated_at", _now()),
            )
        )
    return results


@app.post("/projects", response_model=ProjectOut)
def create_project(payload: ProjectCreate, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    user = require_user(x_api_key)
    doc = {
        "owner_email": user["email"],
        "name": payload.name,
        "description": payload.description,
        "status": "active",
        "created_at": _now(),
        "updated_at": _now(),
    }
    inserted_id = db["project"].insert_one(doc).inserted_id
    doc_out = db["project"].find_one({"_id": inserted_id})
    return ProjectOut(
        id=str(doc_out.get("_id")),
        name=doc_out.get("name"),
        description=doc_out.get("description"),
        status=doc_out.get("status", "active"),
        owner_email=doc_out.get("owner_email"),
        created_at=doc_out.get("created_at", _now()),
        updated_at=doc_out.get("updated_at", _now()),
    )


@app.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, payload: ProjectUpdate, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    user = require_user(x_api_key)
    try:
        oid = ObjectId(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid project id")

    proj = db["project"].find_one({"_id": oid, "owner_email": user["email"]})
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    update = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    if not update:
        update = {}
    update["updated_at"] = _now()
    db["project"].update_one({"_id": oid}, {"$set": update})
    new_doc = db["project"].find_one({"_id": oid})
    return ProjectOut(
        id=str(new_doc.get("_id")),
        name=new_doc.get("name"),
        description=new_doc.get("description"),
        status=new_doc.get("status", "active"),
        owner_email=new_doc.get("owner_email"),
        created_at=new_doc.get("created_at", _now()),
        updated_at=new_doc.get("updated_at", _now()),
    )


@app.delete("/projects/{project_id}")
def delete_project(project_id: str, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    user = require_user(x_api_key)
    try:
        oid = ObjectId(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid project id")

    result = db["project"].delete_one({"_id": oid, "owner_email": user["email"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True}


# Public API endpoint secured by API key header
class AnalyzeRequest(BaseModel):
    text: str


@app.post("/api/v1/analyze")
def analyze_text(payload: AnalyzeRequest, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    user = require_user(x_api_key)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text required")
    words = text.split()
    chars = len(text)
    result = {
        "email": user["email"],
        "plan": user.get("plan", "free"),
        "words": len(words),
        "characters": chars,
        "preview": text[:80],
    }
    # Simple usage tracking per user (increment counter)
    db["user"].update_one({"email": user["email"]}, {"$inc": {"usage_count": 1}, "$set": {"updated_at": _now()}})
    return result


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
