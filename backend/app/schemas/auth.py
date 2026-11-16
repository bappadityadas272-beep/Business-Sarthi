from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime


class OtpRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20, examples=["+919800000001"])


class OtpRequested(BaseModel):
    sent: bool = True
    expires_in_seconds: int
    is_mock: bool = True                       # prototype: no SMS is sent
    dev_otp: str | None = None                 # only when DEV_MODE is on


class OtpVerify(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    otp: str = Field(min_length=4, max_length=8)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    is_new_user: bool


class Me(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone: str
    language: str
    created_at: UtcDatetime
