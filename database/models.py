from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class ClinicStatus(str, Enum):
    NEW = "new"
    PARSED = "parsed"
    FAILED = "failed"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class Clinic:
    domain: str
    website: str
    clinic_name: str = ""
    phones: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    telegram: tuple[str, ...] = ()
    whatsapp: tuple[str, ...] = ()
    vk: tuple[str, ...] = ()
    address: str = ""
    parsed_at: str | None = None
    status: ClinicStatus = ClinicStatus.NEW
    error: str = ""
