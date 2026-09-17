"""Publish shared source facts into the existing ADT compatibility read models.

This is a read-model transformation, never a fake-data generator. The caller
must supply a complete source scope and own the transaction/publication. Event
replacement is restricted to the requested dates. Intersecting stay and payer
intervals retain their full boundaries so opening census, payer attribution and
LOS do not become invented dates at the start of the reporting window.

Some canonical facts cannot fit the older, non-nullable, date-only read models.
Those inputs fail explicitly until the relevant serving schema is upgraded.
"""

from collections import Counter, defaultdict
from datetime import date, timedelta

from data.locking import lock_source_scope

from sqlalchemy import and_, or_, select, text
from sqlalchemy.engine import Connection

from data.models import canonical as c
from data.models.admissions import admissions
from data.models.adt_values import DISCHARGE_TYPES, PAYER_TYPES
from data.models.discharges import discharges
from data.models.payer_changes import payer_changes
from data.models.payer_periods import periods
from data.models.stays import census, stays
from data.writers.core import upsert_rows
from data.writers.source import validate_source_history
from domain.identities import source_id


class ProjectionInputError(ValueError):
    """A canonical fact cannot be represented faithfully by a serving table."""


def _text(value, maximum, field):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ProjectionInputError(
            f"Canonical {field} must be present and fit {maximum} characters for "
            "the existing ADT read model. Correct the source mapping or upgrade "
            "the serving column; values are not guessed or truncated."
        )
    return value


def _validate_scope(connection, organization_id, facility_codes, start_date, end_date):
    if not connection.in_transaction():
        raise ValueError("Canonical projection requires a caller-owned transaction.")
    if not organization_id or not facility_codes:
        raise ValueError("An organization and explicit facility codes are required.")
    if not isinstance(start_date, date) or not isinstance(end_date, date) or start_date > end_date:
        raise ValueError("A valid inclusive projection date range is required.")
    if isinstance(facility_codes, str):
        raise ValueError("Facility scope must be a sequence of codes, not a single string.")
    codes = tuple(facility_codes)
    if any(not isinstance(code, str) or not code for code in codes):
        raise ValueError("Facility codes must be nonempty strings.")
    codes = tuple(sorted(set(codes)))
    rows = connection.execute(select(
        c.facility_reference.c.facility_code, c.facility_reference.c.organization_id,
    ).where(c.facility_reference.c.facility_code.in_(codes))).all()
    if {row.facility_code for row in rows} != set(codes):
        raise ValueError("The canonical projection scope contains unknown facilities.")
    if any(row.organization_id != organization_id for row in rows):
        raise ValueError("Canonical projection scope crosses organization ownership.")
    return codes


def _source_stays(connection, organization_id, code, start_date, end_date):
    origin = c.external_locations.alias("origin")
    destination = c.external_locations.alias("destination")
    source = c.census_stays
    joined = source.join(c.residents, and_(
        c.residents.c.organization_id == source.c.organization_id,
        c.residents.c.resident_id == source.c.resident_id,
    )).outerjoin(origin, and_(
        origin.c.organization_id == source.c.organization_id,
        origin.c.location_id == source.c.source_location_id,
    )).outerjoin(destination, and_(
        destination.c.organization_id == source.c.organization_id,
        destination.c.location_id == source.c.destination_location_id,
    ))
    query = select(
        source, c.residents.c.display_name.label("resident_name"),
        origin.c.name.label("origin_name"), origin.c.location_type.label("origin_type"),
        destination.c.name.label("destination_name"),
        destination.c.location_type.label("destination_kind"),
    ).select_from(joined).where(
        source.c.organization_id == organization_id, source.c.facility_code == code,
        or_(source.c.admission_date <= end_date,
            and_(source.c.admission_date.is_(None), source.c.known_from <= end_date)),
        or_(source.c.discharge_date.is_(None), source.c.discharge_date >= start_date),
    ).order_by(source.c.stay_id)
    return [dict(row) for row in connection.execute(query).mappings()]


