"""Durable resident-first scenario plans, with no changes to source identities."""
from data.models.seed_operations import source_plans


def upgrade(connection):
    source_plans.create(connection, checkfirst=True)
