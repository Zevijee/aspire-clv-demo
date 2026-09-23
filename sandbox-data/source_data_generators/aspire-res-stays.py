"""Reproducible SNF admission episodes and their contiguous payer periods.

Dates use [start, end): a discharge/end date is not an occupied/covered day.
Null ends mean still present at the latest completed simulation day.
Weights below are demo choices, not measured clinical distributions. Skilled
payers (Medicare categories and VA) share a 100-day allowance; another admission resets it
only after at least 60 days out of the facility in this synthetic history.
"""
from collections import defaultdict
from datetime import date, timedelta
from itertools import accumulate
from heapq import heappop, heappush
from importlib import import_module
import json
from math import ceil, exp, floor
from random import Random
from uuid import UUID

from sqlalchemy import bindparam, func, select

from base import COPY_BATCH_SIZE, BaseGenerator, DailyGenerator


class ResidentStayGenerator(BaseGenerator):
    """Shared payer rules and table ownership; DailyAdtGenerator owns execution."""
    name = 'res_stays'
    table = BaseGenerator.res_stays
    related_tables = (BaseGenerator.res_payer_stays,)
    SEED = 42
    START_DATE = date(2023, 1, 1)
    ADMISSION_WEIGHTS = (12, 36, 31, 13, 5, 2, 1)  # Counts 1 through 7.
    PERIOD_WEIGHTS = (52, 34, 14)  # Counts 1 through 3.
    STATE_MEDICAID_SHARE = 0.50
    MEDICAID_PENDING_SHARE = 0.50
    MAX_SKILLED_DAYS = 100
    # Medicare Advantage plans. A resident can disenrol from one mid-stay and
    # finish under Original Medicare, which is the only skilled-to-skilled payer
    # change that exists here.
    MANAGED_MEDICARE = ('medicare_hmo', 'medicare_comm')
    # Below this the remaining allowance is too short to divide between two
    # skilled periods, so the move is not offered.
    MIN_DAYS_TO_SPLIT_SKILLED = 14
    # Share of eligible managed-Medicare changes that disenrol to Original
    # Medicare rather than moving to Private Pay or Medicaid. A demo choice.
    MANAGED_DISENROLMENT_SHARE = 0.12
    INITIAL_PAYER_WEIGHTS = {
        'medicare': 40, 'medicare_hmo': 23, 'medicare_comm': 10,
        'medicaid': 20, 'private': 4, 'va': 2, 'hospice': 1,
    }
    # Planned total stay length, chosen at admission from the initial payer type.
    # Each entry is ((low, high), weight); a band is picked, then a day within it.
    # These are demo choices, not measured clinical distributions, but they keep
    # payers distinguishable: managed Medicare discharges sooner than traditional
    # Medicare, private pay is largely custodial, and hospice has a short median
    # with a long tail. A single non-Medicaid band gave every payer the same stay.
    STAY_LENGTH_BANDS = {
        'medicaid':      (((45, 120), 40), ((121, 240), 40), ((241, 450), 20)),
        'medicare':      (((14, 35), 45), ((36, 70), 40), ((71, 120), 15)),
        'medicare_comm': (((14, 35), 45), ((36, 70), 40), ((71, 120), 15)),
        'medicare_hmo':  (((10, 28), 55), ((29, 55), 35), ((56, 90), 10)),
        'va':            (((20, 60), 50), ((61, 120), 35), ((121, 240), 15)),
        'private':       (((30, 120), 30), ((121, 365), 40), ((366, 730), 30)),
        'hospice':       (((5, 30), 55), ((31, 90), 30), ((91, 240), 15)),
    }

    @classmethod
    def stay_length_band(cls, category, rng):
        bands = cls.STAY_LENGTH_BANDS.get(category)
        if bands is None:
            raise ValueError(f'Add {category} to STAY_LENGTH_BANDS before admitting it.')
        return rng.choices([band for band, _ in bands], weights=[weight for _, weight in bands], k=1)[0]

    def generate(self):
        raise ValueError('Use manage.py seed or update; fixed-window stay generation has been replaced.')

    def _random(self, kind, *parts):
        # Reuse one Random object per independent stream, preserving its exact seed.
        if not hasattr(self, '_random_sources'):
            self._random_sources = {}
        seed = self.source_id(kind, self.SEED, *(str(part) for part in parts)).int
        rng = self._random_sources.get(kind)
        if rng is None:
            rng = self._random_sources[kind] = Random(seed)
        else:
            rng.seed(seed)
        return rng

    @staticmethod
    def _occupancy_target(rng):
        # 80% of targets are in 85-95%; the remaining targets cover both tails.
        low, high = rng.choices(((0.70, 0.85), (0.85, 0.95), (0.95, 1.00)),
            cum_weights=(10, 90, 100), k=1)[0]
        return rng.uniform(low, high)

    @staticmethod
    def _allocate(total, weights, minimum=0):
        """Allocate an exact integer day budget without zero-length stays."""
        remaining = total - minimum * len(weights)
        if remaining < 0:
            raise ValueError('The date window is too short for the requested stay counts.')
        weight_sum = sum(weights)
        shares = [remaining * weight / weight_sum for weight in weights]
        allocated = [minimum + floor(share) for share in shares]
        order = sorted(range(len(weights)), key=lambda i: shares[i] - floor(shares[i]), reverse=True)
        for index in order[:total - sum(allocated)]:
            allocated[index] += 1
        return allocated

    def _payer_catalog(self):
        catalog = defaultdict(list)
        for row in self._payer_rows:
            catalog[row['payer_type']].append(row)
        missing = set(self.INITIAL_PAYER_WEIGHTS) - set(catalog)
        if missing:
            raise ValueError('Stay generation needs payer categories: ' + ', '.join(sorted(missing)))
        pending = [payer for payer in catalog['medicaid'] if payer['payer_name'] == 'Medicaid Pending']
        if len(pending) != 1:
            raise ValueError('Add Medicaid Pending under medicaid in payers.json and run manage.py payers --regenerate.')
        self._pending_payer = pending[0]
        if self._pending_payer['is_skilled']:
            raise ValueError('Medicaid Pending must be a non-skilled Medicaid payer.')
        # Pending is an application status, not an approved payer choice.
        catalog['medicaid'] = [payer for payer in catalog['medicaid'] if payer['payer_id'] != self._pending_payer['payer_id']]
        self._skilled_types = set()
        for category, payers in catalog.items():
            flags = {payer['is_skilled'] for payer in payers}
            if len(flags) != 1:
                raise ValueError(f'Payers in category {category} must share the same is_skilled flag.')
            if True in flags:
                self._skilled_types.add(category)
        state = [payer for payer in catalog['medicaid'] if payer['payer_name'] == 'State Medicaid']
        if len(state) != 1 or len(catalog['medicaid']) < 2:
            raise ValueError('Medicaid needs State Medicaid and at least one other payer.')
        self._medicaid_choices = {
            True: tuple(state),
            False: tuple(payer for payer in catalog['medicaid'] if payer['payer_name'] != 'State Medicaid'),
        }
        self._payer_exclusions = {}
        return catalog

    def _pick_payer(self, category, previous, catalog, rng):
        choices = catalog[category]
        if category == 'medicaid':
            use_state = rng.random() < self.STATE_MEDICAID_SHARE
            if previous and previous['payer_type'] == 'medicaid':
                # Alternating within Medicaid runs keeps roughly half State Medicaid
                # while ensuring a payer change actually changes the payer.
                use_state = previous['payer_name'] != 'State Medicaid'
            choices = self._medicaid_choices[use_state]
        elif previous and previous['payer_type'] == category:
            key = (category, previous['payer_id'])
            if key not in self._payer_exclusions:
                self._payer_exclusions[key] = tuple(payer for payer in choices if payer['payer_id'] != previous['payer_id'])
            choices = self._payer_exclusions[key]
        if not choices:
            raise ValueError(f'No different payer available for {category}.')
        return rng.choice(choices)

    def payer_mix(self, facility_id, day):
        return dict(self.varied_mix(self.SEED, 'payer-types', facility_id, day,
            tuple(self.INITIAL_PAYER_WEIGHTS.items())))

    def _payer_periods(self, stay_id, start, end, is_open, skilled_remaining, catalog, *,
            facility_id, initial_category=None, medicaid_multiplier=1.0, minimum_first_days=1,
            skilled_mode=21):
        rng = self._random('payer-periods', stay_id)
        length = end - start
        count = min(length, rng.choices((1, 2, 3), cum_weights=self._period_cumulative, k=1)[0])
        mix = self.payer_mix(facility_id, self.START_DATE + timedelta(days=start))
        mix['medicaid'] *= medicaid_multiplier
        initial = dict(mix)
        if skilled_remaining == 0:
            for category in self._skilled_types:
                initial.pop(category, None)
        if count > 1:
            initial.pop('hospice', None)
        category = initial_category or rng.choices(tuple(initial), weights=tuple(initial.values()), k=1)[0]
        if category == 'hospice':
            count = 1
        if category in self._skilled_types and skilled_remaining <= 0:
            raise ValueError('A resident without skilled days cannot start with a skilled payer.')
        if category in self._skilled_types and length > skilled_remaining:
            count = max(2, count)
        payers = [self._pick_payer(category, None, catalog, rng)]
        for number in range(1, count):
            previous = payers[-1]
            choice_key = (previous['payer_type'], number < count - 1)
            if choice_key not in self._transition_choices:
                if previous['payer_type'] == 'medicaid':
                    transitions = {'medicaid': 85, 'private': 8, 'hospice': 7}
                elif previous['payer_type'] in self.MANAGED_MEDICARE:
                    # Disenrolling from a Medicare Advantage plan mid-stay moves
                    # the resident to Original Medicare. This is the only skilled
                    # destination there is, and it continues the same 100-day
                    # allowance rather than starting a new one. Its share is
                    # applied after the census mix adjustment below, not as a
                    # weight here; eligibility is checked there too.
                    transitions = {'private': 70, 'medicaid': 24, 'hospice': 6, 'medicare': 0}
                elif previous['is_skilled']:
                    transitions = {'private': 70, 'medicaid': 24, 'hospice': 6}
                elif previous['payer_type'] == 'private':
                    transitions = {'medicaid': 92, 'hospice': 8}
                else:
                    transitions = {'medicaid': 90, 'hospice': 10}
                # Electing hospice is available from every payer, but only as the
                # last period: the benefit runs to the end of the stay.
                if number < count - 1:
                    transitions.pop('hospice', None)
                # No other payer change may restart the skilled allowance.
                transitions = {category: weight for category, weight in transitions.items()
                    if category not in self._skilled_types or category == 'medicare'}
                if not transitions:
                    raise ValueError('Skilled stays require a non-skilled Private or Medicaid payer to transition to.')
                self._transition_choices[choice_key] = (tuple(transitions), tuple(transitions.values()))
            choices, weights = self._transition_choices[choice_key]
            adjusted = {category: weight * mix[category] / self.INITIAL_PAYER_WEIGHTS[category]
                for category, weight in zip(choices, weights)}
            if 'medicare' in adjusted:
                # Two skilled periods share what is left of the allowance, so the
                # move is only offered while there is enough to split between them.
                blocked = skilled_remaining < self.MIN_DAYS_TO_SPLIT_SKILLED
                # Taking it on the final period leaves the whole stay skilled, so
                # the entire stay then has to fit inside the allowance.
                if (number == count - 1 and length > skilled_remaining
                        and all(payer['is_skilled'] for payer in payers)):
                    blocked = True
                if blocked:
                    adjusted.pop('medicare')
                else:
                    # Set the share directly. Scaling it by the census mix like the
                    # others would divide by Medicare's initial weight of 40 against
                    # Private's 4, leaving disenrolment at well under 1%.
                    share = self.MANAGED_DISENROLMENT_SHARE
                    others = sum(value for key, value in adjusted.items() if key != 'medicare')
                    adjusted['medicare'] = others * share / (1 - share)
            if previous['is_skilled']:
                # Private remains the usual next payer after skilled coverage,
                # even when the census is currently below its Medicaid target.
                adjusted['private'] = max(adjusted['private'], 1.5 * adjusted['medicaid'])
            category = rng.choices(tuple(adjusted), weights=tuple(adjusted.values()), k=1)[0]
            payers.append(self._pick_payer(category, previous, catalog, rng))

        # The leading run of skilled payers shares one allowance. A managed-to-
        # traditional Medicare change makes that run two periods long; the days
        # are split between them rather than granted twice.
        skilled_count = 0
        for payer in payers:
            if not payer['is_skilled']:
                break
            skilled_count += 1
        skilled_days = 0
        if skilled_count:
            if skilled_count == count:
                # Every period is skilled, so the whole stay draws on the
                # allowance. The choice above only permits this when it fits.
                skilled_days = length
                lengths = self._allocate(length,
                    [rng.random() + 0.1 for _ in range(count)], minimum=1)
            else:
                maximum = min(skilled_remaining, length - (count - skilled_count))
                skilled_days = max(skilled_count,
                    int(rng.triangular(1, maximum, min(skilled_mode, maximum))))
                lengths = self._allocate(skilled_days,
                    [rng.random() + 0.1 for _ in range(skilled_count)], minimum=1)
                lengths += self._allocate(length - skilled_days,
                    [rng.random() + 0.1 for _ in range(count - skilled_count)], minimum=1)
        else:
            lengths = self._allocate(length - minimum_first_days + 1,
                [rng.random() + 0.1 for _ in range(count)], minimum=1)
            lengths[0] += minimum_first_days - 1
        if skilled_days > skilled_remaining:
            raise ValueError('A skilled payer period exceeded the available 100-day allowance.')

        periods, cursor = [], start
        identity = self.numbered_ids('payer-stay', str(stay_id))
        for number, (payer, period_days) in enumerate(zip(payers, lengths), start=1):
            last = number == count
            periods.append(dict(payer_stay_id=identity(number),
                stay_id=stay_id, payer_id=payer['payer_id'], period_number=number,
                start_date=self.START_DATE + timedelta(days=cursor),
                end_date=None if last and is_open else self.START_DATE + timedelta(days=cursor + period_days),
                start_reason='admission' if number == 1 else 'payer_change',
                end_reason=None if last and is_open else ('discharge' if last else 'payer_change')))
            cursor += period_days
        return periods, skilled_days


