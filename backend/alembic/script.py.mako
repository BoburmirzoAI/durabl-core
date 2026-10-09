"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Yaratilgan: ${create_date}
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

# Alembic identifikatorlari
revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """Sxemani oldinga siljitadi."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """O'zgarishni orqaga qaytaradi."""
    ${downgrades if downgrades else "pass"}
