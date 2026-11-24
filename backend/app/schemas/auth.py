from uuid import UUID

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.project import ProjectOut


class LoginIn(ApiModel):
    email: str
    password: str


class ChangePasswordIn(ApiModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(ApiModel):
    id: UUID
    email: str
    display_name: str


class LoginOut(ApiModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    projects: list[ProjectOut]


class MeOut(ApiModel):
    user: UserOut
    projects: list[ProjectOut]
