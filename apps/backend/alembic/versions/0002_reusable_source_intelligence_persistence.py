"""Reusable source intelligence persistence

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-02 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'amazon_product_evidence_bundles',
        sa.Column('bundle_id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('bundle', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['run_id'],
            ['shopping_runs.run_id'],
            name=op.f('fk_amazon_product_evidence_bundles_run_id_shopping_runs'),
        ),
        sa.PrimaryKeyConstraint(
            'bundle_id',
            name=op.f('pk_amazon_product_evidence_bundles'),
        ),
    )
    op.create_index(
        'ix_amazon_product_evidence_bundles_run_id',
        'amazon_product_evidence_bundles',
        ['run_id'],
        unique=False,
    )
    op.create_table(
        'community_discussion_evidence_bundles',
        sa.Column('bundle_id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('bundle', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['run_id'],
            ['shopping_runs.run_id'],
            name=op.f('fk_community_discussion_evidence_bundles_run_id_shopping_runs'),
        ),
        sa.PrimaryKeyConstraint(
            'bundle_id',
            name=op.f('pk_community_discussion_evidence_bundles'),
        ),
    )
    op.create_index(
        'ix_community_discussion_evidence_bundles_run_id',
        'community_discussion_evidence_bundles',
        ['run_id'],
        unique=False,
    )
    op.create_table(
        'ikea_store_evidence_bundles',
        sa.Column('bundle_id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('bundle', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['run_id'],
            ['shopping_runs.run_id'],
            name=op.f('fk_ikea_store_evidence_bundles_run_id_shopping_runs'),
        ),
        sa.PrimaryKeyConstraint('bundle_id', name=op.f('pk_ikea_store_evidence_bundles')),
    )
    op.create_index(
        'ix_ikea_store_evidence_bundles_run_id',
        'ikea_store_evidence_bundles',
        ['run_id'],
        unique=False,
    )
    op.create_table(
        'reusable_source_evidence_gaps',
        sa.Column('gap_id', sa.String(length=36), nullable=False),
        sa.Column('bundle_id', sa.String(length=36), nullable=False),
        sa.Column('bundle_kind', sa.String(length=60), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('source_id', sa.String(length=36), nullable=True),
        sa.Column('capability', sa.String(length=80), nullable=False),
        sa.Column('target_type', sa.String(length=60), nullable=True),
        sa.Column('product_id', sa.String(length=36), nullable=True),
        sa.Column('listing_id', sa.String(length=36), nullable=True),
        sa.Column('candidate_id', sa.String(length=36), nullable=True),
        sa.Column('seller_name', sa.String(length=200), nullable=True),
        sa.Column('review_id', sa.String(length=200), nullable=True),
        sa.Column('region_code', sa.String(length=12), nullable=True),
        sa.Column('source_target_id', sa.String(length=36), nullable=True),
        sa.Column('recommendation_claim_id', sa.String(length=120), nullable=True),
        sa.Column('gap', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['run_id'],
            ['shopping_runs.run_id'],
            name=op.f('fk_reusable_source_evidence_gaps_run_id_shopping_runs'),
        ),
        sa.ForeignKeyConstraint(
            ['source_id'],
            ['source_snapshots.source_id'],
            name=op.f('fk_reusable_source_evidence_gaps_source_id_source_snapshots'),
        ),
        sa.PrimaryKeyConstraint('gap_id', name=op.f('pk_reusable_source_evidence_gaps')),
    )
    op.create_index(
        'ix_reusable_source_evidence_gaps_bundle_id',
        'reusable_source_evidence_gaps',
        ['bundle_id'],
        unique=False,
    )
    op.create_index(
        'ix_reusable_source_evidence_gaps_capability',
        'reusable_source_evidence_gaps',
        ['capability'],
        unique=False,
    )
    op.create_index(
        'ix_reusable_source_evidence_gaps_listing_id',
        'reusable_source_evidence_gaps',
        ['listing_id'],
        unique=False,
    )
    op.create_index(
        'ix_reusable_source_evidence_gaps_product_id',
        'reusable_source_evidence_gaps',
        ['product_id'],
        unique=False,
    )
    op.create_index(
        'ix_reusable_source_evidence_gaps_recommendation_claim_id',
        'reusable_source_evidence_gaps',
        ['recommendation_claim_id'],
        unique=False,
    )
    op.create_index(
        'ix_reusable_source_evidence_gaps_region_code',
        'reusable_source_evidence_gaps',
        ['region_code'],
        unique=False,
    )
    op.create_index(
        'ix_reusable_source_evidence_gaps_review_id',
        'reusable_source_evidence_gaps',
        ['review_id'],
        unique=False,
    )
    op.create_index(
        'ix_reusable_source_evidence_gaps_run_id',
        'reusable_source_evidence_gaps',
        ['run_id'],
        unique=False,
    )
    op.create_index(
        'ix_reusable_source_evidence_gaps_source_id',
        'reusable_source_evidence_gaps',
        ['source_id'],
        unique=False,
    )
    op.create_table(
        'amazon_listing_contexts',
        sa.Column('context_record_id', sa.String(length=36), nullable=False),
        sa.Column('bundle_id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('source_id', sa.String(length=36), nullable=False),
        sa.Column('marketplace_name', sa.String(length=120), nullable=False),
        sa.Column('marketplace_domain', sa.String(length=200), nullable=False),
        sa.Column('marketplace_country_code', sa.String(length=12), nullable=True),
        sa.Column('asin', sa.String(length=20), nullable=True),
        sa.Column('external_listing_id', sa.String(length=200), nullable=True),
        sa.Column('seller_name', sa.String(length=200), nullable=True),
        sa.Column('ships_to_region_code', sa.String(length=12), nullable=True),
        sa.Column('ships_to_region', sa.Boolean(), nullable=True),
        sa.Column('context', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['bundle_id'],
            ['amazon_product_evidence_bundles.bundle_id'],
            name=op.f('fk_amazon_listing_contexts_bundle_id_amazon_product_evidence_bundles'),
        ),
        sa.ForeignKeyConstraint(
            ['run_id'],
            ['shopping_runs.run_id'],
            name=op.f('fk_amazon_listing_contexts_run_id_shopping_runs'),
        ),
        sa.ForeignKeyConstraint(
            ['source_id'],
            ['source_snapshots.source_id'],
            name=op.f('fk_amazon_listing_contexts_source_id_source_snapshots'),
        ),
        sa.PrimaryKeyConstraint(
            'context_record_id',
            name=op.f('pk_amazon_listing_contexts'),
        ),
    )
    op.create_index('ix_amazon_listing_contexts_asin', 'amazon_listing_contexts', ['asin'], unique=False)
    op.create_index('ix_amazon_listing_contexts_bundle_id', 'amazon_listing_contexts', ['bundle_id'], unique=False)
    op.create_index('ix_amazon_listing_contexts_marketplace_domain', 'amazon_listing_contexts', ['marketplace_domain'], unique=False)
    op.create_index('ix_amazon_listing_contexts_run_id', 'amazon_listing_contexts', ['run_id'], unique=False)
    op.create_index('ix_amazon_listing_contexts_seller_name', 'amazon_listing_contexts', ['seller_name'], unique=False)
    op.create_index('ix_amazon_listing_contexts_ships_to_region_code', 'amazon_listing_contexts', ['ships_to_region_code'], unique=False)
    op.create_index('ix_amazon_listing_contexts_source_id', 'amazon_listing_contexts', ['source_id'], unique=False)
    op.create_table(
        'community_discussion_contexts',
        sa.Column('context_record_id', sa.String(length=36), nullable=False),
        sa.Column('bundle_id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('source_id', sa.String(length=36), nullable=False),
        sa.Column('platform', sa.String(length=80), nullable=False),
        sa.Column('community_name', sa.String(length=120), nullable=True),
        sa.Column('thread_id', sa.String(length=200), nullable=True),
        sa.Column('comment_id', sa.String(length=200), nullable=True),
        sa.Column('posted_at', sa.String(length=35), nullable=True),
        sa.Column('context', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['bundle_id'],
            ['community_discussion_evidence_bundles.bundle_id'],
            name=op.f('fk_community_discussion_contexts_bundle_id_community_discussion_evidence_bundles'),
        ),
        sa.ForeignKeyConstraint(
            ['run_id'],
            ['shopping_runs.run_id'],
            name=op.f('fk_community_discussion_contexts_run_id_shopping_runs'),
        ),
        sa.ForeignKeyConstraint(
            ['source_id'],
            ['source_snapshots.source_id'],
            name=op.f('fk_community_discussion_contexts_source_id_source_snapshots'),
        ),
        sa.PrimaryKeyConstraint(
            'context_record_id',
            name=op.f('pk_community_discussion_contexts'),
        ),
    )
    op.create_index('ix_community_discussion_contexts_bundle_id', 'community_discussion_contexts', ['bundle_id'], unique=False)
    op.create_index('ix_community_discussion_contexts_comment_id', 'community_discussion_contexts', ['comment_id'], unique=False)
    op.create_index('ix_community_discussion_contexts_run_id', 'community_discussion_contexts', ['run_id'], unique=False)
    op.create_index('ix_community_discussion_contexts_source_id', 'community_discussion_contexts', ['source_id'], unique=False)
    op.create_index('ix_community_discussion_contexts_thread_id', 'community_discussion_contexts', ['thread_id'], unique=False)
    op.create_table(
        'ikea_store_contexts',
        sa.Column('context_record_id', sa.String(length=36), nullable=False),
        sa.Column('bundle_id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('source_id', sa.String(length=36), nullable=False),
        sa.Column('country_code', sa.String(length=12), nullable=False),
        sa.Column('product_code', sa.String(length=120), nullable=True),
        sa.Column('store_name', sa.String(length=200), nullable=True),
        sa.Column('availability', sa.String(length=40), nullable=False),
        sa.Column('context', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['bundle_id'],
            ['ikea_store_evidence_bundles.bundle_id'],
            name=op.f('fk_ikea_store_contexts_bundle_id_ikea_store_evidence_bundles'),
        ),
        sa.ForeignKeyConstraint(
            ['run_id'],
            ['shopping_runs.run_id'],
            name=op.f('fk_ikea_store_contexts_run_id_shopping_runs'),
        ),
        sa.ForeignKeyConstraint(
            ['source_id'],
            ['source_snapshots.source_id'],
            name=op.f('fk_ikea_store_contexts_source_id_source_snapshots'),
        ),
        sa.PrimaryKeyConstraint('context_record_id', name=op.f('pk_ikea_store_contexts')),
    )
    op.create_index('ix_ikea_store_contexts_availability', 'ikea_store_contexts', ['availability'], unique=False)
    op.create_index('ix_ikea_store_contexts_bundle_id', 'ikea_store_contexts', ['bundle_id'], unique=False)
    op.create_index('ix_ikea_store_contexts_country_code', 'ikea_store_contexts', ['country_code'], unique=False)
    op.create_index('ix_ikea_store_contexts_product_code', 'ikea_store_contexts', ['product_code'], unique=False)
    op.create_index('ix_ikea_store_contexts_run_id', 'ikea_store_contexts', ['run_id'], unique=False)
    op.create_index('ix_ikea_store_contexts_source_id', 'ikea_store_contexts', ['source_id'], unique=False)
    op.create_table(
        'amazon_product_evidence',
        sa.Column('evidence_id', sa.String(length=36), nullable=False),
        sa.Column('bundle_id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('source_id', sa.String(length=36), nullable=False),
        sa.Column('fact_type', sa.String(length=80), nullable=False),
        sa.Column('target_type', sa.String(length=60), nullable=False),
        sa.Column('product_id', sa.String(length=36), nullable=True),
        sa.Column('listing_id', sa.String(length=36), nullable=True),
        sa.Column('candidate_id', sa.String(length=36), nullable=True),
        sa.Column('seller_name', sa.String(length=200), nullable=True),
        sa.Column('review_id', sa.String(length=200), nullable=True),
        sa.Column('region_code', sa.String(length=12), nullable=True),
        sa.Column('source_target_id', sa.String(length=36), nullable=True),
        sa.Column('listing_context_source_id', sa.String(length=36), nullable=True),
        sa.Column('recommendation_claim_id', sa.String(length=120), nullable=True),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['bundle_id'],
            ['amazon_product_evidence_bundles.bundle_id'],
            name=op.f('fk_amazon_product_evidence_bundle_id_amazon_product_evidence_bundles'),
        ),
        sa.ForeignKeyConstraint(
            ['listing_context_source_id'],
            ['source_snapshots.source_id'],
            name=op.f('fk_amazon_product_evidence_listing_context_source_id_source_snapshots'),
        ),
        sa.ForeignKeyConstraint(
            ['run_id'],
            ['shopping_runs.run_id'],
            name=op.f('fk_amazon_product_evidence_run_id_shopping_runs'),
        ),
        sa.ForeignKeyConstraint(
            ['source_id'],
            ['source_snapshots.source_id'],
            name=op.f('fk_amazon_product_evidence_source_id_source_snapshots'),
        ),
        sa.PrimaryKeyConstraint('evidence_id', name=op.f('pk_amazon_product_evidence')),
    )
    op.create_index('ix_amazon_product_evidence_bundle_id', 'amazon_product_evidence', ['bundle_id'], unique=False)
    op.create_index('ix_amazon_product_evidence_candidate_id', 'amazon_product_evidence', ['candidate_id'], unique=False)
    op.create_index('ix_amazon_product_evidence_fact_type', 'amazon_product_evidence', ['fact_type'], unique=False)
    op.create_index('ix_amazon_product_evidence_listing_context_source_id', 'amazon_product_evidence', ['listing_context_source_id'], unique=False)
    op.create_index('ix_amazon_product_evidence_listing_id', 'amazon_product_evidence', ['listing_id'], unique=False)
    op.create_index('ix_amazon_product_evidence_product_id', 'amazon_product_evidence', ['product_id'], unique=False)
    op.create_index('ix_amazon_product_evidence_recommendation_claim_id', 'amazon_product_evidence', ['recommendation_claim_id'], unique=False)
    op.create_index('ix_amazon_product_evidence_region_code', 'amazon_product_evidence', ['region_code'], unique=False)
    op.create_index('ix_amazon_product_evidence_review_id', 'amazon_product_evidence', ['review_id'], unique=False)
    op.create_index('ix_amazon_product_evidence_run_id', 'amazon_product_evidence', ['run_id'], unique=False)
    op.create_index('ix_amazon_product_evidence_seller_name', 'amazon_product_evidence', ['seller_name'], unique=False)
    op.create_index('ix_amazon_product_evidence_source_id', 'amazon_product_evidence', ['source_id'], unique=False)
    op.create_table(
        'community_discussion_evidence',
        sa.Column('evidence_id', sa.String(length=36), nullable=False),
        sa.Column('bundle_id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('source_id', sa.String(length=36), nullable=False),
        sa.Column('target_type', sa.String(length=60), nullable=False),
        sa.Column('product_id', sa.String(length=36), nullable=True),
        sa.Column('listing_id', sa.String(length=36), nullable=True),
        sa.Column('candidate_id', sa.String(length=36), nullable=True),
        sa.Column('seller_name', sa.String(length=200), nullable=True),
        sa.Column('review_id', sa.String(length=200), nullable=True),
        sa.Column('region_code', sa.String(length=12), nullable=True),
        sa.Column('source_target_id', sa.String(length=36), nullable=True),
        sa.Column('recommendation_claim_id', sa.String(length=120), nullable=True),
        sa.Column('recurring_signal', sa.Boolean(), nullable=False),
        sa.Column('qualitative_signal', sa.Boolean(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['bundle_id'],
            ['community_discussion_evidence_bundles.bundle_id'],
            name=op.f('fk_community_discussion_evidence_bundle_id_community_discussion_evidence_bundles'),
        ),
        sa.ForeignKeyConstraint(
            ['run_id'],
            ['shopping_runs.run_id'],
            name=op.f('fk_community_discussion_evidence_run_id_shopping_runs'),
        ),
        sa.ForeignKeyConstraint(
            ['source_id'],
            ['source_snapshots.source_id'],
            name=op.f('fk_community_discussion_evidence_source_id_source_snapshots'),
        ),
        sa.PrimaryKeyConstraint(
            'evidence_id',
            name=op.f('pk_community_discussion_evidence'),
        ),
    )
    op.create_index('ix_community_discussion_evidence_bundle_id', 'community_discussion_evidence', ['bundle_id'], unique=False)
    op.create_index('ix_community_discussion_evidence_candidate_id', 'community_discussion_evidence', ['candidate_id'], unique=False)
    op.create_index('ix_community_discussion_evidence_listing_id', 'community_discussion_evidence', ['listing_id'], unique=False)
    op.create_index('ix_community_discussion_evidence_product_id', 'community_discussion_evidence', ['product_id'], unique=False)
    op.create_index('ix_community_discussion_evidence_recommendation_claim_id', 'community_discussion_evidence', ['recommendation_claim_id'], unique=False)
    op.create_index('ix_community_discussion_evidence_region_code', 'community_discussion_evidence', ['region_code'], unique=False)
    op.create_index('ix_community_discussion_evidence_review_id', 'community_discussion_evidence', ['review_id'], unique=False)
    op.create_index('ix_community_discussion_evidence_run_id', 'community_discussion_evidence', ['run_id'], unique=False)
    op.create_index('ix_community_discussion_evidence_source_id', 'community_discussion_evidence', ['source_id'], unique=False)
    op.create_table(
        'ikea_store_evidence',
        sa.Column('evidence_id', sa.String(length=36), nullable=False),
        sa.Column('bundle_id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('source_id', sa.String(length=36), nullable=False),
        sa.Column('fact_type', sa.String(length=80), nullable=False),
        sa.Column('target_type', sa.String(length=60), nullable=False),
        sa.Column('product_id', sa.String(length=36), nullable=True),
        sa.Column('listing_id', sa.String(length=36), nullable=True),
        sa.Column('candidate_id', sa.String(length=36), nullable=True),
        sa.Column('seller_name', sa.String(length=200), nullable=True),
        sa.Column('review_id', sa.String(length=200), nullable=True),
        sa.Column('region_code', sa.String(length=12), nullable=True),
        sa.Column('source_target_id', sa.String(length=36), nullable=True),
        sa.Column('store_context_source_id', sa.String(length=36), nullable=True),
        sa.Column('recommendation_claim_id', sa.String(length=120), nullable=True),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['bundle_id'],
            ['ikea_store_evidence_bundles.bundle_id'],
            name=op.f('fk_ikea_store_evidence_bundle_id_ikea_store_evidence_bundles'),
        ),
        sa.ForeignKeyConstraint(
            ['run_id'],
            ['shopping_runs.run_id'],
            name=op.f('fk_ikea_store_evidence_run_id_shopping_runs'),
        ),
        sa.ForeignKeyConstraint(
            ['source_id'],
            ['source_snapshots.source_id'],
            name=op.f('fk_ikea_store_evidence_source_id_source_snapshots'),
        ),
        sa.ForeignKeyConstraint(
            ['store_context_source_id'],
            ['source_snapshots.source_id'],
            name=op.f('fk_ikea_store_evidence_store_context_source_id_source_snapshots'),
        ),
        sa.PrimaryKeyConstraint('evidence_id', name=op.f('pk_ikea_store_evidence')),
    )
    op.create_index('ix_ikea_store_evidence_bundle_id', 'ikea_store_evidence', ['bundle_id'], unique=False)
    op.create_index('ix_ikea_store_evidence_candidate_id', 'ikea_store_evidence', ['candidate_id'], unique=False)
    op.create_index('ix_ikea_store_evidence_fact_type', 'ikea_store_evidence', ['fact_type'], unique=False)
    op.create_index('ix_ikea_store_evidence_listing_id', 'ikea_store_evidence', ['listing_id'], unique=False)
    op.create_index('ix_ikea_store_evidence_product_id', 'ikea_store_evidence', ['product_id'], unique=False)
    op.create_index('ix_ikea_store_evidence_recommendation_claim_id', 'ikea_store_evidence', ['recommendation_claim_id'], unique=False)
    op.create_index('ix_ikea_store_evidence_region_code', 'ikea_store_evidence', ['region_code'], unique=False)
    op.create_index('ix_ikea_store_evidence_run_id', 'ikea_store_evidence', ['run_id'], unique=False)
    op.create_index('ix_ikea_store_evidence_source_id', 'ikea_store_evidence', ['source_id'], unique=False)
    op.create_index('ix_ikea_store_evidence_store_context_source_id', 'ikea_store_evidence', ['store_context_source_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ikea_store_evidence_store_context_source_id', table_name='ikea_store_evidence')
    op.drop_index('ix_ikea_store_evidence_source_id', table_name='ikea_store_evidence')
    op.drop_index('ix_ikea_store_evidence_run_id', table_name='ikea_store_evidence')
    op.drop_index('ix_ikea_store_evidence_region_code', table_name='ikea_store_evidence')
    op.drop_index('ix_ikea_store_evidence_recommendation_claim_id', table_name='ikea_store_evidence')
    op.drop_index('ix_ikea_store_evidence_product_id', table_name='ikea_store_evidence')
    op.drop_index('ix_ikea_store_evidence_listing_id', table_name='ikea_store_evidence')
    op.drop_index('ix_ikea_store_evidence_fact_type', table_name='ikea_store_evidence')
    op.drop_index('ix_ikea_store_evidence_candidate_id', table_name='ikea_store_evidence')
    op.drop_index('ix_ikea_store_evidence_bundle_id', table_name='ikea_store_evidence')
    op.drop_table('ikea_store_evidence')
    op.drop_index('ix_community_discussion_evidence_source_id', table_name='community_discussion_evidence')
    op.drop_index('ix_community_discussion_evidence_run_id', table_name='community_discussion_evidence')
    op.drop_index('ix_community_discussion_evidence_review_id', table_name='community_discussion_evidence')
    op.drop_index('ix_community_discussion_evidence_region_code', table_name='community_discussion_evidence')
    op.drop_index('ix_community_discussion_evidence_recommendation_claim_id', table_name='community_discussion_evidence')
    op.drop_index('ix_community_discussion_evidence_product_id', table_name='community_discussion_evidence')
    op.drop_index('ix_community_discussion_evidence_listing_id', table_name='community_discussion_evidence')
    op.drop_index('ix_community_discussion_evidence_candidate_id', table_name='community_discussion_evidence')
    op.drop_index('ix_community_discussion_evidence_bundle_id', table_name='community_discussion_evidence')
    op.drop_table('community_discussion_evidence')
    op.drop_index('ix_amazon_product_evidence_source_id', table_name='amazon_product_evidence')
    op.drop_index('ix_amazon_product_evidence_seller_name', table_name='amazon_product_evidence')
    op.drop_index('ix_amazon_product_evidence_run_id', table_name='amazon_product_evidence')
    op.drop_index('ix_amazon_product_evidence_review_id', table_name='amazon_product_evidence')
    op.drop_index('ix_amazon_product_evidence_region_code', table_name='amazon_product_evidence')
    op.drop_index('ix_amazon_product_evidence_recommendation_claim_id', table_name='amazon_product_evidence')
    op.drop_index('ix_amazon_product_evidence_product_id', table_name='amazon_product_evidence')
    op.drop_index('ix_amazon_product_evidence_listing_id', table_name='amazon_product_evidence')
    op.drop_index('ix_amazon_product_evidence_listing_context_source_id', table_name='amazon_product_evidence')
    op.drop_index('ix_amazon_product_evidence_fact_type', table_name='amazon_product_evidence')
    op.drop_index('ix_amazon_product_evidence_candidate_id', table_name='amazon_product_evidence')
    op.drop_index('ix_amazon_product_evidence_bundle_id', table_name='amazon_product_evidence')
    op.drop_table('amazon_product_evidence')
    op.drop_index('ix_ikea_store_contexts_source_id', table_name='ikea_store_contexts')
    op.drop_index('ix_ikea_store_contexts_run_id', table_name='ikea_store_contexts')
    op.drop_index('ix_ikea_store_contexts_product_code', table_name='ikea_store_contexts')
    op.drop_index('ix_ikea_store_contexts_country_code', table_name='ikea_store_contexts')
    op.drop_index('ix_ikea_store_contexts_bundle_id', table_name='ikea_store_contexts')
    op.drop_index('ix_ikea_store_contexts_availability', table_name='ikea_store_contexts')
    op.drop_table('ikea_store_contexts')
    op.drop_index('ix_community_discussion_contexts_thread_id', table_name='community_discussion_contexts')
    op.drop_index('ix_community_discussion_contexts_source_id', table_name='community_discussion_contexts')
    op.drop_index('ix_community_discussion_contexts_run_id', table_name='community_discussion_contexts')
    op.drop_index('ix_community_discussion_contexts_comment_id', table_name='community_discussion_contexts')
    op.drop_index('ix_community_discussion_contexts_bundle_id', table_name='community_discussion_contexts')
    op.drop_table('community_discussion_contexts')
    op.drop_index('ix_amazon_listing_contexts_source_id', table_name='amazon_listing_contexts')
    op.drop_index('ix_amazon_listing_contexts_ships_to_region_code', table_name='amazon_listing_contexts')
    op.drop_index('ix_amazon_listing_contexts_seller_name', table_name='amazon_listing_contexts')
    op.drop_index('ix_amazon_listing_contexts_run_id', table_name='amazon_listing_contexts')
    op.drop_index('ix_amazon_listing_contexts_marketplace_domain', table_name='amazon_listing_contexts')
    op.drop_index('ix_amazon_listing_contexts_bundle_id', table_name='amazon_listing_contexts')
    op.drop_index('ix_amazon_listing_contexts_asin', table_name='amazon_listing_contexts')
    op.drop_table('amazon_listing_contexts')
    op.drop_index('ix_reusable_source_evidence_gaps_source_id', table_name='reusable_source_evidence_gaps')
    op.drop_index('ix_reusable_source_evidence_gaps_run_id', table_name='reusable_source_evidence_gaps')
    op.drop_index('ix_reusable_source_evidence_gaps_review_id', table_name='reusable_source_evidence_gaps')
    op.drop_index('ix_reusable_source_evidence_gaps_region_code', table_name='reusable_source_evidence_gaps')
    op.drop_index('ix_reusable_source_evidence_gaps_recommendation_claim_id', table_name='reusable_source_evidence_gaps')
    op.drop_index('ix_reusable_source_evidence_gaps_product_id', table_name='reusable_source_evidence_gaps')
    op.drop_index('ix_reusable_source_evidence_gaps_listing_id', table_name='reusable_source_evidence_gaps')
    op.drop_index('ix_reusable_source_evidence_gaps_capability', table_name='reusable_source_evidence_gaps')
    op.drop_index('ix_reusable_source_evidence_gaps_bundle_id', table_name='reusable_source_evidence_gaps')
    op.drop_table('reusable_source_evidence_gaps')
    op.drop_index('ix_ikea_store_evidence_bundles_run_id', table_name='ikea_store_evidence_bundles')
    op.drop_table('ikea_store_evidence_bundles')
    op.drop_index('ix_community_discussion_evidence_bundles_run_id', table_name='community_discussion_evidence_bundles')
    op.drop_table('community_discussion_evidence_bundles')
    op.drop_index('ix_amazon_product_evidence_bundles_run_id', table_name='amazon_product_evidence_bundles')
    op.drop_table('amazon_product_evidence_bundles')
