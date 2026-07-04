from __future__ import annotations

from datetime import datetime
from sqlalchemy import Integer, String, ForeignKey, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="New Chat")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to messages
    messages: Mapped[list[Message]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Message.timestamp.asc()"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True
    )
    role: Mapped[str] = mapped_column(String(50))  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Rich metadata fields for assistant responses
    intent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    companies: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON serialized
    metrics: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON serialized
    financial_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON serialized
    documents: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON serialized
    news: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON serialized
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON serialized
    warnings: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON serialized

    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="messages")
