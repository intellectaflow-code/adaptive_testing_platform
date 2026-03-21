from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID


class SettingsOut(BaseModel):
    id: UUID
    user_id: UUID
    email_notifications: bool
    quiz_alerts: bool
    auto_fullscreen: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SettingsUpdate(BaseModel):
    email_notifications: Optional[bool] = None
    quiz_alerts: Optional[bool] = None
    auto_fullscreen: Optional[bool] = None