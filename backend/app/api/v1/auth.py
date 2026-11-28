from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models.identity import AppUser
from app.db.session import get_db
from app.schemas.auth import ChangePasswordIn, LoginIn, LoginOut, MeOut, UserOut
from app.services.projects import list_project_outs

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> LoginOut:
    email = payload.email.strip().lower()
    user = db.scalar(select(AppUser).where(AppUser.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise ApiError(401, "invalid_credentials", "邮箱或密码不正确")
    if user.status != "active":
        raise ApiError(403, "user_disabled", "账号已停用")
    return LoginOut(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
        projects=list_project_outs(db, user.id),
    )


@router.get("/me", response_model=MeOut)
def me(
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeOut:
    return MeOut(user=UserOut.model_validate(user), projects=list_project_outs(db, user.id))


@router.post("/change-password")
def change_password(
    payload: ChangePasswordIn,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not verify_password(payload.current_password, user.password_hash):
        raise ApiError(400, "invalid_password", "当前密码不正确")
    if payload.current_password == payload.new_password:
        raise ApiError(400, "password_unchanged", "新密码不能与当前密码相同")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"status": "ok"}
