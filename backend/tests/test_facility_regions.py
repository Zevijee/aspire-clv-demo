from collections import Counter

import pytest
from app.seeding.facilities import build_facility_rows, validate_region_sizes


def test_regions_are_balanced_within_each_portfolio():
    rows = build_facility_rows()
    counts = Counter((row['state'], row['portfolio'], row['region']) for row in rows)
    assert len(rows) == 253
    assert len({row['facility_code'] for row in rows}) == 253
    assert len({row['name'] for row in rows}) == 253
    assert len(counts) == 22
    assert all(5 <= count <= 15 for count in counts.values())
    assert Counter(row['state'] for row in rows) == {'TX': 164, 'FL': 76, 'PA': 13}
    for portfolio in {row['portfolio'] for row in rows}:
        sizes = [count for (_, owner, _), count in counts.items() if owner == portfolio]
        assert max(sizes) - min(sizes) <= 1
    assert build_facility_rows() == rows


@pytest.mark.parametrize('size', [1, 4, 16])
def test_region_validation_rejects_out_of_range_sizes(size):
    with pytest.raises(ValueError, match='Each region must contain'):
        validate_region_sizes([{'state': 'TX', 'portfolio': 'Example', 'region': 'North'}] * size)


def test_region_bounds_are_inclusive_and_names_are_scoped_to_portfolio():
    rows = [dict(state='TX', portfolio='First', region='North')] * 5
    rows += [dict(state='TX', portfolio='Second', region='North')] * 15
    validate_region_sizes(rows)
