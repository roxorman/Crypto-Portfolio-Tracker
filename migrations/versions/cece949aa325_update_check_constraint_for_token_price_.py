"""Update check constraint for token price alerts

Revision ID: cece949aa325
Revises: def04717d8d0
Create Date: 2025-07-09 09:51:23.434760

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cece949aa325'
down_revision: Union[str, None] = 'def04717d8d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('check_token_price_alert_fields', 'alerts', type_='check')
    op.create_check_constraint(
        'check_token_price_alert_fields',
        'alerts',
        sa.text(
            "(alert_type != 'token_price') OR "
            "((source = 'cmc' AND cmc_id IS NOT NULL) OR "
            "(source = 'coingecko' AND token_address IS NOT NULL AND network_id IS NOT NULL))"
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('check_token_price_alert_fields', 'alerts', type_='check')
    # The downgrade path is tricky as we don't know the exact old constraint.
    # For this case, we'll assume the old constraint was the one from the mobula implementation.
    op.create_check_constraint(
        'check_token_price_alert_fields',
        'alerts',
        sa.text("(alert_type != 'token_price') OR (token_mobula_id IS NOT NULL AND token_display_name IS NOT NULL)")
    )
