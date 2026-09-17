"""Discharge schema and seeder for reconciled admission stays and census."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
)

from seeding.base import BaseSeeder, SeedContext, SeedResult

GENERATOR_VERSION = "resident-movement-v2"
DISCHARGE_TYPES = ("Routine", "Transfer", "Deceased", "AMA")
from data.models.discharges import metadata, discharges

class DischargesSeeder(BaseSeeder):
    name = "discharges"
    dependencies = ("admissions",)

    def seed(self, context: SeedContext) -> SeedResult:
        from seeding.generators.resident_movement import seed_movement

        return seed_movement(context)

    def validate(self, context: SeedContext, result: SeedResult) -> None:
        from seeding.generators.resident_movement import validate_movement

        validate_movement(context, result)
