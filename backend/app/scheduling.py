"""Cross-source availability checks for LTMP assignments.

All-day legacy assignment rows overlap any slot on their dates. Optional
StartTime/EndTime add slot granularity without a destructive DB migration.
Conflicts are validated again at commit: the browser's preview is advisory.
"""
from datetime import datetime, time
from fastapi import HTTPException
from .identifiers import username as normalized_username
from .queries import rows, s, active_assignment

ACTIVE_EXTERNAL = {'Running', 'Upcoming', 'On Hold'}


def _day(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(s(value).replace('Z', '+00:00')).date()
    except ValueError:
        return None


def _time(value):
    if value in ('', None):
        return None
    try:
        return time.fromisoformat(s(value).strip())
    except ValueError:
        raise HTTPException(400, 'Time slot must use HH:MM format')


def validate_slot(start, end, start_time=None, end_time=None, require_dates=False):
    start_day, end_day = _day(start), _day(end)
    if require_dates and (not start_day or not end_day):
        raise HTTPException(400, 'Assignment requires valid start and end dates')
    if bool(start) != bool(end) or (start and (not start_day or not end_day)):
        raise HTTPException(400, 'Provide valid start and end dates together')
    if start_day and end_day and end_day < start_day:
        raise HTTPException(400, 'End date cannot precede start date')
    a, b = _time(start_time), _time(end_time)
    if (a is None) != (b is None):
        raise HTTPException(400, 'Enter both start and end time for a time slot')
    if a is not None and b <= a:
        raise HTTPException(400, 'End time must be later than start time')
    if a is not None and not start_day:
        raise HTTPException(400, 'Time slot needs assignment dates')
    return start_day, end_day, a, b


def _overlaps(a, b):
    first_start, first_end, first_time, first_time_end = a
    second_start, second_end, second_time, second_time_end = b
    if not first_start or not second_start:
        return False  # unscheduled historical rows do not imply occupancy
    if first_end < second_start or second_end < first_start:
        return False
    # An unspecified time means all day. Touching boundaries are not an overlap.
    if first_time is None or second_time is None:
        return True
    return first_time < second_time_end and second_time < first_time_end


def conflicts(db, trainer_username, start, end, start_time='', end_time='',
              exclude_type='', exclude_id='', exclude_category=''):
    target = normalized_username(trainer_username)
    candidate = validate_slot(start, end, start_time, end_time)
    if not target or not candidate[0]:
        return []
    found = []
    college_names = {s(x.get('CollegeCode')): s(x.get('CollegeName')) for x in rows(db, 'Colleges')}
    for x in rows(db, 'TrainerAssignments'):
        if not active_assignment(x) or normalized_username(x.get('TrainerUsername')) != target:
            continue
        college_id = s(x.get('CollegeCode'))
        if (exclude_type == 'lesuccess' and college_id == s(exclude_id)
                and s(x.get('Category')).casefold() == s(exclude_category).casefold()):
            continue
        existing = validate_slot(x.get('FromDate'), x.get('ToDate'),
                                 x.get('StartTime'), x.get('EndTime'))
        if _overlaps(candidate, existing):
            found.append({'type': 'lesuccess', 'projectId': college_id,
                'projectName': college_names.get(college_id, college_id),
                'batch': s(x.get('Batch')) or s(x.get('Category')),
                'location': s(x.get('Location')), 'startDate': s(x.get('FromDate')),
                'endDate': s(x.get('ToDate')), 'startTime': s(x.get('StartTime')),
                'endTime': s(x.get('EndTime')), 'reason': 'session'})
    for typ, sheet in (('vendor', 'VendorProjects'), ('freelance', 'FreelanceProjects')):
        for x in rows(db, sheet):
            if (s(x.get('Status') or 'Running') not in ACTIVE_EXTERNAL or
                    s(x.get('ProjectID')) == s(exclude_id) and typ == exclude_type):
                continue
            # This helper handles legacy full-name assignment as well as Employee IDs.
            from .unified_projects import project_owner
            if project_owner(db, x) != target:
                continue
            existing = validate_slot(x.get('StartDate'), x.get('EndDate'),
                                     x.get('StartTime'), x.get('EndTime'))
            if _overlaps(candidate, existing):
                found.append({'type': typ, 'projectId': s(x.get('ProjectID')),
                    'projectName': s(x.get('CollegeName')) or s(x.get('Vendor')),
                    'batch': s(x.get('Batch')) or s(x.get('Category')),
                    'location': s(x.get('Location')), 'startDate': s(x.get('StartDate')),
                    'endDate': s(x.get('EndDate')), 'startTime': s(x.get('StartTime')),
                    'endTime': s(x.get('EndTime')), 'reason': 'session'})
    for x in rows(db, 'LeaveRequests'):
        if (normalized_username(x.get('EmployeeUsername')) != target or
                s(x.get('Status')) != 'Approved'):
            continue
        existing = validate_slot(x.get('StartDate'), x.get('EndDate'))
        if _overlaps(candidate, existing):
            found.append({'type': 'leave', 'projectId': s(x.get('LeaveID')),
                          'projectName': 'Approved leave', 'batch': '', 'location': '',
                          'startDate': s(x.get('StartDate')), 'endDate': s(x.get('EndDate')),
                          'startTime': '', 'endTime': '', 'reason': 'leave'})
    return found


def check(db, actor, data):
    from sqlalchemy import select
    from .db import User
    normalized = normalized_username(data.get('trainerUsername'))
    trainer = db.scalar(select(User).where(User.username == normalized, User.role == 'Trainer'))
    if not trainer or not trainer.active:
        raise HTTPException(400, 'Choose an active Trainer Employee ID')
    # Preview validates dates/slots even if there is no existing conflict.
    validate_slot(data.get('startDate') or data.get('fromDate'),
                  data.get('endDate') or data.get('toDate'),
                  data.get('startTime'), data.get('endTime'))
    items = conflicts(db, normalized, data.get('startDate') or data.get('fromDate'),
                      data.get('endDate') or data.get('toDate'),
                      data.get('startTime'), data.get('endTime'),
                      data.get('projectType',''), data.get('projectId',''), data.get('category',''))
    return {'available': not items, 'is_occupied': bool(items), 'conflicts': items,
            'alerts': [{'type': x['type'], 'message': f"{x['projectName']} — {x['startDate']} to {x['endDate']}"} for x in items]}


def enforce(db, actor, data, *, start_key='startDate', end_key='endDate',
            exclude_type='', exclude_id='', exclude_category=''):
    """No partial rows written when an occupied Trainer was not acknowledged."""
    if not normalized_username(data.get('trainerUsername')):
        return []  # A free-text external freelancer is not a portal assignment.
    if s(data.get('status') or data.get('assignmentStatus') or 'Running') not in ACTIVE_EXTERNAL:
        return []
    # A booking without dates cannot be checked for double-booking. Old source
    # records remain readable; new active portal assignments require dates.
    validate_slot(data.get(start_key), data.get(end_key), data.get('startTime'),
                  data.get('endTime'), require_dates=True)
    # Serialize concurrent assignment writes for the same trainer on PostgreSQL.
    # A preflight browser check alone cannot close the race between two Admins.
    from sqlalchemy import select
    from .db import User
    db.execute(select(User.id).where(User.username == normalized_username(data.get('trainerUsername'))).with_for_update()).first()
    checked = conflicts(db, data.get('trainerUsername'), data.get(start_key),
                        data.get(end_key), data.get('startTime'), data.get('endTime'),
                        exclude_type, exclude_id, exclude_category)
    if checked and not data.get('acknowledgeConflict'):
        raise HTTPException(409, {'message': 'Trainer is already occupied. Cancel or ask Admin to Override & Proceed.',
                                  'is_occupied': True, 'conflicts': checked})
    if checked and actor.role != 'Admin':
        raise HTTPException(403, 'Only Admin may override a double-booked trainer')
    return checked
