import uuid

from sqlalchemy import ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# JSONB on PostgreSQL (production), portable JSON elsewhere (tests).
StateJSON = JSON().with_variant(JSONB(), "postgresql")


class ScenarioModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scenarios"

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(nullable=False, default="general", server_default="general")
    status: Mapped[str] = mapped_column(nullable=False, default="created", server_default="created")

    inputs: Mapped[list["ScenarioInputModel"]] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
    )
    reality_states: Mapped[list["RealityStateModel"]] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
    )


class ScenarioInputModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scenario_inputs"

    scenario_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    input_type: Mapped[str] = mapped_column(nullable=False, default="initial", server_default="initial")

    scenario: Mapped["ScenarioModel"] = relationship(back_populates="inputs")


class RealityStateModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "reality_states"

    scenario_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    state_json: Mapped[dict] = mapped_column(StateJSON, nullable=False, default=dict)

    scenario: Mapped["ScenarioModel"] = relationship(back_populates="reality_states")
