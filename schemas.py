from pydantic import BaseModel, EmailStr, AnyHttpUrl, model_validator
from typing import Literal, Optional


class EnrichedLead(BaseModel):
    source_url: Optional[AnyHttpUrl]
    email: EmailStr | None = None
    phone_number: str | None = None
    email_step: Optional[str] = None
    phone_step: Optional[str] = None
    
    @model_validator(mode="after")
    def check_atleast_one(self):
        if not self.email and not self.phone_number:
            raise ValueError("Atleast one of 'email' or 'phone' must be provided.")
        return self
    