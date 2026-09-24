"""Pydantic request/response schemas (shape validation only).

Rational-string *value* validation lives in :mod:`app.grid` so the same
strict rules apply to the pure core and the API layer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EventIn(BaseModel):
    """One sounding (``note``) or silent (``rest``) event of a voice."""

    kind: Literal["note", "rest"] = Field(
        description="'note' for a sounding event, 'rest' for silence"
    )
    duration: str = Field(
        description="Positive rational string, e.g. '1', '1/4', '3/8'",
        examples=["1/4"],
    )


class VoiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, examples=["soprano"])
    events: list[EventIn] = Field(min_length=1)


class MeasureIn(BaseModel):
    """A measure submission: target duration plus at least two voices."""

    target_duration: str = Field(
        description="Positive rational string the voices must add up to",
        examples=["4/4"],
    )
    voices: list[VoiceIn] = Field(min_length=2)

    @field_validator("voices")
    @classmethod
    def voice_names_must_be_unique(cls, voices: list[VoiceIn]) -> list[VoiceIn]:
        names = [voice.name for voice in voices]
        if len(names) != len(set(names)):
            raise ValueError("voice names must be unique within a measure")
        return voices