def _source_payers(connection, organization_id, stay_ids):
    histories = defaultdict(list)
    if not stay_ids:
        return histories
    source = c.payer_stays
    joined = source.join(c.payer_plans, and_(
        c.payer_plans.c.organization_id == source.c.organization_id,
        c.payer_plans.c.payer_plan_id == source.c.payer_plan_id,
    )).join(c.payer_types, c.payer_types.c.payer_type_id == c.payer_plans.c.payer_type_id)
    # Facility batches avoid building an all-organization resident/coverage payload.
    for offset in range(0, len(stay_ids), 1000):
        query = select(
            source, c.payer_types.c.code.label("payer_type"),
            c.payer_plans.c.name.label("payer_name"),
        ).select_from(joined).where(
            source.c.organization_id == organization_id,
            source.c.stay_id.in_(stay_ids[offset:offset + 1000]),
        ).order_by(source.c.stay_id, source.c.started_on, source.c.source_sequence,
                   source.c.payer_stay_id)
        for row in connection.execute(query).mappings():
            histories[row["stay_id"]].append(dict(row))
    return histories


def _validate_history(stay, history):
    if not stay["start_known"] or stay["admission_date"] is None:
        raise ProjectionInputError(
            "An intersecting stay has an unknown admission date. The existing ADT "
            "stay/LOS read model requires a known date; upgrade that projection "
            "before publishing this scope. known_from is not an admission date."
        )
    _text(stay["resident_name"], 120, "resident display name")
    if stay["time_precision"] != "date" or any(item["time_precision"] != "date" for item in history):
        raise ProjectionInputError(
            "Timestamp-precision stays or payer intervals need a timestamp-aware "
            "serving contract before publication. The date-only legacy projection "
            "must not discard event ordering or guess payer-at-event attribution."
        )
    if not history or history[0]["started_on"] != stay["admission_date"]:
        raise ProjectionInputError("Payer coverage must identify the payer at the actual admission boundary.")
    if history[-1]["ended_on"] != stay["discharge_date"]:
        raise ProjectionInputError("Payer coverage must extend exactly to the known discharge or remain open with the stay.")
    previous = None
    for item in history:
        if item["payer_type"] not in PAYER_TYPES:
            raise ProjectionInputError(
                "A payer type has no supported legacy ADT code. Add the reference "
                "mapping and serving-schema migration before publishing it."
            )
        _text(item["payer_name"], 120, "payer plan name")
        if item["ended_on"] is not None and item["ended_on"] < item["started_on"]:
            raise ProjectionInputError("Payer coverage has reversed boundaries.")
        if previous and previous["ended_on"] != item["started_on"]:
            raise ProjectionInputError("Payer coverage must be continuous and non-overlapping within a stay.")
        if previous and previous["started_on"] == item["started_on"]:
            if previous["source_sequence"] >= item["source_sequence"]:
                raise ProjectionInputError("Same-date payer intervals need explicit, increasing source_sequence values.")
        if previous and previous["payer_plan_id"] != item["payer_plan_id"] and (
            previous["payer_type"], previous["payer_name"]
        ) == (item["payer_type"], item["payer_name"]):
            raise ProjectionInputError(
                "Distinct payer plans share the same legacy type/name. The legacy "
                "change log cannot identify that transition; add plan IDs to its contract."
            )
        previous = item


def _event_key(row):
    return (row["resident_id"], row["facility_code"], row["start_date"], row["discharge_date"])


def _change_key(row):
    return tuple(row[key] for key in (
        "resident_id", "facility_code", "effective_date", "previous_payer_start_date",
        "previous_payer_type", "previous_payer_name", "new_payer_type", "new_payer_name",
    ))


def _existing_ids(connection, code, start_date, end_date):
    exits = {}
    changes = {}
    for row in connection.execute(select(discharges).where(
        discharges.c.facility_code == code,
        discharges.c.discharge_date.between(start_date, end_date),
    )).mappings():
        key = _event_key(row)
        if key in exits:
            raise ProjectionInputError("Duplicate existing discharge identities must be reconciled before publication.")
        exits[key] = row["discharge_id"]
    for row in connection.execute(select(payer_changes).where(
        payer_changes.c.facility_code == code,
        payer_changes.c.effective_date.between(start_date, end_date),
    )).mappings():
        key = _change_key(row)
        if key in changes:
            raise ProjectionInputError("Ambiguous existing payer-change identities require reconciliation.")
        changes[key] = row["change_id"]
    return exits, changes


