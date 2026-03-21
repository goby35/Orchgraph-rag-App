from __future__ import annotations

from enum import Enum
import re
import unicodedata
from typing import Any
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class DegreeLevel(str, Enum):
    BACHELOR = "BACHELOR"
    MASTER = "MASTER"
    PHD = "PHD"
    OTHER = "OTHER"


_TECH_ALIASES: dict[str, str] = {
    "reactjs": "react",
    "react.js": "react",
    "vuejs": "vue",
    "vue.js": "vue",
    "nodejs": "node.js",
    "node js": "node.js",
    "postgresql": "postgres",
    "k8s": "kubernetes",
    "tf": "terraform",
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "golang": "go",
    "springboot": "spring boot",
    "spring-boot": "spring boot",
    "aws lambda": "aws",
    "gcp": "google cloud",
}


def _normalize_entity(name: str) -> str:
    """Normalize entity names to reduce duplicated graph nodes."""
    normalized = re.sub(r"\s+", " ", str(name).strip().lower())
    return _TECH_ALIASES.get(normalized, normalized)


_DEGREE_VI_MAP: dict[str, str] = {
    "ky su": "BACHELOR",
    "cu nhan": "BACHELOR",
    "thac si": "MASTER",
    "tien si": "PHD",
    "phd": "PHD",
    "bachelor": "BACHELOR",
    "master": "MASTER",
}


def _strip_vietnamese_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return without_marks.replace("đ", "d").replace("Đ", "D")


def _normalize_degree(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    key = _strip_vietnamese_accents(key)
    key = re.sub(r"\s+", " ", key)
    return _DEGREE_VI_MAP.get(key, "OTHER")


class ExperienceExtraction(BaseModel):
    organization_name: Optional[str] = Field(default=None)
    project_name: str = ""
    role: str = ""
    tech_stack: list[str] = Field(default_factory=list)

    @field_validator("organization_name", "project_name", "role", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("tech_stack", mode="before")
    @classmethod
    def _normalize_tech_stack(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [_normalize_entity(item) for item in value if isinstance(item, str) and item.strip()]


class EducationExtraction(BaseModel):
    degree: DegreeLevel = DegreeLevel.OTHER
    major: str = ""
    school: str = ""
    year: Optional[int] = Field(default=None)

    @field_validator("degree", mode="before")
    @classmethod
    def _normalize_degree_value(cls, value: Any) -> str:
        if isinstance(value, DegreeLevel):
            return value.value
        return _normalize_degree(value)

    @field_validator("major", "school", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class ContactLinks(BaseModel):
    email: str = ""
    phone: str = ""
    github: str = ""
    linkedin: str = ""


class InterviewQA(BaseModel):
    question: str = ""
    answer: str = ""
    org: str = ""


class PrivateData(BaseModel):
    contact: ContactLinks = Field(default_factory=ContactLinks)
    salary_expectation: str = ""
    project_technical_secrets: str = ""
    interview_questions_history: list[InterviewQA] = Field(default_factory=list)
    blacklist_orgs: list[str] = Field(default_factory=list)
    evidence_links: list[str] = Field(default_factory=list)
    additional_information: dict[str, Any] = Field(default_factory=dict)
    @field_validator("additional_information", mode="before")
    @classmethod
    def coerce_additional_info(cls, v: Any) -> dict:
        """
        OpenAI strict mode trả về additional_information dạng
        list[{"key":..., "value":...}] — convert sang dict.
        """
        if isinstance(v, dict):
            return v
        if isinstance(v, list):
            result = {}
            for item in v:
                if isinstance(item, dict):
                    k   = item.get("key") or item.get("name") or item.get("k")
                    val = item.get("value") or item.get("v") or item.get("val")
                    if k:
                        result[str(k)] = val
            return result
        return {}


class PublicDataGraph(BaseModel):
    full_name: str = ""
    professional_summary: str = ""
    is_available: bool = Field(default=False)
    skills: list[str] = Field(default_factory=list)
    certificates: list[str] = Field(default_factory=list)
    cultural_tags: list[str] = Field(default_factory=list)
    education: list[EducationExtraction] = Field(default_factory=list)
    experience: list[ExperienceExtraction] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _map_legacy_availability(cls, value: Any) -> Any:
        # Backward compatibility: map legacy `availability` string into `is_available`.
        if not isinstance(value, dict):
            return value
        if "is_available" in value:
            return value

        availability = str(value.get("availability", "")).strip().lower()
        available_markers = {
            "open_for_offers",
            "open for offers",
            "available",
            "immediate",
            "dang tim viec",
            "đang tìm việc",
        }
        value["is_available"] = availability in available_markers
        return value

    @field_validator("skills", mode="before")
    @classmethod
    def _normalize_skills(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [_normalize_entity(item) for item in value if isinstance(item, str) and item.strip()]


class RecruitmentNode(BaseModel):
    personnel_id: str | None = None
    org_id: str | None = None
    public_data: PublicDataGraph = Field(default_factory=PublicDataGraph)
    private_data: PrivateData = Field(default_factory=PrivateData)

    @property
    def neo4j_id(self) -> str:
        return self.personnel_id or self.org_id or ""

    @property
    def role(self) -> str:
        return "PERSONNEL" if self.personnel_id else "ORGANIZATION"

    @classmethod
    def from_pipeline_payload(cls, payload: dict[str, Any]) -> "RecruitmentNode":
        """Accept either extraction payload ({record_type, data}) or direct data payload."""
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        return cls.model_validate(data)
