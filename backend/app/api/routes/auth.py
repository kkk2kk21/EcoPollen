from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import select

from ...core.db import get_db
from ...domain.models import User
from ...core.security import hash_password, verify_password, create_access_token, decode_token
from jose import JWTError

router = APIRouter(prefix="/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

@router.post(
    "/register",
    summary="Регистрация пользователя",
    description="Создаёт нового пользователя с ролью student.",
)
def register(payload: dict, db: Session = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    if "@" not in email or len(password) < 6:
        raise HTTPException(status_code=400, detail="Некорректный email или пароль (минимум 6 символов).")

    exists = db.scalar(select(User).where(User.email == email))
    if exists:
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже существует.")

    user = User(email=email, password_hash=hash_password(password), role="student")
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"id": user.id, "email": user.email, "role": user.role}

@router.post(
    "/login",
    summary="Вход и получение токена",
    description="OAuth2 Password Flow. Передайте логин в поле username, пароль в поле password.",
)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = form_data.username.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль.")

    token = create_access_token({"uid": user.id, "sub": user.email, "role": user.role})
    return {"access_token": token, "token_type": "bearer"}

def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    try:
        payload = decode_token(token)
        uid = payload.get("uid")
        if not uid:
            raise HTTPException(status_code=401, detail="Токен без uid.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Неверный токен.")

    user = db.get(User, uid)
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден.")
    return user

def require_roles(*roles: str):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Недостаточно прав. Нужно: {', '.join(roles)}"
            )
        return user
    return _dep

@router.post(
    "/change-password",
    summary="Изменить свой пароль",
    description="Меняет пароль текущего пользователя после проверки текущего пароля.",
)
def change_password(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    current_password = str(payload.get("current_password") or "")
    new_password = str(payload.get("new_password") or "")

    if not current_password or not new_password:
        raise HTTPException(status_code=400, detail="Нужно передать current_password и new_password.")

    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно.")

    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Новый пароль должен быть не короче 6 символов.")

    if verify_password(new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Новый пароль должен отличаться от текущего.")

    user.password_hash = hash_password(new_password)
    db.add(user)
    db.commit()

    return {"status": "ok"}

@router.get("/me", summary="Текущий пользователь")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "role": user.role}
