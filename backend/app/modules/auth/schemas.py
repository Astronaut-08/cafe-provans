"""Схеми входу. Паролі й токени в логи не потрапляють: помилки валідації не повторюють введене значення
(див. core/exceptions.py), а самі моделі ніде не друкуються."""
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.modules.users.schemas import NewPassword, UserRead

# Логін при вході нормалізуємо так само, як при створенні (нижній регістр, без пробілів по краях), але без
# мінімальної довжини: «ab» просто не знайдеться й дасть звичайне «невірний логін або пароль», а не 422.
LoginInput = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50), AfterValidator(str.lower),
]
# Перевіряти пароль при вході можна будь-якої довжини: вимоги до довжини діють лише для НОВИХ паролів
PasswordInput = Annotated[str, Field(min_length=1, max_length=128)]
RefreshTokenInput = Annotated[str, Field(min_length=1, max_length=200)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    login: LoginInput
    password: PasswordInput


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    refresh_token: RefreshTokenInput


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    current_password: PasswordInput
    new_password: NewPassword


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    login: LoginInput


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    login: LoginInput
    code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r'^[0-9]{6}$')]
    new_password: NewPassword


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal['bearer'] = 'bearer'
    expires_in: int  # скільки секунд діє access_token
    # true: пароль тимчасовий. Доки його не замінено (POST /auth/change-password), решта API закрита (403)
    must_change_password: bool
    user: UserRead


class ForgotPasswordResponse(BaseModel):
    # Відповідь завжди однакова, існує такий акаунт чи ні: інакше форму можна використати для вгадування логінів
    detail: str = 'Якщо такий обліковий запис існує і має email, код надіслано'
