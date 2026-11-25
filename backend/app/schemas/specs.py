from datetime import datetime

from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.schemas.common import ApiModel


class SpecFileIn(ApiModel):
    path: str = Field(min_length=1)
    content: str


class SpecUploadIn(ApiModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "files": [
                        {
                            "path": "order/create.yaml",
                            "content": (
                                "test_name: 创建订单\n"
                                "stages:\n"
                                "  - name: create\n"
                                "    request:\n"
                                "      url: /orders\n"
                                "      method: POST\n"
                                "      json:\n"
                                "        sku: A-1\n"
                                "        qty: 2\n"
                                "    response:\n"
                                "      status_code: 201"
                            ),
                        }
                    ]
                }
            ]
        },
    )

    files: list[SpecFileIn] = Field(default_factory=list)


class SpecUploadOut(ApiModel):
    saved: list[str]
    root: str


class SpecFileOut(ApiModel):
    path: str
    size: int
    updated_at: datetime
    sha256: str
    case_count: int
    valid: bool
    error: str | None = None


class SpecContentOut(ApiModel):
    path: str
    content: str
    sha256: str
    updated_at: datetime


class SpecContentIn(ApiModel):
    path: str = Field(min_length=1)
    content: str
    expected_sha256: str | None = Field(default=None, max_length=64)


class SpecSaveOut(ApiModel):
    path: str
    sha256: str
    case_count: int


class SpecDeleteOut(ApiModel):
    path: str
    archived_case_count: int