def _rows(organization_id, source, histories, old_stays, exit_ids, change_ids, start_date, end_date):
    output = {"stays": [], "periods": [], "admissions": [], "discharges": [], "payer_changes": []}
    for stay in source:
        history = histories[stay["stay_id"]]
        _validate_history(stay, history)
        begin, end = stay["admission_date"], stay["discharge_date"]
        common = {key: stay[key] for key in ("facility_code", "resident_id", "resident_name")}
        old = old_stays.get(stay["stay_id"])
        output["stays"].append(dict(
            **common, stay_id=stay["stay_id"], start_date=begin, end_date=end,
            opening_resident=old["opening_resident"] if old else begin < start_date,
            initial_payer_type=history[0]["payer_type"], initial_payer_name=history[0]["payer_name"],
        ))
        if start_date <= begin <= end_date:
            if stay["source_readmission_flag"] is None:
                raise ProjectionInputError("Admission readmission classification is missing; unknown is not false.")
            if stay["source_readmission_flag"] and stay["readmission_gap_days"] is None:
                raise ProjectionInputError("Readmission gap is unknown; the within-30-days measure cannot treat it as zero.")
            output["admissions"].append(dict(
                **common, admission_id=stay["stay_id"], admission_date=begin,
                payer_type=history[0]["payer_type"], payer_name=history[0]["payer_name"],
                admission_source_type=_text(stay["source_type"] or stay["origin_type"], 40, "admission source type"),
                admission_source_name=_text(stay["origin_name"], 160, "admission source name"),
                is_readmission=stay["source_readmission_flag"],
                readmission_days_since_prior=stay["readmission_gap_days"],
            ))
        if end is not None and start_date <= end <= end_date:
            if stay["discharge_type"] not in DISCHARGE_TYPES:
                raise ProjectionInputError("Discharge classification is missing or unsupported by the ADT read model.")
            exit_row = dict(
                **common, start_date=begin, discharge_date=end,
                payer_type=history[-1]["payer_type"], payer_name=history[-1]["payer_name"],
                destination_type=_text(stay["destination_type"] or stay["destination_kind"], 40, "discharge destination type"),
                destination_name=_text(stay["destination_name"], 160, "discharge destination name"),
                discharge_type=stay["discharge_type"], los_days=(end - begin).days,
            )
            exit_row["discharge_id"] = exit_ids.get(_event_key(exit_row)) or source_id(
                organization_id, "canonical-projection", "discharge", stay["stay_id"],
            )
            output["discharges"].append(exit_row)
        for index, item in enumerate(history):
            output["periods"].append(dict(
                period_id=item["payer_stay_id"], stay_id=stay["stay_id"],
                facility_code=stay["facility_code"], start_date=item["started_on"],
                end_date=item["ended_on"], payer_type=item["payer_type"], payer_name=item["payer_name"],
            ))
            if index == 0 or not start_date <= item["started_on"] <= end_date:
                continue
            previous = history[index - 1]
            if (previous["payer_type"], previous["payer_name"]) == (item["payer_type"], item["payer_name"]):
                continue
            change = dict(
                **common, effective_date=item["started_on"],
                previous_payer_start_date=previous["started_on"], new_payer_end_date=item["ended_on"],
                previous_payer_type=previous["payer_type"], previous_payer_name=previous["payer_name"],
                new_payer_type=item["payer_type"], new_payer_name=item["payer_name"],
                change_category="Payer type" if previous["payer_type"] != item["payer_type"] else "Plan only",
            )
            # The destination interval is a stable source identity, unlike its sequence or label.
            change["change_id"] = change_ids.get(_change_key(change)) or source_id(
                organization_id, "canonical-projection", "payer-change", item["payer_stay_id"],
            )
            output["payer_changes"].append(change)
    for dataset, identity in (("discharges", _event_key), ("payer_changes", _change_key)):
        if len({identity(row) for row in output[dataset]}) != len(output[dataset]):
            raise ProjectionInputError(
                "Multiple source events have indistinguishable legacy date/identity "
                "fields. Add source stay/interval identity to that serving contract "
                "before publishing; events are not merged or counted twice."
            )
    return output


