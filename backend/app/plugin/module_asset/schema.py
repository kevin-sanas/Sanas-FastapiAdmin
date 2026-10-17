from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from .enums import ApplicationType


class AssetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CategoryCreate(AssetInput):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    parent_id: int | None = Field(default=None, gt=0)
    sort_order: int = 0


class ItemCreate(AssetInput):
    asset_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    category_id: int = Field(gt=0)
    purchase_date: date | None = None
    purchase_amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)


class ApplicationCreate(AssetInput):
    asset_id: int = Field(gt=0)
    application_type: ApplicationType
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=128)


class ApprovalInput(AssetInput):
    review_note: str | None = Field(default=None, max_length=2000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class RepairComplete(AssetInput):
    completion_note: str = Field(min_length=1, max_length=2000)


class HandoverInput(AssetInput):
    note: str = Field(min_length=1, max_length=2000)


class CancelHandoverInput(AssetInput):
    reason: str = Field(min_length=1, max_length=2000)


class RetireInput(AssetInput):
    row_version: int = Field(gt=0)
