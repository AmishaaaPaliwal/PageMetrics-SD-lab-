"""Pure filtering and aggregation shared by server-generated usage reports."""
from collections import Counter
from datetime import date, timedelta

# Fields supporting one or several selected values.
FILTER_KEYS = ('subject', 'deweyClass', 'resourceId', 'userSegment', 'format')
# Accepted time buckets for reporting.
GROUPINGS = {'DAILY', 'WEEKLY', 'MONTHLY', 'SEASONAL'}

# Validate date ranges and time grouping, and normalize every filter into a list.
def validate_criteria(criteria):
    # Copy caller data so normalization does not mutate the supplied dictionary.
    criteria = dict(criteria or {})
    # Read the optional inclusive date range.
    start, end = criteria.get('start', ''), criteria.get('end', '')
    # Require both ends of the range or neither.
    if bool(start) != bool(end):
        raise ValueError('Start and end dates must both be supplied.')
    if start:
        try:
            # Reject impossible dates, noncanonical formatting and reversed ranges.
            if str(date.fromisoformat(start)) != start or str(date.fromisoformat(end)) != end or start > end:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('Enter valid dates with the start on or before the end.')
    # Reject unknown time-grouping names before aggregation.
    if criteria.get('grouping', 'MONTHLY') not in GROUPINGS:
        raise ValueError('Choose a valid time grouping.')
    # Normalize each selectable field and bound input size.
    for key in FILTER_KEYS:
        values = criteria.get(key, [])
        # Convert a single selected value into the same representation as multiselect values.
        if isinstance(values, str): values = [values] if values else []
        # Reject malformed or oversized filter selections.
        if not isinstance(values, list) or len(values) > 500 or any(not isinstance(v,str) or len(v)>300 for v in values):
            raise ValueError('Invalid filter selection.')
        criteria[key] = values
    return criteria

# Combine fields with AND; within each selected field, accept any selected value.
def filter_rows(records, criteria):
    # Use the validated and normalized criteria for filtering.
    c = validate_criteria(criteria)
    # An empty selection includes every value; selected values must match the record.
    return [r for r in records if
            (not c.get('start') or c['start'] <= r['checkoutDate'] <= c['end']) and
            all(not c[k] or r[k] in c[k] for k in FILTER_KEYS)]

# Compute totals, unique readers, known-return punctuality, and grouped circulation counts.
def aggregate(records, grouping='MONTHLY'):
    # Outstanding and unknown-status loans do not enter the on-time percentage denominator.
    returned = [r for r in records if r['returnStatus'] in {'RETURNED_ON_TIME', 'RETURNED_LATE'}]
    # Count checkouts by the selected date bucket.
    periods = Counter()
    for r in records:
        # Parse each checkout date for weekly and seasonal grouping.
        day = date.fromisoformat(r['checkoutDate'])
        label = r['checkoutDate']
        # Weekly buckets start on Monday; monthly and seasonal buckets use calendar components.
        if grouping == 'WEEKLY': label = str(day - timedelta(days=day.weekday()))
        elif grouping == 'MONTHLY': label = label[:7]
        elif grouping == 'SEASONAL': label = f"{day.year} · {['01 Winter','02 Spring','03 Summer','04 Autumn'][(day.month-1)//3]}"
        periods[label] += 1
    # Count circulation per resource identifier.
    counts = Counter(r['resourceId'] for r in records)
    # Associate each resource identifier with its display title.
    titles = {r['resourceId']: r['title'] for r in records}
    return {
        'totalCheckouts': len(records),
        # Deduplicate anonymous reader tokens for the readership KPI.
        'uniqueReaders': len({r['anonymizedReaderId'] for r in records}),
        # Return None when there are no known returns, allowing the UI to display N/A.
        'onTimeRate': 100 * sum(r['returnStatus'] == 'RETURNED_ON_TIME' for r in returned) / len(returned) if returned else None,
        'subjects': dict(Counter(r['subject'] for r in records)),
        'formats': dict(Counter(r['format'] for r in records)),
        'segments': dict(Counter(r['userSegment'] for r in records)),
        # Keep the existing response field name for every grouping and return periods in sorted order.
        'months': dict(sorted(periods.items())),
        'resources': {f'{titles[key]} ({key})': count for key,count in counts.items()},
        'resourcesUsed': len(counts),
        'dateFrom': min((r['checkoutDate'] for r in records), default=None),
        'dateTo': max((r['checkoutDate'] for r in records), default=None),
    }
