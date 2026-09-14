import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.ticket import Ticket


class UserRole(str, enum.Enum):
    CUSTOMER = "customer"
    AGENT = "agent"
    ADMIN = "admin"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), nullable=False, default=UserRole.CUSTOMER
    )

    tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="requester",
        foreign_keys="Ticket.requester_id",
    )
