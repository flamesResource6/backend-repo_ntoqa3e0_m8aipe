"""
Database Schemas for ConnectFood AI

Each Pydantic model maps to a MongoDB collection (lowercased class name).
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal
from datetime import datetime

Role = Literal["donor", "recipient"]

class Account(BaseModel):
    name: str = Field(..., description="Full name or organization name")
    email: EmailStr = Field(..., description="Email address")
    password: str = Field(..., min_length=4, description="Plain password for prototype only")
    role: Role = Field(..., description="User role: donor or recipient")
    phone: Optional[str] = Field(None, description="Contact number")
    lat: Optional[float] = Field(None, ge=-90, le=90, description="Latitude of base location")
    lng: Optional[float] = Field(None, ge=-180, le=180, description="Longitude of base location")
    is_active: bool = True

class Listing(BaseModel):
    donor_id: str = Field(..., description="Account _id of the donor as string")
    title: str = Field(..., description="Short title of food item")
    description: Optional[str] = Field(None, description="Details about the surplus food")
    type: str = Field(..., description="Cuisine or category, e.g., bread, rice, curry")
    quantity: float = Field(..., gt=0, description="Quantity in servings or kg")
    unit: str = Field("servings", description="Unit of quantity")
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    expires_at: Optional[datetime] = Field(None, description="Best-by time for pickup")
    status: Literal["available", "claimed", "completed", "expired"] = "available"

class Match(BaseModel):
    listing_id: str = Field(..., description="Linked listing id")
    donor_id: str = Field(...)
    recipient_id: str = Field(...)
    score: float = Field(0.0, ge=0, le=1, description="Match score 0-1")
    distance_km: float = Field(..., ge=0)
    route_eta_min: float = Field(..., ge=0)
    status: Literal["proposed", "accepted", "rejected", "in_transit", "delivered"] = "proposed"

class Message(BaseModel):
    match_id: str = Field(...)
    sender_id: str = Field(...)
    content: str = Field(...)

class Blog(BaseModel):
    title: str
    excerpt: Optional[str] = None
    body: str
    tags: List[str] = []
