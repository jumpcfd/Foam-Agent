from typing import Optional

from pydantic import BaseModel


class RunIn(BaseModel):
    case_id: str
    environment: str  # "local" | "hpc"
    extra: Optional[dict] = None


class RunOut(BaseModel):
    job_id: Optional[str]
    status: str  # "submitted" | "completed" | "failed"