def _validate_replacement_scope(connection, organization_id, source, old, start_date, end_date):
    current = {row["stay_id"]: row for row in source}
    for identifier, before in old.items():
        after = current.get(identifier)
        if after is None:
            elsewhere = connection.execute(select(c.census_stays.c.stay_id).where(
                c.census_stays.c.organization_id == organization_id,
                c.census_stays.c.stay_id == identifier,
            )).first()
            if elsewhere:
                raise ProjectionInputError(
                    "A stay changed facility or left the selected dates. Its existing "
                    "projection requires an explicit identity/boundary backfill across "
                    "both scopes before this date-limited refresh."
                )
            if before["start_date"] < start_date or (
                before["end_date"] is not None and before["end_date"] > end_date
            ):
                raise ProjectionInputError(
                    "A deleted stay has movement events outside the selected date range. "
                    "Expand the repair to include those former boundaries before publishing."
                )
            continue
        for old_key, new_key in (("start_date", "admission_date"), ("end_date", "discharge_date")):
            previous, replacement = before[old_key], after[new_key]
            if previous != replacement and any(
                value is not None and not start_date <= value <= end_date
                for value in (previous, replacement)
            ):
                raise ProjectionInputError(
                    "A stay boundary correction extends outside the requested dates. "
                    "Include both old and new movement dates in the projection scope."
                )


def _retained_change_updates(connection, code, source, histories, old_stays, start_date):
    """Complete retained transition attributes without moving historical events.

    A transition can precede this refresh while its destination coverage ends
    today. Its historical event identity/count remains unchanged, but LOS must
    stop being reported as ongoing. Reference display edits follow the same path.
    """
    if not source:
        return []
    earliest = min(row["admission_date"] for row in source)
    existing = defaultdict(list)
    for row in connection.execute(select(payer_changes).where(
        payer_changes.c.facility_code == code,
        payer_changes.c.effective_date >= earliest,
        payer_changes.c.effective_date < start_date,
    )).mappings():
        key = (row["resident_id"], row["effective_date"], row["previous_payer_start_date"])
        existing[key].append(dict(row))
    updates = []
    for stay in source:
        history = histories[stay["stay_id"]]
        prior_resident = old_stays.get(stay["stay_id"], {}).get("resident_id", stay["resident_id"])
        for previous, current in zip(history, history[1:]):
            if current["started_on"] >= start_date:
                continue
            key = (prior_resident, current["started_on"], previous["started_on"])
            matches = existing.get(key, [])
            if not matches:
                continue  # An attribute repair never invents an older event.
            if len(matches) != 1:
                raise ProjectionInputError("A retained payer transition has ambiguous source interval identity.")
            recorded = matches[0]
            if (previous["payer_type"], previous["payer_name"]) == (
                current["payer_type"], current["payer_name"]
            ):
                raise ProjectionInputError(
                    "An older payer transition is no longer present in the source history. "
                    "Include its effective date in the event refresh instead of changing its count implicitly."
                )
            category = "Payer type" if previous["payer_type"] != current["payer_type"] else "Plan only"
            if (recorded["previous_payer_type"] != previous["payer_type"]
                    or recorded["new_payer_type"] != current["payer_type"]
                    or recorded["change_category"] != category
                    or prior_resident != stay["resident_id"]):
                raise ProjectionInputError(
                    "An older payer event needs a type or resident-identity correction. "
                    "Expand the event refresh to its effective date; an attribute-only "
                    "repair must not change historical cohort counts."
                )
            updates.append(dict(
                change_id=recorded["change_id"], resident_name=stay["resident_name"],
                previous_payer_name=previous["payer_name"], new_payer_name=current["payer_name"],
                new_payer_end_date=current["ended_on"],
            ))
    return updates


def _census_rows(code, source, start_date, end_date):
    arriving = Counter(row["admission_date"] for row in source)
    departing = Counter(row["discharge_date"] for row in source if row["discharge_date"] is not None)
    opening = sum(row["admission_date"] < start_date and (
        row["discharge_date"] is None or row["discharge_date"] >= start_date
    ) for row in source)
    for offset in range((end_date - start_date).days + 1):
        day = start_date + timedelta(days=offset)
        closing = opening + arriving[day] - departing[day]
        if opening < 0 or closing < 0:
            raise ProjectionInputError("Canonical census boundaries do not reconcile.")
        yield dict(facility_code=code, census_date=day, opening_census=opening,
                   closing_census=closing, admissions=arriving[day], discharges=departing[day])
        opening = closing


