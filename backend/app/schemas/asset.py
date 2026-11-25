from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.schemas.common import ApiModel

HttpMethod = Literal[
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "HEAD",
    "OPTIONS",
    "TRACE",
]


class RequirementIn(ApiModel):
    external_id: str = Field(min_length=1)
    title: str = ""
    version: str = ""
    tags: list[str] = Field(default_factory=list)
    owner: str = ""
    content_md: str = ""
    updated_at: datetime | None = None

    @field_validator("updated_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("时间必须带时区，例如 2026-11-24T09:12:33+08:00")
        return value


class RequirementBatchIn(ApiModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "requirements": [
                        {
                            "externalId": "REQ-ORDER-01",
                            "title": "订单创建与库存锁定",
                            "version": "v1.2",
                            "tags": ["order", "inventory"],
                            "owner": "交易产品组",
                            "contentMd": "# 背景\n\n## 验收标准\n\n- 库存不足时返回 409",
                            "updatedAt": "2026-11-25T20:00:00+08:00",
                        }
                    ]
                }
            ]
        },
    )

    requirements: list[RequirementIn] = Field(default_factory=list)


class OperationIn(ApiModel):
    external_id: str = Field(min_length=1)
    method: HttpMethod
    path: str = Field(min_length=1)
    summary: str = ""
    tag: str = ""
    description: str = ""
    params: list[dict] = Field(default_factory=list)
    request_body: list[dict] | None = None
    responses: list[dict] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


class OpenApiDocIn(ApiModel):
    external_id: str = Field(min_length=1)
    title: str = ""
    version: str = ""
    base_url: str = ""
    description: str = ""
    updated_at: datetime | None = None
    operations: list[OperationIn] = Field(default_factory=list)

    @field_validator("updated_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("时间必须带时区，例如 2026-11-24T09:12:33+08:00")
        return value


class OpenApiBatchIn(ApiModel):
    docs: list[OpenApiDocIn] = Field(default_factory=list)


class RequirementIngestOut(BaseModel):
    requirement_count: int


class OpenApiIngestOut(BaseModel):
    doc_count: int
    operation_count: int


class RequirementUpdateIn(ApiModel):
    """需求局部更新。仅修改传入的字段，external_id 不可变更。"""

    title: str | None = None
    version: str | None = None
    tags: list[str] | None = None
    owner: str | None = None
    content_md: str | None = None


class OpenApiImportIn(ApiModel):
    """接收原始 OpenAPI 3.x 文档（JSON 或 YAML 文本），由服务端解析入库。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "externalId": "DOC-ORDER",
                    "title": "订单服务接口",
                    "version": "v1.4.0",
                    "content": (
                        "openapi: 3.0.3\n"
                        "info:\n"
                        "  title: 订单服务\n"
                        "  version: 1.4.0\n"
                        "paths:\n"
                        "  /orders:\n"
                        "    get:\n"
                        "      operationId: listOrders\n"
                        "      summary: 查询订单列表\n"
                        "      responses:\n"
                        "        '200':\n"
                        "          description: ok\n"
                        "    head:\n"
                        "      operationId: probeOrders\n"
                        "      summary: 健康探测\n"
                        "      responses:\n"
                        "        '200':\n"
                        "          description: ok"
                    ),
                }
            ]
        },
    )

    external_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    title: str = ""
    version: str = ""
    base_url: str = ""


class OpenApiDocUpdateIn(ApiModel):
    title: str | None = None
    version: str | None = None
    base_url: str | None = None
    description: str | None = None


class OperationUpdateIn(ApiModel):
    method: HttpMethod | None = None
    path: str | None = None
    summary: str | None = None
    tag: str | None = None
    description: str | None = None
