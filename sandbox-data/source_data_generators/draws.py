"""Stable random draws in SQL, for generators whose rows must come out the same
on every rebuild: each draw is the md5 of a text seed -- an id and what is being
drawn -- not a random number generator.

Used by the incident and infection generators; listed in SHARED_RULES in
generator_rules.py for both, so a change here rebuilds them.
"""


def draw(seed):
    """A stable draw in [0, 1) from a SQL text expression: 32 bits of its md5."""
    return f"(('x' || lpad(substr(md5({seed}), 1, 8), 16, '0'))::bit(64)::bigint / 4294967296.0)"


def pick(draw_sql, values, weights):
    """The value a draw in [0, 1) lands on, by cumulative weights; values are SQL
    literals. A zero weight is never picked."""
    total, edges, running = sum(weights), [], 0
    for value, weight in zip(values, weights):
        if weight == 0:
            continue
        running += weight
        edges.append((value, running / total))
    return 'CASE ' + ' '.join(f'WHEN {draw_sql} < {edge} THEN {value}' for value, edge in edges[:-1]) \
        + f' ELSE {edges[-1][0]} END'
