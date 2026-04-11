"""
WidgetConfig Pydantic model for WebChat widget configuration.
All 36 fields with defaults — use WidgetConfig(**stored) to fill missing fields gracefully.
"""
import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator

HEX_RE = re.compile(r'^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')


def _validate_hex(v: str) -> str:
    if not HEX_RE.match(v):
        raise ValueError(f"'{v}' is not a valid hex color")
    return v


class WidgetConfig(BaseModel):
    # ── Branding ──────────────────────────────────────────────────────────────
    business_name: str = Field("", max_length=60)
    tagline: str = Field("", max_length=80)
    avatar_url: str = ""
    primary_color: str = "#4F46E5"
    secondary_color: str = "#FFFFFF"
    text_color: str = "#FFFFFF"
    user_bubble_color: str = "#4F46E5"
    agent_bubble_color: str = "#F3F4F6"

    # ── Layout ────────────────────────────────────────────────────────────────
    position: Literal["bottom-right", "bottom-left", "top-right", "top-left"] = "bottom-right"
    horizontal_offset: int = Field(20, ge=0, le=200)
    vertical_offset: int = Field(20, ge=0, le=200)
    launcher_size: Literal["small", "medium", "large"] = "medium"
    chat_window_width: int = Field(360, ge=280, le=480)
    chat_window_height: int = Field(520, ge=400, le=700)

    # ── Content ───────────────────────────────────────────────────────────────
    welcome_message: str = Field("Hi! How can we help you today?", max_length=200)
    placeholder_text: str = Field("Type a message\u2026", max_length=80)
    send_button_label: str = Field("Send", max_length=20)
    pre_chat_form_enabled: bool = False
    pre_chat_heading: str = Field("Start a conversation", max_length=60)
    pre_chat_subtext: str = Field("Fill in your details to get started.", max_length=120)
    away_message: str = Field(
        "We're currently away. Leave a message and we'll get back to you.",
        max_length=200,
    )
    csat_prompt: str = Field("How would you rate your experience?", max_length=100)

    # ── Behavior ──────────────────────────────────────────────────────────────
    auto_open_delay: int = Field(0, ge=0, le=60)
    show_unread_badge: bool = True
    sound_notifications: bool = False
    persist_session: bool = True
    file_uploads: bool = False
    emoji_picker: bool = True
    typing_indicator: bool = True

    # ── Launcher ──────────────────────────────────────────────────────────────
    launcher_icon: Literal[
        "chat-bubble", "message-circle", "headset", "question-mark", "custom-image"
    ] = "chat-bubble"
    launcher_icon_url: str = ""
    launcher_label: str = Field("", max_length=30)
    launcher_shape: Literal["circle", "rounded-rectangle"] = "circle"
    pulse_animation: bool = False

    # ── Typography ────────────────────────────────────────────────────────────
    font_family: Literal[
        "System Default", "Inter", "Roboto", "Open Sans", "Lato", "Poppins"
    ] = "System Default"
    base_font_size: Literal["12px", "13px", "14px", "15px", "16px"] = "13px"

    @field_validator(
        "primary_color",
        "secondary_color",
        "text_color",
        "user_bubble_color",
        "agent_bubble_color",
        mode="before",
    )
    @classmethod
    def check_hex(cls, v: str) -> str:
        return _validate_hex(v)

    model_config = {"extra": "ignore"}
