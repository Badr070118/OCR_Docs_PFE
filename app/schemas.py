from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: int
    file_name: str
    data: Dict[str, Any]
    raw_text: Optional[str] = None
    llama_output: Optional[str] = None
    date_uploaded: datetime

    class Config:
        from_attributes = True


class DocumentAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)


class DocumentAskResponse(BaseModel):
    answer: str
    found: bool
    fields_used: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float
