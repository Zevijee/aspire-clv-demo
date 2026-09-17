"""Shared source identities and histories for ingestion, generation and every module.

The existing ADT tables remain compatibility read models during migration. This
metadata owns new source tables; DDL is applied only by data.migrations.
"""
from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, JSON, MetaData, String, Table,
    UniqueConstraint, func,
)

metadata = MetaData()


def entity_columns(id_name):
    return [Column("organization_id", String(64), primary_key=True),
            Column(id_name, String(36), primary_key=True),
            Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
            Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
            ForeignKeyConstraint(["organization_id"], ["organizations.organization_id"])]


def scoped_fk(column, target, target_column):
    return ForeignKeyConstraint(["organization_id", column],
                                [f"{target}.organization_id", f"{target}.{target_column}"])


organizations = Table("organizations", metadata,
    Column("organization_id", String(64), primary_key=True),
    Column("name", String(160), nullable=False),
    Column("reporting_timezone", String(80), nullable=False),
)
# Existing facility codes are stable keys. The migration adds tenant ownership
# without changing URLs, codes or the serving table's existing primary key.
facility_reference = Table("facilities", metadata,
    Column("facility_code", String(12), primary_key=True),
    Column("organization_id", String(64)),
    UniqueConstraint("organization_id", "facility_code"),
)
portfolios = Table("portfolios", metadata, *entity_columns("portfolio_id"),
    Column("code", String(160), nullable=False), Column("name", String(160), nullable=False),
    UniqueConstraint("organization_id", "code"))
regions = Table("regions", metadata, *entity_columns("region_id"),
    Column("code", String(240), nullable=False), Column("name", String(160), nullable=False),
    UniqueConstraint("organization_id", "code"))
facility_hierarchy_periods = Table("facility_hierarchy_periods", metadata,
    *entity_columns("hierarchy_period_id"), Column("facility_code", String(12), nullable=False),
    Column("portfolio_id", String(36), nullable=False), Column("region_id", String(36), nullable=False),
    Column("started_on", Date, nullable=False), Column("ended_on", Date),
    scoped_fk("facility_code", "facilities", "facility_code"),
    scoped_fk("portfolio_id", "portfolios", "portfolio_id"), scoped_fk("region_id", "regions", "region_id"),
    CheckConstraint("ended_on IS NULL OR ended_on > started_on"),
    UniqueConstraint("organization_id", "facility_code", "started_on"))
facility_capacity_periods = Table("facility_capacity_periods", metadata,
    *entity_columns("capacity_period_id"), Column("facility_code", String(12), nullable=False),
    Column("licensed_beds", Integer, nullable=False), Column("operational_beds", Integer),
    Column("started_on", Date, nullable=False), Column("ended_on", Date),
    scoped_fk("facility_code", "facilities", "facility_code"),
    CheckConstraint("licensed_beds >= 0 AND (operational_beds IS NULL OR operational_beds >= 0)"),
    CheckConstraint("ended_on IS NULL OR ended_on > started_on"))
residents = Table("residents", metadata, *entity_columns("resident_id"),
    Column("display_name", String(160), nullable=False), Column("first_name", String(80)),
    Column("last_name", String(80)), Column("date_of_birth", Date))
resident_identifiers = Table("resident_identifiers", metadata, *entity_columns("identifier_id"),
    Column("resident_id", String(36), nullable=False), Column("source_system", String(80), nullable=False),
    Column("identifier_scope", String(160), nullable=False), Column("external_key", String(240), nullable=False),
    scoped_fk("resident_id", "residents", "resident_id"),
    UniqueConstraint("organization_id", "source_system", "identifier_scope", "external_key"))
payer_types = Table("payer_types", metadata,
    Column("payer_type_id", String(36), primary_key=True), Column("code", String(80), unique=True, nullable=False),
    Column("name", String(80), nullable=False), Column("is_active", Boolean, nullable=False, default=True))