GENERATORS = (ResidentStayGenerator,)


class DailyAdtGenerator(DailyGenerator):
    """Advance actual ADT events one day; future plans are private simulation state.

    Repeatable randomness is keyed by date/facility or stay ID, never command range.
    Resident pools and pending-event heaps reload from committed database records.
    A failed day aborts the command; the next command rebuilds these caches.
    """
    name = 'adt'
    table = BaseGenerator.res_stays
    sequential = True
    owned_tables = (BaseGenerator.residents, BaseGenerator.res_stays, BaseGenerator.res_payer_stays,
        BaseGenerator.admission_logs, BaseGenerator.discharge_logs, BaseGenerator.medicaid_applications, BaseGenerator.adt_resident_state,
        BaseGenerator.adt_active_stays, BaseGenerator.adt_daily_census)
    # One TRUNCATE without CASCADE, so every table referencing one of these has to
    # appear here too. payer_change_logs is not generated by the daily simulation --
    # it has its own command -- but it carries foreign keys to res_stays and
    # res_payer_stays, and leaving it out made `seed --reset-history` fail outright
    # with "cannot truncate a table referenced in a foreign key constraint".
    reset_tables = (BaseGenerator.adt_daily_census, BaseGenerator.adt_active_stays, BaseGenerator.medicaid_applications,
        BaseGenerator.payer_change_logs, BaseGenerator.discharge_logs, BaseGenerator.admission_logs,
        BaseGenerator.res_payer_stays, BaseGenerator.res_stays, BaseGenerator.adt_resident_state)
    SEED = 42
    # Simulated days per write batch. Days are still simulated strictly in order;
    # only the write boundary moves. Per-day writes were ~330 rows per table, where
    # fixed statement cost dominates; a batch of this size reaches bulk COPY rates.
    batch_days = 30

    # One draw places a facility on a spectrum from long-term custodial care (0) to
    # short-stay rehab (1). Everything that distinguishes a facility's payer profile
    # comes off that position, so the targets can never contradict each other the way
    # independently drawn skilled and Medicaid targets would. Region shifts the draw,
    # because neighbouring facilities share a referral and payer landscape.
    SKILLED_CENSUS_RANGE = (0.05, 0.35)
    MEDICAID_CENSUS_RANGE = (0.75, 0.42)      # high at custodial, low at rehab
    REGION_SHIFT = 0.15
    # Rehab beds turn over faster, which is what makes a high skilled census reachable
    # at all: skilled is only ever a stay's first period, so sustaining it needs
    # admissions. Applied to planned length for every payer except Medicaid.
    TURNOVER_RANGE = (1.15, 0.80)
    # Therapy-heavy facilities keep residents on skilled coverage longer.
    SKILLED_PERIOD_MODE = (14, 40)

    # Hospital discharge planning is a weekday function, so far fewer residents
    # arrive at a weekend. Beds are not lost, only deferred: the shortfall is still
    # below target on Monday and fills then, which is what produces the weekly
    # sawtooth every real daily admissions chart has. Monday index 0.
    WEEKDAY_ADMISSION_RATE = (1.0, 1.0, 1.0, 1.0, 0.90, 0.45, 0.35)
    # Respiratory season and winter falls lift census; summer is the trough.
    # Roughly cancels over a year, so it moves the shape, not the annual average.
    SEASONAL_LIFT = {1: .025, 2: .025, 3: .015, 4: 0.0, 5: -.010, 6: -.025,
        7: -.030, 8: -.025, 9: -.010, 10: .005, 11: .015, 12: .020}
    # An outbreak, a survey or a staffing hold takes a single facility off plan for
    # weeks. These are what make outliers worth finding on a portfolio dashboard.
    DISRUPTION_CHANCE = 0.04
    DISRUPTION_DEPTH = (0.04, 0.14)

    def _plan_month(self, day):
        """Refresh the month's targets and disruptions once, not once per day.

        Every value here is keyed by calendar month, so rebuilding it daily meant
        seeding hundreds of generators a day to reproduce numbers that had not
        changed. Same seeds, same values, a thirtieth of the work.
        """
        month = day.strftime('%Y-%m')
        if self._month_key == month:
            return
        self._month_key = month
        self._medicaid_targets = {key: min(.80, max(.40, baseline +
            self._rng('medicaid-census-month', key, month).uniform(-.03, .03)))
            for key, baseline in self._medicaid_baselines.items()}
        self._skilled_targets = {key: min(.45, max(.03, baseline +
            self._rng('skilled-census-month', key, month).uniform(-.03, .03)))
            for key, baseline in self._skilled_baselines.items()}
        self._disruptions = {}
        for key in self._facilities:
            rng = self._rng('facility-disruption', key, month)
            if rng.random() < self.DISRUPTION_CHANCE:
                self._disruptions[key] = (rng.randint(1, 18), rng.randint(10, 26),
                    rng.uniform(*self.DISRUPTION_DEPTH))

    def _disruption(self, facility_id, day):
        """Depth of this facility's current disruption: sharp onset, gradual recovery."""
        plan = self._disruptions.get(facility_id)
        if plan is None:
            return 0.0
        start, length, depth = plan
        offset = day.day - start
        if not 0 <= offset < length:
            return 0.0
        return depth * (1 - offset / length)

    @staticmethod
    def _between(bounds, position):
        low, high = bounds
        return low + (high - low) * position

    def _rng(self, kind, *parts):
        return Random(self.source_id(kind, self.SEED, *(str(part) for part in parts)).int)

    def prepare_daily(self, connection):
        self._facilities = {row['facility_id']: dict(row) for row in self.read_rows(connection,
            select(self.facilities.c.facility_id, self.facilities.c.beds, self.regions.c.region)
            .select_from(self.facilities.join(self.regions)).order_by(self.facilities.c.facility_id))}
        self._planner = ResidentStayGenerator(self.database_url)
        self._planner._payer_rows = self.read_rows(connection, select(self.payers)
            .order_by(self.payers.c.payer_type, self.payers.c.payer_name, self.payers.c.payer_id))
        self._catalog = self._planner._payer_catalog()
        self._medicaid_payer_ids = {row['payer_id'] for row in self._catalog['medicaid']}
        self._medicaid_payer_ids.add(self._planner._pending_payer['payer_id'])
        self._skilled_payer_ids = {row['payer_id'] for row in self._planner._payer_rows if row['is_skilled']}
        self._pending_cases = {row['stay_id']: dict(row) for row in self.read_rows(connection,
            select(self.medicaid_applications).where(self.medicaid_applications.c.approved_date.is_(None)))}
        self._planner._period_cumulative = tuple(accumulate(self._planner.PERIOD_WEIGHTS))
        self._planner._transition_choices = {}
        self._admission_rules = import_module('source_data_generators.aspire-admission-logs').AdmissionLogGenerator
        self._discharge_rules = import_module('source_data_generators.aspire-discharge-logs').DischargeLogGenerator
        hospitals = self.load_hospitals()
        self._hospitals = {}
        for identity, facility in self._facilities.items():
            if facility['region'] not in hospitals:
                raise ValueError(f"No hospitals configured for saved region {facility['region']}.")
            entries = hospitals[facility['region']]
            self._hospitals[identity] = (tuple(row['hospital'] for row in entries),
                tuple(accumulate(row['score'] for row in entries)))
        self._resident_state = {row['resident_id']: dict(row) for row in
            self.read_rows(connection, select(self.adt_resident_state))}
        self._unused = {key: [] for key in self._facilities}
        self._returning = {key: [] for key in self._facilities}
        self._names = set()
        self._resident_ids = set()
        for resident_id, facility_id, first, last in connection.execute(select(
                self.residents.c.resident_id, self.residents.c.facility_id,
                self.residents.c.first_name, self.residents.c.last_name)
                .order_by(self.residents.c.resident_id.desc())):
            self._names.add((first.casefold(), last.casefold()))
            self._resident_ids.add(resident_id)
            if facility_id not in self._facilities:
                raise ValueError(f'Resident {resident_id} has no saved facility.')
            state = self._resident_state.get(resident_id)
            if state is None:
                self._unused[facility_id].append(resident_id)
            elif (not state['is_deceased'] and state['admissions'] < state['admission_limit']
                    and state['eligible_after'] is not None):
                heappush(self._returning[facility_id], (state['eligible_after'], resident_id))
        source = self.facilities_path.parent
        self._first_names = {gender: self.load_name_list(source / f'{gender}_first_names.txt')
            for gender in ('male', 'female')}
        self._last_names = self.load_name_list(source / 'last_names.txt')
        self._active, self._due = {}, []
        self._census = {key: 0 for key in self._facilities}
        self._medicaid_census = {key: 0 for key in self._facilities}
        self._skilled_census = {key: 0 for key in self._facilities}
        # Position each facility once; every payer target it has follows from that.
        self._profiles = {}
        for key, facility in self._facilities.items():
            shift = self._rng('operation-profile-region', facility['region']).uniform(
                -self.REGION_SHIFT, self.REGION_SHIFT)
            self._profiles[key] = min(1.0, max(0.0, self._rng('operation-profile', key).random() + shift))
        self._medicaid_baselines = {key: self._between(self.MEDICAID_CENSUS_RANGE, position)
            for key, position in self._profiles.items()}
        self._skilled_baselines = {key: self._between(self.SKILLED_CENSUS_RANGE, position)
            for key, position in self._profiles.items()}
        # Depends only on the facility, so seed it once rather than every day.
        self._occupancy_baselines = {key: self._planner._occupancy_target(
            self._rng('daily-target', key)) for key in self._facilities}
        self._month_key = None
        self._disruptions = {}
        latest = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == self.name))
        for row in self.read_rows(connection, select(self.res_stays,
                self.adt_active_stays.c.planned_discharge, self.adt_active_stays.c.payer_plan,
                self.adt_active_stays.c.skilled_days, self.adt_active_stays.c.medicaid_approval).select_from(
                    self.res_stays.join(self.adt_active_stays))):
            stay = {key: row[key] for key in self.res_stays.c.keys()}
            if stay['discharge_date'] is not None or latest is None:
                raise ValueError('Saved daily ADT state is inconsistent with active stays.')
            plan = []
            for saved in row['payer_plan']:
                period = dict(saved)
                for key in ('payer_stay_id', 'stay_id', 'payer_id'):
                    period[key] = UUID(period[key])
                for key in ('start_date', 'end_date'):
                    period[key] = date.fromisoformat(period[key])
                plan.append(period)
            active = dict(stay=stay, planned_discharge=row['planned_discharge'],
                periods=plan, skilled_days=row['skilled_days'], approval=None)
            if row['medicaid_approval'] is not None:
                saved = row['medicaid_approval']
                active['approval'] = dict(date=date.fromisoformat(saved['date']), payer_id=UUID(saved['payer_id']))
                if stay['stay_id'] not in self._pending_cases:
                    raise ValueError('An active Medicaid approval plan has no pending application.')
            self._active[stay['stay_id']] = active
            self._census[stay['facility_id']] += 1
            self._medicaid_census[stay['facility_id']] += self._has_medicaid(active, latest)
            self._skilled_census[stay['facility_id']] += self._has_skilled(active, latest)
            self._schedule(active, latest)
        saved_open = connection.scalar(select(func.count()).select_from(self.res_stays)
            .where(self.res_stays.c.discharge_date.is_(None)))
        if saved_open != len(self._active):
            raise ValueError('Open stays are missing daily simulation plans; cannot safely resume.')
        if any(stay_id not in self._active or self._active[stay_id].get('approval') is None
                for stay_id in self._pending_cases):
            raise ValueError('An unresolved Medicaid application is missing its active approval plan.')
        self._reset_batch()

    def _reset_batch(self):
        """Buffers live for the whole batch; the last write for a key wins."""
        self._buffers = {table.name: {} for table in self.owned_tables}
        self._closed = []
        self._approved_admissions = []
        self._touched = defaultdict(set)

    def _put(self, table, row):
        key = tuple(row[column.name] for column in table.primary_key)
        self._buffers[table.name][key] = dict(row)
        self._touched[table.name].add(key)

    def _has_medicaid(self, active, day):
        medicaid_ids = self._medicaid_payer_ids
        return any(period['payer_id'] in medicaid_ids and period['start_date'] <= day < period['end_date']
            for period in active['periods'])

    def _has_skilled(self, active, day):
        skilled_ids = self._skilled_payer_ids
        return any(period['payer_id'] in skilled_ids and period['start_date'] <= day < period['end_date']
            for period in active['periods'])

    def _admission_payer(self, facility_id, admitted, stay_id, skilled_remaining, opening):
        """Steer this facility's Medicaid and skilled census toward its own targets.

        Both are census targets, not admission quotas: skilled residents turn over
        several times faster than Medicaid ones, so the admitted mix is always far
        more skilled than the occupied-bed mix. Feedback only affects new plans;
        saved periods are never silently reassigned.
        """
        census = self._census[facility_id]
        target = self._medicaid_targets[facility_id]
        share = self._medicaid_census[facility_id] / census if census else target
        multiplier = min(8.0, max(.05, exp(16 * (target - share))))
        skilled_target = self._skilled_targets[facility_id]
        skilled_share = self._skilled_census[facility_id] / census if census else skilled_target
        skilled_multiplier = min(8.0, max(.05, exp(16 * (skilled_target - skilled_share))))
        weights = self._planner.payer_mix(facility_id, admitted)
        if skilled_remaining <= 0:
            for category in self._planner._skilled_types:
                weights.pop(category, None)
        if opening:
            # The opening snapshot has no census history to steer from, so set the
            # shares directly and let the remaining payers share what is left.
            skilled_weight = sum(weight for category, weight in weights.items()
                if category in self._planner._skilled_types)
            other_weight = sum(weight for category, weight in weights.items()
                if category != 'medicaid' and category not in self._planner._skilled_types)
            remainder = max(0.05, 1 - target - skilled_target)
            for category in tuple(weights):
                if category in self._planner._skilled_types:
                    weights[category] *= skilled_target / skilled_weight if skilled_weight else 0
                elif category == 'medicaid':
                    weights[category] = target
                elif other_weight:
                    weights[category] *= remainder / other_weight
        weights['medicaid'] *= multiplier
        for category in self._planner._skilled_types:
            if category in weights:
                weights[category] *= skilled_multiplier
        if not any(weights.values()):
            raise ValueError('Every payer category was weighted to zero for this admission.')
        rng = self._rng('daily-initial-payer', stay_id)
        category = rng.choices(tuple(weights), weights=tuple(weights.values()), k=1)[0]
        return category, multiplier

    def _schedule(self, active, after):
        pending = [period['start_date'] for period in active['periods'] if period['start_date'] > after]
        if active.get('approval') is not None:
            pending.append(active['approval']['date'])
        next_day = min([active['planned_discharge'], *pending])
        if next_day <= after:
            raise ValueError('A pending ADT event predates the last completed day.')
        heappush(self._due, (next_day, active['stay']['stay_id']))

    def _save_active(self, active):
        self._put(self.adt_active_stays, dict(stay_id=active['stay']['stay_id'],
            planned_discharge=active['planned_discharge'],
            payer_plan=json.loads(json.dumps(active['periods'], default=str)),
            skilled_days=active['skilled_days'],
            medicaid_approval=None if active.get('approval') is None
                else json.loads(json.dumps(active['approval'], default=str))))

    def _approve_medicaid(self, active):
        approval = active['approval']
        stay_id = active['stay']['stay_id']
        case = self._pending_cases.pop(stay_id)
        first = active['periods'][0]
        first['payer_id'] = approval['payer_id']
        # Correct the original period: no extra period or shifted LOS start date.
        saved = dict(first)
        if first['end_date'] > self._day:
            saved.update(end_date=None, end_reason=None)
        self._put(self.res_payer_stays, saved)
        self._put(self.medicaid_applications, dict(case, approved_date=self._day,
            approved_payer_id=approval['payer_id']))
        self._approved_admissions.append(dict(approved_stay_id=stay_id, approved_payer_id=approval['payer_id']))
        active['approval'] = None
        self._save_active(active)

    def _new_resident(self, facility_id):
        while True:
            self._new_sequences[facility_id] += 1
            resident_id = self.source_id('daily-resident', str(facility_id), self._day.isoformat(),
                self._new_sequences[facility_id])
            if resident_id not in self._resident_ids:
                self._resident_ids.add(resident_id)
                break
        rng = self._rng('daily-resident-name', resident_id)
        gender = 'male' if rng.getrandbits(1) else 'female'
        for _ in range(100000):
            first, last = rng.choice(self._first_names[gender]), rng.choice(self._last_names)
            key = (first.casefold(), last.casefold())
            if key not in self._names:
                self._names.add(key)
                self._put(self.residents, dict(resident_id=resident_id, facility_id=facility_id,
                    gender=gender, first_name=first, last_name=last))
                return resident_id
        raise ValueError('Name lists are exhausted; add more names before generating new residents.')

    def _choose_resident(self, facility_id, rng, opening):
        returning = self._returning[facility_id]
        eligible = bool(returning and returning[0][0] <= self._day)
        if eligible and rng.random() < 0.65:
            return heappop(returning)[1]
        unused = self._unused[facility_id]
        if unused and (opening or rng.random() >= 0.10):
            return unused.pop()
        if eligible and not unused and rng.random() < 0.65:
            return heappop(returning)[1]
        return self._new_resident(facility_id)

    def _admit(self, facility_id, rng, *, opening=False):
        resident_id = self._choose_resident(facility_id, rng, opening)
        state = self._resident_state.get(resident_id)
        if state is None:
            limit = self._rng('admission-count', resident_id).choices(range(1, 8),
                weights=self._planner.ADMISSION_WEIGHTS, k=1)[0]
            state = self._resident_state[resident_id] = dict(resident_id=resident_id,
                admission_limit=limit, admissions=0, last_discharge=None, eligible_after=None,
                is_deceased=False, skilled_used=0)
        admitted = self._day - timedelta(days=rng.randint(1, 90)) if opening else self._day
        previous = state['last_discharge']
        if previous is None or (admitted - previous).days >= 60:
            state['skilled_used'] = 0
        if state['is_deceased'] or state['admissions'] >= state['admission_limit']:
            raise ValueError('An ineligible resident was selected for admission.')
        state['admissions'] += 1
        state['eligible_after'] = None
        stay_id = self.source_id('res-stay', str(resident_id), state['admissions'])
        remaining = self._planner.MAX_SKILLED_DAYS - state['skilled_used']
        category, medicaid_multiplier = self._admission_payer(
            facility_id, admitted, stay_id, remaining, opening)
        pending_rng = self._rng('medicaid-pending-v1', stay_id)
        starts_pending = category == 'medicaid' and pending_rng.random() < self._planner.MEDICAID_PENDING_SHARE
        approval_date = admitted + timedelta(days=pending_rng.randint(7, 14)) if starts_pending else None
        plan_rng = self._rng('daily-stay-length', stay_id)
        low, high = self._planner.stay_length_band(category, plan_rng)
        planned = plan_rng.randint(low, high)
        if category != 'medicaid':
            # Rehab-leaning facilities turn short-stay beds over faster, which is what
            # makes their higher skilled census reachable. Medicaid length is a
            # resident's own trajectory, not a facility operating choice.
            planned = max(1, round(planned * self._between(
                self.TURNOVER_RANGE, self._profiles[facility_id])))
        # Opening residents have varied remaining lengths, rather than all being
        # forced to discharge a few days after the initial snapshot.
        length = (self._day - admitted).days + planned
        discharged = admitted + timedelta(days=length)
        periods, skilled_days = self._planner._payer_periods(stay_id,
            (admitted - self.SIMULATION_START).days, (discharged - self.SIMULATION_START).days,
            False, remaining, self._catalog, facility_id=facility_id,
            initial_category=category, medicaid_multiplier=medicaid_multiplier,
            minimum_first_days=(approval_date - admitted).days + 1 if starts_pending else 1,
            skilled_mode=round(self._between(self.SKILLED_PERIOD_MODE, self._profiles[facility_id])))
        approval = None
        if starts_pending:
            approved_payer = periods[0]['payer_id']
            already_approved = approval_date <= self._day
            case = dict(stay_id=stay_id, payer_stay_id=periods[0]['payer_stay_id'], application_date=admitted,
                approved_date=approval_date if already_approved else None,
                approved_payer_id=approved_payer if already_approved else None)
            self._put(self.medicaid_applications, case)
            if not already_approved:
                periods[0]['payer_id'] = self._planner._pending_payer['payer_id']
                approval = dict(date=approval_date, payer_id=approved_payer)
                self._pending_cases[stay_id] = case
        stay = dict(stay_id=stay_id, resident_id=resident_id, facility_id=facility_id,
            admission_number=state['admissions'], admission_date=admitted, discharge_date=None)
        active = dict(stay=stay, planned_discharge=discharged, periods=periods,
            skilled_days=skilled_days, approval=approval)
        self._active[stay_id] = active
        self._schedule(active, self._day)
        self._census[facility_id] += 1
        self._medicaid_census[facility_id] += self._has_medicaid(active, self._day)
        self._skilled_census[facility_id] += self._has_skilled(active, self._day)
        self._put(self.res_stays, stay)
        self._put(self.adt_resident_state, state)
        self._save_active(active)
        for period in periods:
            if period['start_date'] <= self._day:
                saved = dict(period)
                if period['end_date'] > self._day:
                    saved.update(end_date=None, end_reason=None)
                self._put(self.res_payer_stays, saved)
        source_rng = self._rng('daily-admission-source', stay_id)
        source_type = self._admission_rules.pick_source_type(facility_id, admitted, source_rng)
        if source_type == 'Hospital':
            names, cumulative = self._hospitals[facility_id]
            source_name = source_rng.choices(names, cum_weights=cumulative, k=1)[0]
        else:
            source_name = source_rng.choice(self._admission_rules.SOURCE_NAMES[source_type])
        self._put(self.admission_logs, dict(stay_id=stay_id, admission_date=admitted,
            payer_id=periods[0]['payer_id'], source_type=source_type, source_name=source_name,
            is_readmission=state['admissions'] > 1,
            is_30_day_readmission=previous is not None and 0 <= (admitted - previous).days <= 30))

    def _discharge(self, active):
        stay, periods = active['stay'], active['periods']
        facility_id, resident_id = stay['facility_id'], stay['resident_id']
        state = self._resident_state[resident_id]
        rng = self._rng('daily-discharge', stay['stay_id'])
        deceased = rng.random() < self._discharge_rules.DECEASED_SHARE
        if deceased:
            destination = 'Funeral Home'
        else:
            weights = self._discharge_rules.DESTINATION_WEIGHTS
            destination = rng.choices(tuple(weights), weights=tuple(weights.values()), k=1)[0]
        if destination == 'Hospital':
            names, cumulative = self._hospitals[facility_id]
            name = rng.choices(names, cum_weights=cumulative, k=1)[0]
        else:
            name = rng.choice(self._discharge_rules.DESTINATION_NAMES[destination])
        # Leaving against medical advice. Deaths and acute transfers are already
        # implied by the destination, so neither is eligible and the three
        # reported outcomes stay disjoint.
        is_ama = (not deceased and destination != 'Hospital'
            and rng.random() < self._discharge_rules.AMA_SHARE)
        state.update(last_discharge=self._day, is_deceased=deceased,
            eligible_after=None if deceased or state['admissions'] >= state['admission_limit']
                else self._day + timedelta(days=rng.randint(1, 90)),
            skilled_used=state['skilled_used'] + active['skilled_days'])
        if state['eligible_after'] is not None:
            heappush(self._returning[facility_id], (state['eligible_after'], resident_id))
        self._put(self.adt_resident_state, state)
        self._put(self.res_stays, dict(stay, discharge_date=self._day))
        self._put(self.res_payer_stays, periods[-1])
        self._put(self.discharge_logs, dict(stay_id=stay['stay_id'], discharge_date=self._day,
            payer_id=periods[-1]['payer_id'], destination_type=destination, destination_name=name,
            is_deceased=deceased, is_ama=is_ama,
            los=(self._day - periods[-1]['start_date']).days))
        self._closed.append(stay['stay_id'])
        del self._active[stay['stay_id']]
        self._census[facility_id] -= 1
        self._medicaid_census[facility_id] -= periods[-1]['payer_id'] in self._medicaid_payer_ids
        self._skilled_census[facility_id] -= periods[-1]['payer_id'] in self._skilled_payer_ids
        self._discharges[facility_id] += 1

    def run_day(self, connection, day):
        self._day = day
        # Rows accumulate in the batch buffers; _touched keeps this day's own count
        # so each checkpoint still records what that date produced.
        self._touched = defaultdict(set)
        self._new_sequences = defaultdict(int)
        self._discharges = defaultdict(int)
        self._plan_month(day)
        # Opening residents arrived in late 2022; initialize before measuring Jan 1 movement.
        if day == self.SIMULATION_START:
            for facility_id, facility in self._facilities.items():
                rng = self._rng('daily-opening', facility_id)
                target = round(facility['beds'] * self._planner._occupancy_target(rng))
                target = min(facility['beds'], max(ceil(facility['beds'] * .70), target))
                for _ in range(target):
                    self._admit(facility_id, rng, opening=True)
        opening = dict(self._census)
        while self._due and self._due[0][0] <= day:
            due, stay_id = heappop(self._due)
            if due != day:
                raise ValueError('A daily event was skipped; resume from the earliest missing date.')
            active = self._active[stay_id]
            if active.get('approval') is not None and active['approval']['date'] == day:
                self._approve_medicaid(active)
            if active['planned_discharge'] == day:
                self._discharge(active)
            else:
                for index, period in enumerate(active['periods']):
                    if period['start_date'] == day:
                        facility_id = active['stay']['facility_id']
                        previous_payer = active['periods'][index - 1]['payer_id']
                        self._medicaid_census[facility_id] += (
                            int(period['payer_id'] in self._medicaid_payer_ids)
                            - int(previous_payer in self._medicaid_payer_ids))
                        self._skilled_census[facility_id] += (
                            int(period['payer_id'] in self._skilled_payer_ids)
                            - int(previous_payer in self._skilled_payer_ids))
                        self._put(self.res_payer_stays, active['periods'][index - 1])
                        self._put(self.res_payer_stays, dict(period, end_date=None, end_reason=None))
                        break
                self._schedule(active, day)
        for facility_id, facility in self._facilities.items():
            beds = facility['beds']
            if self._census[facility_id] > beds:
                raise ValueError(f'Facility {facility_id} has more active residents than its saved bed count.')
            rng = self._rng('daily-facility', facility_id, day)
            baseline = self._occupancy_baselines[facility_id]
            # Season and any current disruption move the target; the floor is low
            # enough that a real disruption is visible rather than clipped away.
            occupancy = baseline + self.SEASONAL_LIFT[day.month] - self._disruption(facility_id, day)
            target = min(beds, max(ceil(.55 * beds), round(occupancy * beds) + rng.randint(-2, 2)))
            shortfall = max(0, target - self._census[facility_id])
            admissions = round(shortfall * self.WEEKDAY_ADMISSION_RATE[day.weekday()])
            for _ in range(admissions):
                self._admit(facility_id, rng)
            if not 0 <= self._medicaid_census[facility_id] <= self._census[facility_id]:
                raise ValueError('Medicaid census is inconsistent with the active resident count.')
            if not 0 <= self._skilled_census[facility_id] <= self._census[facility_id]:
                raise ValueError('Skilled census is inconsistent with the active resident count.')
            self._put(self.adt_daily_census, dict(facility_id=facility_id, census_date=day, beds=beds,
                opening_census=opening[facility_id], admissions=admissions,
                discharges=self._discharges[facility_id], closing_census=self._census[facility_id]))
        return {table.name: len(self._touched[table.name]) for table in self.owned_tables}

    def flush_writes(self, connection):
        """Write the whole batch once, in foreign-key-safe table order.

        A stay admitted and discharged inside one batch is inserted here and then
        removed by the same closed-stay delete, leaving exactly the committed state
        that writing each day separately would have produced. Likewise a Medicaid
        approval for an admission logged in this batch writes the pending payer and
        is then corrected by the approval update, as it is across batches.
        """
        for table in self.owned_tables:
            rows = list(self._buffers[table.name].values())
            if rows:
                self.save_rows(connection, table, rows)
        if self._closed:
            for offset in range(0, len(self._closed), COPY_BATCH_SIZE):
                connection.execute(self.adt_active_stays.delete().where(
                    self.adt_active_stays.c.stay_id.in_(self._closed[offset:offset + COPY_BATCH_SIZE])))
        if self._approved_admissions:
            connection.execute(self.admission_logs.update().where(
                self.admission_logs.c.stay_id == bindparam('approved_stay_id')).values(
                    payer_id=bindparam('approved_payer_id')), self._approved_admissions)
        self._reset_batch()


DAILY_GENERATORS = (DailyAdtGenerator,)
