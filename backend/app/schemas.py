import pycountry
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateCampaign(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    geo_code: str
    offer_id: int = Field(gt=0)
    domain_id: int = Field(gt=0)
    group_id: int = Field(gt=0)
    traffic_source_id: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        if not value.strip():
            raise ValueError("Введите название кампании")
        return value.strip()

    @field_validator("geo_code")
    @classmethod
    def country(cls, value):
        value = value.strip().upper()
        if not pycountry.countries.get(alpha_2=value):
            raise ValueError("Укажите двухбуквенный код существующей страны")
        return value


class Revision(StrictModel):
    expected_revision: int = Field(ge=1)


class AddOffer(Revision):
    offer_id: int = Field(gt=0)


class PinOffer(Revision):
    pinned: bool
    share: int | None = Field(default=None, ge=0, le=100, strict=True)


class ImportCampaign(StrictModel):
    remote_id: int = Field(gt=0)


class Login(StrictModel):
    password: str