payers = Table("payers", metadata, *entity_columns("payer_id"),
    Column("code", String(160), nullable=False), Column("name", String(160), nullable=False),
    Column("is_active", Boolean, nullable=False, default=True), UniqueConstraint("organization_id", "code"))
payer_plans = Table("payer_plans", metadata, *entity_columns("payer_plan_id"),
    Column("payer_id", String(36), nullable=False),
    Column("payer_type_id", String(36), ForeignKey("payer_types.payer_type_id"), nullable=False),
    Column("code", String(240), nullable=False), Column("name", String(160), nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    scoped_fk("payer_id", "payers", "payer_id"), UniqueConstraint("organization_id", "code"))
external_locations = Table("external_locations", metadata, *entity_columns("location_id"),
    Column("code", String(240), nullable=False), Column("name", String(160), nullable=False),
    Column("location_type", String(80), nullable=False), Column("state_code", String(2)),
    Column("is_active", Boolean, nullable=False, default=True), UniqueConstraint("organization_id", "code"))
external_location_assignments = Table("external_location_assignments", metadata,
    *entity_columns("assignment_id"), Column("location_id", String(36), nullable=False),
    Column("portfolio_id", String(36)), Column("region_id", String(36)),
    Column("started_on", Date, nullable=False), Column("ended_on", Date),
    scoped_fk("location_id", "external_locations", "location_id"),
    scoped_fk("portfolio_id", "portfolios", "portfolio_id"), scoped_fk("region_id", "regions", "region_id"))
census_stays = Table("census_stays", metadata, *entity_columns("stay_id"),
    Column("resident_id", String(36), nullable=False), Column("facility_code", String(12), nullable=False),
    Column("admission_date", Date), Column("discharge_date", Date),
    Column("known_from", Date, nullable=False), Column("start_known", Boolean, nullable=False),
    Column("admitted_at", DateTime(timezone=True)), Column("discharged_at", DateTime(timezone=True)),
    Column("time_precision", String(16), nullable=False, default="date"),
    Column("source_location_id", String(36)), Column("destination_location_id", String(36)),
    Column("source_type", String(80)), Column("destination_type", String(80)),
    Column("discharge_type", String(80)), Column("source_readmission_flag", Boolean),
    Column("readmission_gap_days", Integer), Column("source_system", String(80), nullable=False),
    scoped_fk("resident_id", "residents", "resident_id"), scoped_fk("facility_code", "facilities", "facility_code"),
    scoped_fk("source_location_id", "external_locations", "location_id"),
    scoped_fk("destination_location_id", "external_locations", "location_id"),
    CheckConstraint("NOT start_known OR admission_date IS NOT NULL"),
    CheckConstraint("discharge_date IS NULL OR discharge_date >= coalesce(admission_date, known_from)"),
    Index("ix_census_stays_facility_dates", "organization_id", "facility_code", "admission_date", "discharge_date"),
    Index("ix_census_stays_resident", "organization_id", "resident_id", "admission_date"))
payer_stays = Table("payer_stays", metadata, *entity_columns("payer_stay_id"),
    Column("source_system", String(80), nullable=False),
    Column("stay_id", String(36), nullable=False), Column("payer_plan_id", String(36), nullable=False),
    Column("started_on", Date, nullable=False), Column("ended_on", Date),
    Column("started_at", DateTime(timezone=True)), Column("ended_at", DateTime(timezone=True)),
    Column("time_precision", String(16), nullable=False, default="date"),
    Column("source_sequence", Integer, nullable=False, default=0),
    scoped_fk("stay_id", "census_stays", "stay_id"), scoped_fk("payer_plan_id", "payer_plans", "payer_plan_id"),
    CheckConstraint("ended_on IS NULL OR ended_on >= started_on"),
    UniqueConstraint("organization_id", "stay_id", "started_on", "source_sequence"),
    Index("ix_payer_stays_stay_dates", "organization_id", "stay_id", "started_on", "ended_on"))

rooms = Table("rooms", metadata, *entity_columns("room_id"),
    Column("facility_code", String(12), nullable=False), Column("code", String(80), nullable=False),
    scoped_fk("facility_code", "facilities", "facility_code"), UniqueConstraint("organization_id", "facility_code", "code"))
beds = Table("beds", metadata, *entity_columns("bed_id"),
    Column("room_id", String(36), nullable=False), Column("code", String(80), nullable=False),
    scoped_fk("room_id", "rooms", "room_id"), UniqueConstraint("organization_id", "room_id", "code"))
bed_status_periods = Table("bed_status_periods", metadata, *entity_columns("status_period_id"),
    Column("bed_id", String(36), nullable=False), Column("status", String(40), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False), Column("ended_at", DateTime(timezone=True)),
    scoped_fk("bed_id", "beds", "bed_id"), CheckConstraint("ended_at IS NULL OR ended_at > started_at"))
resident_bed_assignments = Table("resident_bed_assignments", metadata, *entity_columns("assignment_id"),
    Column("stay_id", String(36), nullable=False), Column("bed_id", String(36), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False), Column("ended_at", DateTime(timezone=True)),
    scoped_fk("stay_id", "census_stays", "stay_id"), scoped_fk("bed_id", "beds", "bed_id"),
    CheckConstraint("ended_at IS NULL OR ended_at > started_at"))
resident_absences = Table("resident_absences", metadata, *entity_columns("absence_id"),
    Column("stay_id", String(36), nullable=False), Column("absence_type", String(80), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False), Column("returned_at", DateTime(timezone=True)),
    scoped_fk("stay_id", "census_stays", "stay_id"), CheckConstraint("returned_at IS NULL OR returned_at > started_at"))
bed_reservations = Table("bed_reservations", metadata, *entity_columns("reservation_id"),
    Column("bed_id", String(36), nullable=False), Column("resident_id", String(36), nullable=False),
    Column("stay_id", String(36)), Column("absence_id", String(36)),
    Column("started_at", DateTime(timezone=True), nullable=False), Column("ended_at", DateTime(timezone=True)),
    scoped_fk("bed_id", "beds", "bed_id"), scoped_fk("resident_id", "residents", "resident_id"),
    scoped_fk("stay_id", "census_stays", "stay_id"), scoped_fk("absence_id", "resident_absences", "absence_id"),
    CheckConstraint("ended_at IS NULL OR ended_at > started_at"))
resident_status_periods = Table("resident_status_periods", metadata, *entity_columns("status_period_id"),
    Column("stay_id", String(36), nullable=False), Column("status_type", String(80), nullable=False),
    Column("started_on", Date, nullable=False), Column("ended_on", Date),
    scoped_fk("stay_id", "census_stays", "stay_id"), CheckConstraint("ended_on IS NULL OR ended_on > started_on"))


def source_key_table(name, entity, key):
    return Table(name, metadata, Column("organization_id", String(64), primary_key=True),
        Column("source_system", String(80), primary_key=True), Column("external_key", String(240), primary_key=True),
        Column(key, String(36), nullable=False), scoped_fk(key, entity, key))


resident_source_keys = source_key_table("resident_source_keys", "residents", "resident_id")
stay_source_keys = source_key_table("stay_source_keys", "census_stays", "stay_id")
payer_source_keys = source_key_table("payer_source_keys", "payers", "payer_id")
payer_plan_source_keys = source_key_table("payer_plan_source_keys", "payer_plans", "payer_plan_id")
location_source_keys = source_key_table("external_location_source_keys", "external_locations", "location_id")
ingestion_issues = Table("ingestion_issues", metadata,
    Column("issue_id", String(36), primary_key=True),
    Column("organization_id", String(64), ForeignKey("organizations.organization_id"), nullable=False),
    Column("source_system", String(80), nullable=False), Column("external_key", String(240)),
    Column("code", String(80), nullable=False), Column("details", JSON, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.now()))
