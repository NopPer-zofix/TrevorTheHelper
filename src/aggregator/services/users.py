"""User profiles (language, city, plan). Handlers talk to `UserService`, never to the DB."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aggregator.db.models import User
from aggregator.domain.cities import SELECTABLE_CITIES, City

SUPPORTED_LANGUAGES = ("en", "ru")
DEFAULT_LANGUAGE = "en"
_RUSSIAN_SPEAKING = {"ru", "uk", "be", "kk"}


class UserProfile(BaseModel):
    id: int = 0  # internal primary key (0 = not persisted)
    telegram_id: int
    language: str = DEFAULT_LANGUAGE
    city: City | None = None  # None until the user has chosen one
    plan: str = "private"
    is_allowed: bool = True


def guess_language(telegram_language_code: str | None) -> str:
    code = (telegram_language_code or "").split("-")[0].lower()
    return "ru" if code in _RUSSIAN_SPEAKING else DEFAULT_LANGUAGE


class UserStore(Protocol):
    async def get_or_create(self, telegram_id: int, language: str) -> UserProfile: ...

    async def set_language(self, telegram_id: int, language: str) -> None: ...

    async def set_city(self, telegram_id: int, city: City) -> None: ...


def _profile(row: User) -> UserProfile:
    try:
        city = City(row.city) if row.city else None
    except ValueError:
        city = None
    return UserProfile(
        id=row.id,
        telegram_id=row.telegram_id,
        language=row.language,
        city=city,
        plan=row.plan,
        is_allowed=row.is_allowed,
    )


class DbUserStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_or_create(self, telegram_id: int, language: str) -> UserProfile:
        insert = (
            pg_insert(User)
            .values(telegram_id=telegram_id, language=language)
            .on_conflict_do_nothing(index_elements=[User.telegram_id])
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(insert)  # race-free "create if missing"
            row = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        assert row is not None
        return _profile(row)

    async def set_language(self, telegram_id: int, language: str) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(User).where(User.telegram_id == telegram_id).values(language=language)
            )

    async def set_city(self, telegram_id: int, city: City) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(User).where(User.telegram_id == telegram_id).values(city=city.value)
            )


class InMemoryUserStore:
    """Test double."""

    def __init__(self) -> None:
        self._users: dict[int, UserProfile] = {}

    async def get_or_create(self, telegram_id: int, language: str) -> UserProfile:
        if telegram_id not in self._users:
            self._users[telegram_id] = UserProfile(
                id=len(self._users) + 1, telegram_id=telegram_id, language=language
            )
        return self._users[telegram_id]

    async def set_language(self, telegram_id: int, language: str) -> None:
        user = self._users[telegram_id]
        self._users[telegram_id] = user.model_copy(update={"language": language})

    async def set_city(self, telegram_id: int, city: City) -> None:
        user = self._users[telegram_id]
        self._users[telegram_id] = user.model_copy(update={"city": city})


class UserService:
    def __init__(self, store: UserStore) -> None:
        self._store = store

    async def ensure_user(
        self, telegram_id: int, telegram_language_code: str | None = None
    ) -> UserProfile:
        return await self._store.get_or_create(telegram_id, guess_language(telegram_language_code))

    async def set_language(self, telegram_id: int, language: str) -> UserProfile:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"unsupported language: {language}")
        await self._store.set_language(telegram_id, language)
        return await self._store.get_or_create(telegram_id, language)

    async def set_city(self, telegram_id: int, city: City) -> UserProfile:
        if city not in SELECTABLE_CITIES:
            raise ValueError(f"not a selectable city: {city}")
        await self._store.set_city(telegram_id, city)
        return await self._store.get_or_create(telegram_id, DEFAULT_LANGUAGE)
