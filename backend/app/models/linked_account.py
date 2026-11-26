"""Linked brokerage accounts and their synchronisation history.

Everything in this module describes a **simulated** broker. No live
brokerage API is connected, and the platform has no credentials for one.
`docs/account-linking.md` states exactly what live access to Zerodha, Upstox
or Groww requires, so the path is real even though the connection is not.

Two rules shape the schema.

Passwords are never requested or stored. There is no password column and
there never will be one. The flow mimics OAuth: the user authorises at the
provider, the provider returns a code, and the platform exchanges it for a
token. A platform that collects brokerage passwords is a platform that can
drain an account, and no amount of care in handling them makes asking for
them acceptable.

Tokens are stored encrypted, never in plaintext. The column holds ciphertext
and is named to say so, because a column called `access_token` invites
someone to log it.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import LinkedAccountStatus, SyncStatus

if TYPE_CHECKING:
    from app.models.user import User


class LinkedAccount(Base):
    """An authorised connection to a (simulated) brokerage account."""

    __tablename__ = "linked_accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # The account number as the provider reports it, which is what the user
    # recognises. Stored masked; the full number is never needed.
    account_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))

    status: Mapped[LinkedAccountStatus] = mapped_column(
        String(24), nullable=False, default=LinkedAccountStatus.ACTIVE
    )

    # Ciphertext, not a token. Named so that nobody logs it by accident.
    access_token_encrypted: Mapped[str | None] = mapped_column(String(1024))
    refresh_token_encrypted: Mapped[str | None] = mapped_column(String(1024))
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Scopes the user granted. A sync that needs a scope it was not given
    # must fail rather than quietly return nothing.
    granted_scopes: Mapped[list | None] = mapped_column(JSONB)

    # Always true for now, and surfaced everywhere this record is shown. A
    # column rather than a constant because the day a real integration
    # exists, the two kinds of record must be distinguishable in the data.
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    last_successful_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_sync_error: Mapped[str | None] = mapped_column(String(512))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="linked_accounts")
    sync_runs: Mapped[list["AccountSyncRun"]] = relationship(
        back_populates="linked_account", cascade="all, delete-orphan",
        order_by="AccountSyncRun.started_at.desc()",
    )

    __table_args__ = (
        # One link per provider account per user. Re-authorising updates the
        # existing row instead of creating a second one, which is what stops
        # a double-link from importing every holding twice.
        UniqueConstraint(
            "user_id", "provider", "account_reference",
            name="uq_linked_accounts_user_provider_account",
        ),
        Index("ix_linked_accounts_user_status", "user_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<LinkedAccount {self.provider}:{self.account_reference} "
            f"user={self.user_id} {self.status}>"
        )


class AccountSyncRun(Base):
    """One attempt to pull holdings and transactions from a linked account.

    Every attempt is recorded, including the failures. A sync history that
    only shows successes cannot answer "when did this last actually work",
    which is the question that matters when a number looks stale.
    """

    __tablename__ = "account_sync_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    linked_account_id: Mapped[int] = mapped_column(
        ForeignKey("linked_accounts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    status: Mapped[SyncStatus] = mapped_column(String(16), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)

    holdings_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    holdings_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    holdings_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transactions_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transactions_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicates_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error_kind: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(String(512))
    details: Mapped[dict | None] = mapped_column(JSONB)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    linked_account: Mapped["LinkedAccount"] = relationship(back_populates="sync_runs")

    def __repr__(self) -> str:
        return f"<AccountSyncRun {self.linked_account_id} {self.status}>"