def _reject_id_collisions(connection, table, key, ids, code):
    for offset in range(0, len(ids), 1000):
        conflict = connection.execute(select(table.c[key]).where(
            table.c[key].in_(ids[offset:offset + 1000]), table.c.facility_code != code,
        ).limit(1)).first()
        if conflict:
            raise ProjectionInputError(
                f"A canonical {key} collides with another facility's legacy projection. "
                "Upgrade the legacy primary key to organization scope; source IDs are not remapped."
            )


def publish_legacy_read_models(
    connection: Connection,
    organization_id: str,
    facility_codes,
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    """Replace the selected read scope inside the caller's publication transaction.

    The savepoint prevents a caller that catches validation errors from committing
    an earlier facility's half-completed projection. It is not a publication or a
    source-coverage claim. Refresh dependent summaries before committing.
    """
    codes = _validate_scope(connection, organization_id, facility_codes, start_date, end_date)
    lock_source_scope(connection, organization_id)
    validate_source_history(connection, organization_id, codes)
    totals = dict.fromkeys(("stays", "periods", "admissions", "discharges", "payer_changes",
                           "payer_change_attributes", "census"), 0)
    with connection.begin_nested():
        for code in codes:
            source = _source_stays(connection, organization_id, code, start_date, end_date)
            stay_ids = [row["stay_id"] for row in source]
            old = {row["stay_id"]: dict(row) for row in connection.execute(select(stays).where(
                stays.c.facility_code == code, stays.c.start_date <= end_date,
                or_(stays.c.end_date.is_(None), stays.c.end_date >= start_date),
            )).mappings()}
            histories = _source_payers(connection, organization_id, stay_ids)
            _validate_replacement_scope(connection, organization_id, source, old, start_date, end_date)
            exits, changes = _existing_ids(connection, code, start_date, end_date)
            rows = _rows(organization_id, source, histories, old, exits, changes, start_date, end_date)
            retained_changes = _retained_change_updates(connection, code, source, histories, old, start_date)
            for table, key, dataset in (
                (stays, "stay_id", "stays"), (periods, "period_id", "periods"),
                (admissions, "admission_id", "admissions"), (discharges, "discharge_id", "discharges"),
                (payer_changes, "change_id", "payer_changes"),
            ):
                _reject_id_collisions(connection, table, key, [row[key] for row in rows[dataset]], code)
            affected_stays = sorted(set(stay_ids) | set(old))
            for offset in range(0, len(affected_stays), 1000):
                ids = affected_stays[offset:offset + 1000]
                connection.execute(periods.delete().where(periods.c.facility_code == code, periods.c.stay_id.in_(ids)))
                connection.execute(stays.delete().where(stays.c.facility_code == code, stays.c.stay_id.in_(ids)))
            for table, day in ((admissions, admissions.c.admission_date),
                               (discharges, discharges.c.discharge_date),
                               (payer_changes, payer_changes.c.effective_date)):
                connection.execute(table.delete().where(table.c.facility_code == code, day.between(start_date, end_date)))
            for name, table in (("stays", stays), ("periods", periods), ("admissions", admissions),
                                ("discharges", discharges), ("payer_changes", payer_changes)):
                totals[name] += upsert_rows(connection, table, rows[name])
            for row in retained_changes:
                values = {key: value for key, value in row.items() if key != "change_id"}
                totals["payer_change_attributes"] += connection.execute(payer_changes.update().where(
                    payer_changes.c.change_id == row["change_id"], payer_changes.c.facility_code == code,
                    payer_changes.c.effective_date < start_date,
                    or_(*(payer_changes.c[key].is_distinct_from(value) for key, value in values.items())),
                ).values(**values)).rowcount
            connection.execute(census.delete().where(census.c.facility_code == code,
                                                      census.c.census_date.between(start_date, end_date)))
            totals["census"] += upsert_rows(connection, census, _census_rows(code, source, start_date, end_date))
    return totals
