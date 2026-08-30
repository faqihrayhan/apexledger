"""Seed currencies

Revision ID: 49ca92cd8b4e
Revises: 5ee169f912ea
Create Date: 2026-08-30

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "49ca92cd8b4e"
down_revision: str | None = "5ee169f912ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ISO 4217 seed data for the currencies table.
CURRENCIES = [
    ("IDR", "Indonesian Rupiah", "Rp", 2),
    ("USD", "US Dollar", "$", 2),
    ("EUR", "Euro", "€", 2),
    ("SGD", "Singapore Dollar", "S$", 2),
    ("JPY", "Japanese Yen", "¥", 0),
]


def upgrade() -> None:
    # One INSERT per statement (asyncpg restriction: single command per execute).
    for code, name, symbol, decimals in CURRENCIES:
        op.execute(
            f"INSERT INTO currencies (code, name, symbol, decimal_places) "
            f"VALUES ('{code}', '{name}', '{symbol}', {decimals}) "
            f"ON CONFLICT (code) DO NOTHING;"
        )


def downgrade() -> None:
    for code, _name, _symbol, _decimals in CURRENCIES:
        op.execute(f"DELETE FROM currencies WHERE code = '{code}';")
