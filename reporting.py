"""Pure filtering and aggregation shared by server-generated usage reports."""
from collections import Counter
from datetime import date, timedelta

FILTER_KEYS = ('subject', 'deweyClass', 'resourceId', 'userSegment', 'format')
GROUPINGS = {'DAILY', 'WEEKLY', 'MONTHLY', 'SEASONAL'}

def validate_criteria(criteria):
    criteria = dict(criteria or {})
    start, end = criteria.get('start', ''), criteria.get('end', '')
    if bool(start) != bool(end):
        raise ValueError('Start and end dates must both be supplied.')
    if start:
        try:
            if str(date.fromisoformat(start)) != start or str(date.fromisoformat(end)) != end or start > end:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('Enter valid dates with the start on or before the end.')
    if criteria.get('grouping', 'MONTHLY') not in GROUPINGS:
        raise ValueError('Choose a valid time grouping.')
    for key in FILTER_KEYS:
        values = criteria.get(key, [])
        if isinstance(values, str): values = [values] if values else []
        if not isinstance(values, list) or len(values) > 500 or any(not isinstance(v,str) or len(v)>300 for v in values):
            raise ValueError('Invalid filter selection.')
        criteria[key] = values
    return criteria

def filter_rows(records, criteria):
    c = validate_criteria(criteria)
    return [r for r in records if
            (not c.get('start') or c['start'] <= r['checkoutDate'] <= c['end']) and
            all(not c[k] or r[k] in c[k] for k in FILTER_KEYS)]

def aggregate(records, grouping='MONTHLY'):
    returned = [r for r in records if r['returnStatus'] in {'RETURNED_ON_TIME', 'RETURNED_LATE'}]
    periods = Counter()
    for r in records:
        day = date.fromisoformat(r['checkoutDate'])
        label = r['checkoutDate']
        if grouping == 'WEEKLY': label = str(day - timedelta(days=day.weekday()))
        elif grouping == 'MONTHLY': label = label[:7]
        elif grouping == 'SEASONAL': label = f"{day.year} · {['01 Winter','02 Spring','03 Summer','04 Autumn'][(day.month-1)//3]}"
        periods[label] += 1
    counts = Counter(r['resourceId'] for r in records)
    titles = {r['resourceId']: r['title'] for r in records}
    return {
        'totalCheckouts': len(records),
        'uniqueReaders': len({r['anonymizedReaderId'] for r in records}),
        'onTimeRate': 100 * sum(r['returnStatus'] == 'RETURNED_ON_TIME' for r in returned) / len(returned) if returned else None,
        'subjects': dict(Counter(r['subject'] for r in records)),
        'formats': dict(Counter(r['format'] for r in records)),
        'segments': dict(Counter(r['userSegment'] for r in records)),
        'months': dict(sorted(periods.items())),
        'resources': {f'{titles[key]} ({key})': count for key,count in counts.items()},
        'resourcesUsed': len(counts),
        'dateFrom': min((r['checkoutDate'] for r in records), default=None),
        'dateTo': max((r['checkoutDate'] for r in records), default=None),
    }
