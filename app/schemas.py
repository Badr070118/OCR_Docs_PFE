from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: int
    file_name: str
    data: Dict[str, Any]
    raw_text: Optional[str] = None
    llama_output: Optional[str] = None
    date_uploaded: datetime

    class Config:
        from_attributes = True
