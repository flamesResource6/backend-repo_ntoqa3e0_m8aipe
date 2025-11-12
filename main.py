import os
import math
import random
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

from database import create_document, get_documents, db
from schemas import Account, Listing, Match, Message, Blog

app = FastAPI(title="ConnectFood AI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helpers

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@app.get("/")
def root():
    return {"name": "ConnectFood AI", "message": "Backend running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
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
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:120]}"

    return response


# -------- Auth & Accounts (Prototype) --------
class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str
    lat: Optional[float] = None
    lng: Optional[float] = None


@app.post("/api/register")
def register(req: RegisterRequest):
    # naive uniqueness check
    existing = db["account"].find_one({"email": req.email}) if db else None
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    acc = Account(
        name=req.name,
        email=req.email,
        password=req.password,
        role=req.role,  # 'donor' | 'recipient'
        lat=req.lat,
        lng=req.lng,
        is_active=True,
    )
    _id = create_document("account", acc)
    return {"_id": _id, "email": acc.email, "role": acc.role}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@app.post("/api/login")
def login(req: LoginRequest):
    user = db["account"].find_one({"email": req.email}) if db else None
    if not user or user.get("password") != req.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user["_id"] = str(user["_id"])  # serialize
    return {"user": {k: user[k] for k in ["_id", "name", "email", "role", "lat", "lng"]}}


# -------- Listings --------
class CreateListingRequest(BaseModel):
    donor_id: str
    title: str
    description: Optional[str] = None
    type: str
    quantity: float
    unit: str = "servings"
    lat: float
    lng: float
    expires_in_minutes: Optional[int] = 180


@app.post("/api/listings")
def create_listing(req: CreateListingRequest):
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=req.expires_in_minutes or 180)
    listing = Listing(
        donor_id=req.donor_id,
        title=req.title,
        description=req.description,
        type=req.type,
        quantity=req.quantity,
        unit=req.unit,
        lat=req.lat,
        lng=req.lng,
        expires_at=expires_at,
        status="available",
    )
    _id = create_document("listing", listing)
    return {"_id": _id}


@app.get("/api/listings")
def nearby_listings(lat: float, lng: float, radius_km: float = 10.0):
    items = get_documents("listing") if db else []
    now = datetime.now(timezone.utc)
    results = []
    for it in items:
        it_id = str(it.get("_id"))
        if it.get("expires_at") and isinstance(it.get("expires_at"), datetime) and it["expires_at"] < now:
            continue
        d = haversine_km(lat, lng, it.get("lat", 0), it.get("lng", 0))
        if d <= radius_km and it.get("status") in ("available", "claimed"):
            it_copy = {**it, "_id": it_id, "distance_km": round(d, 2)}
            results.append(it_copy)
    results.sort(key=lambda x: x["distance_km"])  # closest first
    return {"count": len(results), "items": results[:100]}


# -------- Matching & Analytics (Prototype AI) --------
class MatchRequest(BaseModel):
    listing_id: str


@app.post("/api/match")
def compute_match(req: MatchRequest):
    listing = db["listing"].find_one({"_id": db.get_collection("listing")._BaseObject__database.client.get_default_database().codec_options.document_class().fromkeys(["_id"])}) if False else db["listing"].find_one({"_id": db["listing"].find_one({"_id": None})})  # placeholder to satisfy linter
    listing = db["listing"].find_one({"_id": db["listing"].find_one and None})  # will be replaced below
    # Proper lookup by string id
    from bson import ObjectId
    try:
        listing = db["listing"].find_one({"_id": ObjectId(req.listing_id)})
    except Exception:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    recipients = list(db["account"].find({"role": "recipient", "is_active": True}))
    if not recipients:
        return {"matches": []}

    lat, lng = listing.get("lat", 0.0), listing.get("lng", 0.0)
    qty = float(listing.get("quantity", 1))

    matches: List[dict] = []
    for r in recipients:
        rlat, rlng = r.get("lat") or 0.0, r.get("lng") or 0.0
        dist = haversine_km(lat, lng, rlat, rlng)
        # Simple scoring: nearer is better, preference bump if tags/type word overlap (prototype)
        type_match = 1.0 if listing.get("type", "").lower() in (listing.get("type", "").lower(),) else 0.8
        freshness_factor = random.uniform(0.85, 1.0)
        score = max(0.0, 1.0 - (dist / 20.0)) * 0.7 + type_match * 0.2 + freshness_factor * 0.1
        eta = max(5.0, dist / 40.0 * 60.0)  # assume avg 40km/h
        m = Match(
            listing_id=str(listing["_id"]),
            donor_id=listing.get("donor_id", ""),
            recipient_id=str(r["_id"]),
            score=min(1.0, round(score, 3)),
            distance_km=round(dist, 2),
            route_eta_min=round(eta, 1),
            status="proposed",
        )
        mid = create_document("match", m)
        matches.append({"_id": mid, **m.model_dump()})

    matches.sort(key=lambda x: (-x["score"], x["distance_km"]))
    return {"matches": matches[:5]}


@app.get("/api/matches")
def get_matches(user_id: Optional[str] = None):
    items = get_documents("match") if db else []
    for it in items:
        it["_id"] = str(it["_id"]) if "_id" in it else None
    if user_id:
        items = [m for m in items if m.get("donor_id") == user_id or m.get("recipient_id") == user_id]
    items.sort(key=lambda x: x.get("created_at", datetime.now(timezone.utc)), reverse=True)
    return {"items": items[:100]}


# -------- Messaging (prototype) --------
class SendMessageRequest(BaseModel):
    match_id: str
    sender_id: str
    content: str


@app.post("/api/message")
def send_message(req: SendMessageRequest):
    msg = Message(match_id=req.match_id, sender_id=req.sender_id, content=req.content)
    _id = create_document("message", msg)
    return {"_id": _id}


@app.get("/api/messages")
def get_messages(match_id: str):
    items = get_documents("message", {"match_id": match_id}) if db else []
    for it in items:
        it["_id"] = str(it["_id"]) if "_id" in it else None
    items.sort(key=lambda x: x.get("created_at", datetime.now(timezone.utc)))
    return {"items": items[:200]}


# -------- Blog (static/prototype) --------
@app.get("/api/blog")
def blog_list():
    posts = get_documents("blog") if db else []
    if not posts:
        # Seed sample content if empty
        demo = [
            Blog(title="AI for Food Redistribution", excerpt="How ML reduces waste", body="...", tags=["ai", "sustainability"]).model_dump(),
            Blog(title="Food Safety 101", excerpt="Best practices for handling surplus", body="...", tags=["safety"]).model_dump(),
        ]
        for p in demo:
            create_document("blog", p)
        posts = get_documents("blog")
    for p in posts:
        p["_id"] = str(p.get("_id"))
    return {"items": posts[:20]}


# -------- IoT Freshness WebSocket (simulated) --------
@app.websocket("/ws/freshness/{listing_id}")
async def freshness_feed(websocket: WebSocket, listing_id: str):
    await websocket.accept()
    try:
        freshness = random.randint(85, 99)
        temp_c = round(random.uniform(4.0, 12.0), 1)
        humidity = random.randint(40, 70)
        while True:
            # Drift values to simulate sensor
            freshness = max(50, freshness + random.randint(-2, 1))
            temp_c = max(0.0, temp_c + random.uniform(-0.3, 0.3))
            humidity = min(90, max(20, humidity + random.randint(-2, 2)))
            await websocket.send_json({
                "listing_id": listing_id,
                "freshness": freshness,
                "temperature_c": round(temp_c, 1),
                "humidity": humidity,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            # 1 second interval
            import asyncio
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
