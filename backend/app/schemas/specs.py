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
