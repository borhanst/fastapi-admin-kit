"""Pydantic schemas for the notification API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChannelDelivery(BaseModel):
    """Delivery result over a single channel."""

    channel: str
    provider: str = ""
    success: bool
    message_id: str = ""
    error: str | None = None


class NotificationResult(BaseModel):
    """Response for a send request."""

    user_id: str | int | None
    notification_id: int | None = None
    channels: list[ChannelDelivery]


class SendRequest(BaseModel):
    """Request body for ``POST /notifications/send``."""

    user_id: str | int = Field(..., description="Recipient identifier.")
    message: str = Field(..., description="Plain-text notification body.")
    channels: list[str] | None = Field(
        default=None, description="Channels: sms, email, in_app. Defaults to configured channels."
    )
    title: str | None = Field(default=None, description="Notification title / email subject.")
    template: str | None = Field(default=None, description="Named template to render.")
    context: dict[str, Any] | None = Field(default=None, description="Template context.")
    data: dict[str, Any] | None = Field(default=None, description="Structured payload.")
    email: str | None = Field(default=None, description="Recipient email (for email channel).")
    phone: str | None = Field(default=None, description="Recipient phone (for SMS channel).")


class BatchSendRequest(BaseModel):
    """Request body for batch sends."""

    recipients: list[dict[str, Any]] = Field(
        ..., description="Each item: {user_id, email?, phone?}."
    )
    message: str
    channels: list[str] | None = None
    title: str | None = None
    template: str | None = None
    context: dict[str, Any] | None = None
    data: dict[str, Any] | None = None


class NotificationOut(BaseModel):
    """Serialised in-app notification."""

    id: int
    title: str
    body: str | None = None
    channels: list[str] = []
    data: dict[str, Any] | None = None
    status: str = "pending"
    is_read: bool = False
    created_at: str | None = None


class PreferenceUpdate(BaseModel):
    """Request body for ``PUT /notifications/preferences``."""

    channel: str = Field(..., description="Channel name: sms, email, in_app.")
    enabled: bool = True
