"""Aspire state, portfolio, region and facility generators from facilities.json."""
from base import BaseGenerator
from sqlalchemy import select


class StateGenerator(BaseGenerator):
    """One row per state, keyed by its state code."""
    name = 'states'
    table = BaseGenerator.states

    def expected_rows(self):
        return len(self.generate())

    def generate(self):
        states = {facility['state'] for facility in self.load_facilities()}
        return [dict(state=state) for state in sorted(states)]


class PortfolioGenerator(BaseGenerator):
    """One portfolio per state, with region, facility and capacity counts."""
    name = 'portfolios'
    table = BaseGenerator.portfolios

    def prepare_sources(self, connection):
        self._state_keys = {row['state']: row['state']
            for row in self.read_rows(connection, select(self.states.c.state))}

    def expected_rows(self):
        return len(self.generate())

    def generate(self):
        groups = {}
        for facility in self.load_facilities():
            key = (facility['state'], facility['portfolio'])
            group = groups.setdefault(key, dict(regions=set(), facilities=0, beds=0))
            group['regions'].add(facility['market'])
            group['facilities'] += 1
            group['beds'] += facility['beds']
        return [dict(portfolio_id=self.source_id('portfolio', state, portfolio),
            state=self.parent_key(self._state_keys, state, 'states'),
            portfolio=portfolio, region_count=len(group['regions']),
            facility_count=group['facilities'], total_beds=group['beds'])
            for (state, portfolio), group in sorted(groups.items())]


class RegionGenerator(BaseGenerator):
    """One region per portfolio, using the source market field."""
    name = 'regions'
    table = BaseGenerator.regions

    def prepare_sources(self, connection):
        self._portfolio_keys = {(row['state'], row['portfolio']): row['portfolio_id']
            for row in self.read_rows(connection, select(self.portfolios.c.portfolio_id,
                self.portfolios.c.state, self.portfolios.c.portfolio))}

    def expected_rows(self):
        return len(self.generate())

    def generate(self):
        groups = {}
        for facility in self.load_facilities():
            key = (facility['state'], facility['portfolio'], facility['market'])
            group = groups.setdefault(key, dict(facilities=0, beds=0))
            group['facilities'] += 1
            group['beds'] += facility['beds']
        return [dict(region_id=self.source_id('region', state, portfolio, region),
            portfolio_id=self.parent_key(self._portfolio_keys, (state, portfolio), 'portfolios'),
            region=region,
            facility_count=group['facilities'], total_beds=group['beds'])
            for (state, portfolio, region), group in sorted(groups.items())]


class FacilityGenerator(BaseGenerator):
    """One facility row linked to its parent region."""
    name = 'facilities'
    table = BaseGenerator.facilities

    def prepare_sources(self, connection):
        self._region_keys = {(row['state'], row['portfolio'], row['region']): row['region_id']
            for row in self.read_rows(connection, select(self.regions.c.region_id,
                self.regions.c.region, self.portfolios.c.state, self.portfolios.c.portfolio)
                .select_from(self.regions.join(self.portfolios)))}

    def expected_rows(self):
        return len(self.generate())

    def generate(self):
        rows = []
        for facility in self.load_facilities():
            parent = (facility['state'], facility['portfolio'], facility['market'])
            rows.append(dict(facility_id=self.source_id('facility', *parent, facility['facility']),
                region_id=self.parent_key(self._region_keys, parent, 'regions'),
                facility=facility['facility'], beds=facility['beds']))
        return rows


# Export every generator in this file; BaseGenerator owns their execution order.
GENERATORS = (StateGenerator, PortfolioGenerator, RegionGenerator, FacilityGenerator)
