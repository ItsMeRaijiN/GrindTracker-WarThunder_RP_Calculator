from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginPayload(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(_cls, value: EmailStr) -> str:
        return str(value).strip().casefold()


class RegisterPayload(StrictModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(_cls, value: EmailStr) -> str:
        return str(value).strip().casefold()


class RecentBattle(StrictModel):
    rp: float = Field(ge=0, le=10_000_000)
    minutes: float = Field(default=0, ge=0, le=300)


class ProgressValue(StrictModel):
    rp_current: int = Field(default=0, ge=0, le=100_000_000)
    done: bool = False


class CalcPayload(StrictModel):
    vehicle_id: int = Field(gt=0)
    research_vehicle_id: int | None = Field(default=None, gt=0)
    rp_current: int = Field(default=0, ge=0, le=100_000_000)
    avg_rp_per_battle: float = Field(default=0, ge=0, le=10_000_000)
    avg_battle_minutes: float = Field(default=9, ge=0, le=300)
    recent_battles: list[RecentBattle] = Field(default_factory=list, max_length=5)
    rp_is_base: bool = False
    has_premium: bool = False
    booster_percent: int = Field(default=0, ge=0, le=1000)
    skill_bonus_percent: int = Field(default=0, ge=0, le=500)
    has_talisman: bool = False
    game_mode: Literal["ab", "rb", "sb"] = "rb"
    progress: dict[int, ProgressValue] = Field(default_factory=dict, max_length=5_000)


class ProgressPayload(StrictModel):
    rp_earned: int = Field(default=0, ge=0, le=100_000_000)
    done: bool = False


class ProgressBulkPayload(StrictModel):
    progress: dict[int, ProgressPayload] = Field(default_factory=dict, max_length=5_000)

    @field_validator("progress")
    @classmethod
    def positive_vehicle_ids(_cls, value: dict[int, ProgressPayload]) -> dict[int, ProgressPayload]:
        if any(vehicle_id <= 0 for vehicle_id in value):
            raise ValueError("vehicle IDs must be positive integers")
        return value
