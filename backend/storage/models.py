from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ScrapeJob(BaseModel):
    id: int
    source: str
    query: Optional[str] = None
    status: str = "pending"
    total_found: int = 0
    preview_generated: bool = False
    payment_status: str = "unpaid"
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class Lead(BaseModel):
    id: int
    scrape_job_id: Optional[int] = None
    source: str
    business_name: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None
    category: Optional[str] = None
    rating: Optional[float] = None
    raw_data: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class Payment(BaseModel):
    id: int
    scrape_job_id: int
    stripe_session_id: Optional[str] = None
    amount: float
    currency: str = "usd"
    status: str = "pending"
    created_at: datetime
    updated_at: datetime


class PreviewTracking(BaseModel):
    id: int
    scrape_job_id: int
    viewed_at: Optional[datetime] = None
    downloaded: bool = False
    created_at: datetime
    updated_at: datetime


class AdminUser(BaseModel):
    id: int
    username: str
    password_hash: str
    created_at: datetime
    updated_at: datetime


class LeadCreate(BaseModel):
    source: str
    business_name: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None
    category: Optional[str] = None
    rating: Optional[float] = None
    raw_data: Optional[dict[str, Any]] = None


class PaymentCreate(BaseModel):
    scrape_job_id: int
    amount: float
    currency: str = "usd"
    stripe_session_id: Optional[str] = None
