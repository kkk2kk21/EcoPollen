from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, select

from ...core.db import get_db
from ...domain.models import User
from ...core.security import hash_password
from .auth import get_current_user, require_roles  # берём проверку ролей из auth.py

router = APIRouter(prefix="/admin", tags=["admin"])
VALID_ROLES = {"student", "scientist", "admin"}


def _serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "created_at": user.created_at,
    }


def _normalize_role(value: str | None) -> str:
    return (value or "student").strip().lower()


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _admin_count(db: Session) -> int:
    return int(
        db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0
    )


def _ensure_not_last_admin(db: Session, target_user: User, next_role: str | None = None, deleting: bool = False) -> None:
    if target_user.role != "admin":
        return

    if not deleting and (next_role is None or next_role == "admin"):
        return

    if _admin_count(db) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Нельзя удалить или понизить роль последнего администратора.",
        )


@router.get("/users", summary="Список пользователей")
def list_users(db: Session = Depends(get_db), _=Depends(require_roles("admin"))):
    users = db.scalars(select(User).order_by(User.created_at.desc(), User.id.desc())).all()
    return [_serialize_user(user) for user in users]

@router.post(
    "/users",
    summary="Создать пользователя",
    description="Создаёт пользователя с указанными логином, паролем и ролью.",
)
def create_user(payload: dict, db: Session = Depends(get_db), _=Depends(require_roles("admin"))):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    role = _normalize_role(payload.get("role"))

    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="role должен быть: student / scientist / admin")
    if "@" not in email or len(password) < 6:
        raise HTTPException(status_code=400, detail="Некорректный email или пароль (минимум 6 символов).")

    exists = db.scalar(select(User).where(User.email == email))
    if exists:
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже существует.")

    user = User(email=email, password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _serialize_user(user)


@router.patch(
    "/users/{user_id}",
    summary="Обновить пользователя",
    description="Позволяет изменить логин, роль и пароль пользователя.",
)
def update_user(
    user_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")

    email_raw = payload.get("email")
    role_raw = payload.get("role")
    password_raw = payload.get("password")
    next_email = _normalize_email(email_raw) if email_raw is not None else None
    next_role = _normalize_role(role_raw) if role_raw is not None else None
    next_password = str(password_raw or "")

    if next_email is None and next_role is None and not next_password:
        raise HTTPException(
            status_code=400,
            detail="Нужно передать новый логин, новую роль и/или новый пароль.",
        )

    if next_email is not None and "@" not in next_email:
        raise HTTPException(status_code=400, detail="Некорректный email.")
    if next_role is not None and next_role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="role должен быть: student / scientist / admin")
    if password_raw is not None and next_password and len(next_password) < 6:
        raise HTTPException(status_code=400, detail="Новый пароль должен быть не короче 6 символов.")

    if next_email is not None and next_email != user.email:
        exists = db.scalar(
            select(User).where(User.email == next_email, User.id != user.id)
        )
        if exists:
            raise HTTPException(status_code=409, detail="Пользователь с таким email уже существует.")

    if next_role is not None and current_user.id == user.id and next_role != "admin":
        raise HTTPException(
            status_code=400,
            detail="Администратор не может снять роль admin сам у себя через эту панель.",
        )

    _ensure_not_last_admin(db, user, next_role=next_role, deleting=False)

    if next_email is not None:
        user.email = next_email
    if next_role is not None:
        user.role = next_role
    if password_raw is not None and next_password:
        user.password_hash = hash_password(next_password)

    db.add(user)
    db.commit()
    db.refresh(user)
    return _serialize_user(user)


@router.delete("/users/{user_id}", summary="Удалить пользователя")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(require_roles("admin")),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")

    if current_user.id == user.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить самого себя.")

    _ensure_not_last_admin(db, user, deleting=True)

    payload = _serialize_user(user)
    db.delete(user)
    db.commit()
    return payload
