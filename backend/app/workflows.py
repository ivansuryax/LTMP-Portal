"""LTMP workflow migration from supplied Apps Script Code.gs.

RPC names and response envelopes match the original UI. Each request is executed in
one SQL transaction by main.rpc. Actor identity always comes from session cookie,
not from actorUsername fields provided by the browser.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from .db import SheetRow, User
from .identifiers import username as normalize_username
from .queries import colleges, d, n, rows, s

MANAGEMENT = {'Team Leader', 'Reporting Manager', 'Admin'}
DIRECT_ROLE = {'Team Leader': 'Trainer', 'Reporting Manager': 'Team Leader', 'Admin': 'Reporting Manager'}
SUBMITTERS = {'Trainer', 'Team Leader', 'Reporting Manager'}
STATUSES = {'Upcoming', 'Running', 'On Hold', 'Completed', 'Not Active'}


def now():
    return datetime.now(timezone.utc).isoformat()


def lower(value):
    return normalize_username(value)


def date_only(value):
    value = s(value).strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).date()
    except ValueError:
        try:
            return datetime.strptime(value, '%d %b %Y').date()
        except ValueError:
            return None


def as_date(value):
    date_value = date_only(value)
    return date_value.isoformat() if date_value else ''


def overlap(a, b, x, y):
    a, b, x, y = map(date_only, (a, b, x, y))
    return bool(a and b and x and y and a <= y and x <= b)


def working_days(start, end):
    start, end = date_only(start), date_only(end)
    if not start or not end or end < start or (end - start).days > 730:
        return 0
    return sum((start + timedelta(days=i)).weekday() != 6 for i in range((end - start).days + 1))


def fail(message):
    return {'success': False, 'message': message}


def ok(**extra):
    return {'success': True, **extra}


def arg(args, i, default=''):
    return args[i] if len(args) > i else default


def payload(args):
    p = arg(args, 0)
    if not isinstance(p, dict):
        raise HTTPException(400, 'Payload object required')
    return p


def admin(actor):
    if actor.role != 'Admin':
        raise HTTPException(403, 'Admin role required')


def manager(actor):
    if actor.role not in MANAGEMENT:
        raise HTTPException(403, 'Manager role required')


def submitter(actor):
    if actor.role not in SUBMITTERS:
        raise HTTPException(403, 'Submitter role required')


def self_only(actor, supplied):
    if lower(supplied) != actor.username:
        raise HTTPException(403, 'Cannot access or act as another employee')


def person(db, username):
    return db.scalar(select(User).where(User.username == lower(username)))


def sheet_objects(db, name):
    return list(db.scalars(select(SheetRow).where(SheetRow.sheet_name == name).order_by(SheetRow.source_row)))


def find(db, sheet, key, value):
    return next((r for r in sheet_objects(db, sheet) if lower(r.data.get(key)) == lower(value)), None)


def insert(db, sheet, data):
    value = db.scalar(select(func.max(SheetRow.source_row)).where(SheetRow.sheet_name == sheet)) or 1
    db.add(SheetRow(sheet_name=sheet, source_row=value + 1, data=data))
    db.flush()  # reserve the row number before another insert in this same RPC


def amend(r, **changes):
    r.data = {**r.data, **changes}


def alert(db, kind, recipient, message, related_leave='', related_assignment=''):
    insert(db, 'Alerts', {'AlertID': str(uuid4()), 'AlertType': kind,
        'RecipientUserID': recipient, 'RecipientRole': '', 'RelatedLeaveID': related_leave,
        'RelatedAssignmentID': related_assignment, 'Message': message,
        'AlertStatus': 'Unread', 'CreatedOn': now(), 'ReadOn': ''})


def get_team(db, actor):
    return [u for u in db.scalars(select(User)) if lower(u.reporting_manager_username) == actor.username]


def assignment_history(db, item, previous, next_status, actor, comments=''):
    insert(db, 'StatusHistory', {'StatusTimelineID': str(uuid4()),
        'CollegeCode': item.get('CollegeCode', ''), 'AssignmentID': item.get('AssignmentID', ''),
        'TrainerUsername': item.get('TrainerUsername', ''),
        'Activity': 'Assignment Status: ' + (previous + ' → ' if previous else '') + next_status,
        'PreviousStatus': previous, 'NewStatus': next_status,
        'Date': now(), 'RecordedBy': actor.username, 'Comments': comments})


def trainer_availability(db, trainer, start, end):
    conflicts = []
    for r in rows(db, 'LeaveRequests'):
        if lower(r.get('EmployeeUsername')) == lower(trainer) and r.get('Status') == 'Approved' and overlap(start, end, r.get('StartDate'), r.get('EndDate')):
            conflicts.append({'type': 'leave', 'message': 'Approved leave overlaps selected dates.'})
    return {'available': not conflicts, 'alerts': conflicts}




def current_assignment(r):
    state = s(r.get('AssignmentStatus') or 'Upcoming')
    marker = r.get('CurrentAssignment')
    return state in ('Running', 'Upcoming', 'On Hold') and s(marker).lower() not in ('false', '0', 'no')


def syllabus_approver(db, actor, trainer_id):
    if actor.role == 'Admin':
        return True
    if actor.role != 'Reporting Manager':
        return False
    employee = person(db, trainer_id)
    seen = set()
    while employee and employee.username not in seen:
        seen.add(employee.username)
        if lower(employee.reporting_manager_username) == actor.username:
            return True
        employee = person(db, employee.reporting_manager_username)
    return False

def daily_activity_dict(r, show_name=False):
    data = r.data if isinstance(r, SheetRow) else r
    result = {'entryID': s(data.get('EntryID')), 'date': d(data.get('Date')),
              'activityCode': s(data.get('ActivityCode')), 'activityName': s(data.get('ActivityName')),
              'collegeName': s(data.get('CollegeName')), 'classMode': s(data.get('ClassMode')),
              'topicCovered': s(data.get('TopicCovered')), 'hours': n(data.get('Hours')),
              'status': s(data.get('Status') or 'Pending'),
              'approverUsername': s(data.get('ApproverUsername')),
              'submittedOn': d(data.get('SubmittedOn')), 'reviewComments': s(data.get('ReviewComments'))}
    if show_name:
        result['trainerName'] = s(data.get('TrainerName'))
        result['trainerUsername'] = s(data.get('TrainerUsername'))
    return result


def leave_dict(r):
    return {'leaveID': s(r.get('LeaveID')), 'employeeUsername': s(r.get('EmployeeUsername')),
            'employeeName': s(r.get('EmployeeName')), 'role': s(r.get('Role')),
            'reportingManagerUsername': s(r.get('ReportingManagerUsername')),
            'startDate': d(r.get('StartDate')), 'endDate': d(r.get('EndDate')),
            'numberOfDays': n(r.get('NumberOfDays')), 'comments': s(r.get('Comments')),
            'status': s(r.get('Status') or 'Pending'), 'submittedOn': d(r.get('SubmittedOn')),
            'reviewedBy': s(r.get('ReviewedBy')), 'reviewedOn': d(r.get('ReviewedOn')),
            'reviewComments': s(r.get('ReviewComments'))}


def kpi_master(db):
    return [{'id': int(n(r.get('id'))), 'category': s(r.get('category')),
             'parameter': s(r.get('parameter')), 'target': display_target(r.get('target'))}
            for r in rows(db, 'KPI Master') if s(r.get('id')).strip()]


def display_target(target):
    """Excel 5% can arrive from openpyxl as 0.05, not the string '5%'."""
    raw = s(target).strip()
    if isinstance(target, (float, int)) and 0 < float(target) <= 1:
        return f'{float(target) * 100:g}%'
    return raw


def weight(target):
    import re
    raw = display_target(target)
    m = re.match(r'^(\d+(?:\.\d+)?)\s*%', raw)
    if m:
        return float(m.group(1))
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 10.0


def kpi_data(db, actor):
    master = kpi_master(db)
    evaluations = {s(r.get('recordKey')): r for r in rows(db, 'Evaluations')}
    everybody = list(db.scalars(select(User)))
    direct = [u for u in everybody if lower(u.reporting_manager_username) == actor.username and u.role == DIRECT_ROLE[actor.role]] if actor.role in MANAGEMENT else []
    if actor.role in MANAGEMENT:
        stamped = {lower(r.get('employeeId')) for r in evaluations.values() if lower(r.get('approverId')) == actor.username}
        direct = [u for u in everybody if u.username in stamped or (u in direct and not any(
            lower(r.get('employeeId')) == u.username and s(r.get('status')) == 'Submitted' and
            lower(r.get('approverId')) != actor.username for r in evaluations.values()))]

    def build(people):
        out = []
        for u in people:
            for k in master:
                key = f"{k['id']}_{u.username}"
                row = evaluations.get(key, {})
                rv = row.get('trainerRating')
                out.append({'id': key, 'kpiId': k['id'], 'employeeId': u.username,
                    'employeeName': u.full_name, 'employeeRole': u.role, **{x: k[x] for x in ('category', 'parameter', 'target')},
                    'rating': None if rv is None or rv == '' else n(rv), 'status': s(row.get('status') or 'Pending'),
                    'locked': s(row.get('locked')).lower() in ('true', '1'),
                    'submittedDate': d(row.get('trainerSubmittedDate')) or None,
                    'approvedDate': d(row.get('rmSubmittedDate')) or None,
                    'approverId': s(row.get('approverId')) or None,
                    'approverRole': s(row.get('approverRole')) or None,
                    'returnReason': s(row.get('returnReason')) or None})
        return out
    return {'myKpis': build([actor]), 'teamKpis': build(direct)}


def leave_alerts(db, actor):
    out = []
    for r in rows(db, 'LeaveRequests'):
        status = s(r.get('Status'))
        responsible = lower(r.get('ReportingManagerUsername')) == actor.username
        if status == 'Pending' and responsible and actor.role in MANAGEMENT:
            out.append({'level': 'yellow', 'group': 'pending',
                'message': s(r.get('EmployeeName')) + ' has a leave request awaiting your review.', 'leaveID': s(r.get('LeaveID'))})
        if status == 'Approved' and date_only(r.get('EndDate')) and date_only(r.get('EndDate')) >= date.today() and s(r.get('Role')) == 'Trainer' and (actor.role == 'Admin' or responsible and actor.role in MANAGEMENT):
            out.append({'level': 'blue', 'group': 'attention', 'message': s(r.get('EmployeeName')) + ' has approved leave. Check availability before assignment.', 'leaveID': s(r.get('LeaveID'))})
    return out


def missing_activity_alerts(db, actor):
    if actor.role not in MANAGEMENT:
        return []
    yesterday = date.today() - timedelta(days=1)
    if yesterday.weekday() == 6:
        yesterday -= timedelta(days=1)
    submitted = {lower(r.get('TrainerUsername')) for r in rows(db, 'DailyActivityTracker') if date_only(r.get('Date')) == yesterday}
    on_leave = {lower(r.get('EmployeeUsername')) for r in rows(db, 'LeaveRequests')
        if r.get('Status') == 'Approved' and overlap(yesterday, yesterday, r.get('StartDate'), r.get('EndDate'))}
    return [{'level': 'red', 'group': 'attention', 'message':
             (u.full_name or u.username) + ' has not submitted the Daily Tracker for ' + yesterday.strftime('%d %b %Y') + '.'}
            for u in get_team(db, actor) if u.active and u.username not in submitted and u.username not in on_leave]


def get_alerts(db, actor):
    output = []
    logs = rows(db, 'DailyTrainingLog')
    syllabus = rows(db, 'Syllabus')
    # College-wide operational alerts belong to managers, not all Trainers.
    for col in colleges(db) if actor.role in MANAGEMENT else []:
        if col['status'] == 'Running':
            base = {'collegeCode': col['collegeCode'], 'collegeName': col['collegeName'],
                    'collegeLogo': col['logoURL']}
            notes = []
            if not col['trainerCount']:
                notes.append(('blue', 'attention', 'No Trainer Assigned Yet'))
            else:
                recent = [date_only(r.get('Date')) for r in logs if s(r.get('CollegeCode')) == col['collegeCode']]
                recent = [v for v in recent if v]
                if not recent:
                    notes.append(('red', 'attention', 'No Training Updates Logged Yet'))
                elif (date.today() - max(recent)).days >= 3:
                    notes.append(('red', 'attention', f'{(date.today() - max(recent)).days} Days Behind Schedule — No Recent Training Update'))
                pending = sum(1 for r in syllabus if r.get('CollegeCode') == col['collegeCode'] and r.get('RMStatus') == 'Pending')
                if pending:
                    notes.append(('yellow', 'pending', f'{pending} Syllabus Topic(s) Waiting on Your Approval'))
                if not notes:
                    notes.append(('green', 'ontrack', 'On Track — No Action Needed'))
            output.extend({**base, 'level': level, 'group': group, 'message': message} for level, group, message in notes)
        elif col['status'] == 'On Hold':
            output.append({'collegeCode': col['collegeCode'], 'collegeName': col['collegeName'],
                'collegeLogo': col['logoURL'], 'level': 'orange', 'group': 'onhold', 'message': 'Training On Hold'})
    # Only the exact recipient may read persistent in-app assignment notices.
    assignment_by_id = {s(x.get('AssignmentID')): x for x in rows(db, 'TrainerAssignments')}
    college_by_code = {c['collegeCode']: c for c in colleges(db)}
    for note in rows(db, 'Alerts'):
        if lower(note.get('RecipientUserID')) != actor.username or s(note.get('AlertStatus')) != 'Unread':
            continue
        kind = s(note.get('AlertType'))
        if kind in ('Daily Tracker Approved', 'Daily Tracker Rejected', 'Daily Tracker Submitted'):
            output.append({'notificationID': s(note.get('AlertID')), 'collegeCode': '',
                'collegeName': 'Daily Tracker', 'collegeLogo': '',
                'level': 'blue', 'group': 'attention', 'message': s(note.get('Message'))})
            continue
        if kind == 'Schedule Override':
            output.append({'notificationID': s(note.get('AlertID')), 'collegeCode': '',
                'collegeName': 'Scheduling', 'collegeLogo': '',
                'level': 'orange', 'group': 'attention', 'message': s(note.get('Message'))})
            continue
        if kind not in ('Trainer Assigned', 'Assignment Updated', 'Assignment Replaced'):
            continue
        assignment = assignment_by_id.get(s(note.get('RelatedAssignmentID')), {})
        code = s(assignment.get('CollegeCode'))
        college = college_by_code.get(code, {})
        output.append({'notificationID': s(note.get('AlertID')), 'collegeCode': code,
                       'collegeName': college.get('collegeName') or 'Training Assignment',
                       'collegeLogo': college.get('logoURL', ''),
                       'level': 'blue', 'group': 'attention',
                       'message': s(note.get('Message'))})
    from .unified_projects import external_assignment_notices
    output.extend(external_assignment_notices(db, actor))
    output.extend({'collegeCode': '', 'collegeName': 'Leave Management', 'collegeLogo': '', **x} for x in leave_alerts(db, actor))
    if actor.role in MANAGEMENT:
        pending = sum(1 for r in rows(db, 'DailyActivityTracker') if
            lower(r.get('ApproverUsername') or (person(db, r.get('TrainerUsername')).reporting_manager_username
                if person(db, r.get('TrainerUsername')) else '')) == actor.username and s(r.get('Status')) == 'Pending')
        if pending:
            output.append({'collegeCode': '', 'collegeName': 'Daily Tracker', 'collegeLogo': '', 'level': 'yellow', 'group': 'pending', 'message': f'{pending} Daily Tracker entries awaiting your review.'})
        output.extend({'collegeCode': '', 'collegeName': 'Daily Tracker', 'collegeLogo': '', **x} for x in missing_activity_alerts(db, actor))
    kpi = kpi_data(db, actor)
    for flag, cases, message, color in (
        ('Pending', kpi['myKpis'], 'KPI parameter(s) still need your rating.', 'yellow'),
        ('Returned', kpi['myKpis'], 'KPI rating(s) were returned to you.', 'red'),
        ('Submitted', kpi['teamKpis'], 'team KPI rating(s) awaiting your approval.', 'yellow')):
        count = sum(r['status'] == flag for r in cases)
        if count:
            output.append({'collegeCode': '', 'collegeName': 'KPI', 'collegeLogo': '',
                'level': color, 'group': 'attention' if flag == 'Returned' else 'pending', 'message': f'{count} {message}'})
    return output


def handle(db, actor, name, args):
    """Return (handled: bool, result). Unknown operations remain explicitly 501."""
    if name in ('getStatusHistory', 'getTrainerAssignmentStatusTimeline'):
        if name == 'getStatusHistory':
            code = s(arg(args, 0))
            if actor.role == 'Trainer' and not any(
                s(r.get('CollegeCode')) == code and lower(r.get('TrainerUsername')) == actor.username
                for r in rows(db, 'TrainerAssignments')):
                raise HTTPException(403, 'Not assigned to this college')
            return True, [r for r in rows(db, 'StatusHistory') if s(r.get('CollegeCode')) == code]
        assignment = s(arg(args, 0))
        if actor.role == 'Trainer' and not any(
            s(r.get('AssignmentID')) == assignment and lower(r.get('TrainerUsername')) == actor.username
            for r in rows(db, 'TrainerAssignments')):
            raise HTTPException(403, 'Not your trainer assignment')
        names = {u.username: u.full_name for u in db.scalars(select(User))}
        return True, [{'previousStatus': s(r.get('PreviousStatus')), 'newStatus': s(r.get('NewStatus')) or s(r.get('Activity')).removeprefix('Assignment Status: '),
            'date': d(r.get('Date')), 'recordedBy': names.get(lower(r.get('RecordedBy')), s(r.get('RecordedBy'))), 'comments': s(r.get('Comments'))}
            for r in rows(db, 'StatusHistory') if s(r.get('AssignmentID')) == assignment]

    if name == 'getTrainerAvailability':
        admin(actor)
        from .scheduling import check
        return True, check(db, actor, {'trainerUsername': arg(args,0),
            'startDate': arg(args,1), 'endDate': arg(args,2),
            'startTime': arg(args,3), 'endTime': arg(args,4),
            'projectType': arg(args,5), 'projectId': arg(args,6)})
    if name == 'checkTrainerSchedule':
        manager(actor)
        from .scheduling import check
        return True, check(db, actor, payload(args))
    if name == 'updateCategoryPlanning':
        admin(actor)
        code = s(arg(args, 0))
        categories = arg(args, 1, [])
        if not isinstance(categories, list):
            raise HTTPException(400, 'Category list required')
        seen_categories = set()
        for cat in categories:
            cat_name = lower(cat.get('category')) if isinstance(cat, dict) else ''
            if not cat_name or cat_name in seen_categories or n(cat.get('plannedDays')) < 0:
                return True, fail('Categories must be unique, nonblank and have nonnegative days.')
            seen_categories.add(cat_name)
        previous = {}
        for r in sheet_objects(db, 'CategoryPlanning'):
            if s(r.data.get('CollegeCode')) == code:
                previous[lower(r.data.get('Category'))] = n(r.data.get('CompletedDays'))
                db.delete(r)
        for cat in categories:
            if not isinstance(cat, dict) or not s(cat.get('category')).strip():
                continue
            insert(db, 'CategoryPlanning', {'CollegeCode': code, 'Category': s(cat['category']),
                'PlannedDays': n(cat.get('plannedDays')), 'CompletedDays': previous.get(lower(cat['category']), 0)})
        return True, ok()
    if name == 'assignTrainer':
        manager(actor)
        p = payload(args)
        trainer = person(db, p.get('trainerUsername'))
        if not trainer or trainer.role != 'Trainer' or not trainer.active:
            return True, fail('Trainer account not found.')
        code = s(p.get('collegeCode'))
        if not find(db, 'Colleges', 'CollegeCode', code):
            return True, fail('College not found.')
        first_date, last_date = date_only(p.get('fromDate')), date_only(p.get('toDate'))
        if not first_date or not last_date or last_date < first_date:
            return True, fail('Assignment requires valid start/end dates.')
        status = s(p.get('assignmentStatus')) or 'Upcoming'
        if status not in STATUSES:
            return True, fail('Invalid assignment status.')
        planned_categories = {lower(x.get('Category')) for x in rows(db, 'CategoryPlanning')
                              if s(x.get('CollegeCode')).strip() == code}
        category = s(p.get('category')).strip()
        if not category or (planned_categories and lower(category) not in planned_categories):
            return True, fail('Choose a category configured in the college Training Planning tab.')
        # Commit-time validation, not merely a browser-side warning.
        from .scheduling import validate_slot, enforce
        validate_slot(p.get('fromDate'), p.get('toDate'), p.get('startTime'), p.get('endTime'), require_dates=True)
        conflict_rows = enforce(db, actor, p, start_key='fromDate', end_key='toDate',
            exclude_type='lesuccess', exclude_id=code, exclude_category=category)
        for r in sheet_objects(db, 'TrainerAssignments'):
            if (s(r.data.get('CollegeCode')).strip() == code and
                lower(r.data.get('Category')) == lower(category) and current_assignment(r.data)):
                amend(r, CurrentAssignment=False)
                prior_trainer = lower(r.data.get('TrainerUsername'))
                if prior_trainer != trainer.username:
                    alert(db, 'Assignment Replaced', prior_trainer,
                          f'Your assignment to this college in {category} was replaced.',
                          related_assignment=s(r.data.get('AssignmentID')))
        item = {'AssignmentID': str(uuid4()), 'CollegeCode': code,
            'TrainerUsername': trainer.username, 'TrainerName': trainer.full_name,
            'Category': s(p.get('category')), 'FromDate': as_date(p.get('fromDate')),
            'ToDate': as_date(p.get('toDate')), 'StartTime': s(p.get('startTime')),
            'EndTime': s(p.get('endTime')), 'Batch': s(p.get('batch')),
            'AssignmentStatus': status,
            'ActualCompletedDays': 0, 'PlannedDays': p.get('plannedDays', ''),
            'StatusUpdatedOn': now(), 'StatusUpdatedBy': actor.username,
            'CurrentAssignment': status in ('Running', 'Upcoming', 'On Hold'),
            'CreatedBy': actor.username, 'CreatedOn': now()}
        insert(db, 'TrainerAssignments', item)
        assignment_history(db, item, '', status, actor, 'Assignment created.')
        college = find(db, 'Colleges', 'CollegeCode', code)
        college_name = s(college.data.get('CollegeName')) if college else code
        alert(db, 'Trainer Assigned', trainer.username,
              f'Assigned to {college_name} ({category}) — {status}. Open My Colleges for details.',
              related_assignment=item['AssignmentID'])
        availability = trainer_availability(db, trainer.username, item['FromDate'], item['ToDate'])
        if not availability['available']:
            alert(db, 'Assignment Conflict', 'Admin', f'{trainer.full_name} has approved leave overlapping this assignment.', related_assignment=item['AssignmentID'])
        if conflict_rows:
            alert(db, 'Schedule Override', actor.username,
                  f'Admin overrode {len(conflict_rows)} overlapping schedule/leave booking(s) for {trainer.full_name}.',
                  related_assignment=item['AssignmentID'])
        return True, ok(conflict=bool(conflict_rows) or not availability['available'],
                        acknowledgedConflicts=len(conflict_rows))
    if name in ('removeTrainerAssignment', 'updateTrainerAssignmentStatus'):
        manager(actor)
        record = find(db, 'TrainerAssignments', 'AssignmentID', arg(args, 0))
        if not record:
            return True, fail('Assignment not found.')
        new = 'Not Active' if name == 'removeTrainerAssignment' else s(arg(args, 1))
        if new not in STATUSES:
            return True, fail('Invalid assignment status.')
        old = s(record.data.get('AssignmentStatus'))
        if old == new:
            return True, fail('The assignment is already in that status.')
        amend(record, AssignmentStatus=new, StatusUpdatedOn=now(), StatusUpdatedBy=actor.username,
            CurrentAssignment=new in ('Running', 'Upcoming', 'On Hold'))
        assignment_history(db, record.data, old, new, actor, s(arg(args, 3)))
        alert(db, 'Assignment Updated', lower(record.data.get('TrainerUsername')),
              f'Your assignment for {s(record.data.get("Category"))} changed from {old} to {new}.',
              related_assignment=s(record.data.get('AssignmentID')))
        return True, ok()

    if name == 'submitProjectDailyUpdate':
        from .unified_projects import create_update
        return True, create_update(db, actor, payload(args))
    if name == 'getMyDailyUpdates':
        username = lower(arg(args, 0))
        self_only(actor, username)
        names = {c['collegeCode']: c for c in colleges(db)}
        syllabus = rows(db, 'Syllabus')
        logs = [r for r in rows(db, 'DailyTrainingLog') if lower(r.get('TrainerUsername')) == username]
        result = []
        for r in logs:
            code = s(r.get('CollegeCode'))
            matches = [x for x in syllabus if lower(x.get('TrainerUsername')) == username and
                s(x.get('CollegeCode')) == code and s(x.get('Category')) == s(r.get('Category')) and
                (s(x.get('LogID')) == s(r.get('LogID')) if s(x.get('LogID')) else
                 s(x.get('Topic')) == s(r.get('TopicCovered')))]
            sy = matches[-1] if matches else {}
            col = names.get(code, {})
            result.append({'logID': s(r.get('LogID')), 'date': d(r.get('Date')), 'collegeCode': code,
                'collegeName': col.get('collegeName', code), 'collegeLogo': col.get('logoURL', ''),
                'category': s(r.get('Category')), 'topicCovered': s(r.get('TopicCovered')),
                'attendance': s(r.get('Attendance')), 'submittedOn': d(r.get('SubmittedOn')),
                'trainerUsername': username, 'trainerName': s(r.get('TrainerName')),
                'trainerStatus': s(sy.get('TrainerStatus') or 'Submitted'), 'rmStatus': s(sy.get('RMStatus') or 'Pending')})
        from .unified_projects import update_history
        result.extend(update_history(db, actor))
        return True, sorted(result, key=lambda x: date_only(x['date']) or date.min, reverse=True)
    if name == 'submitDailyUpdate':
        if actor.role != 'Trainer':
            raise HTTPException(403, 'Trainer role required')
        p = payload(args)
        self_only(actor, p.get('trainerUsername'))
        if s(p.get('projectType')).lower() in ('vendor', 'freelance'):
            from .unified_projects import create_update
            return True, create_update(db, actor, p)
        code, category = s(p.get('collegeCode')), s(p.get('category'))
        submission_day = date_only(p.get('date'))
        assigned = any(lower(a.get('TrainerUsername')) == actor.username and s(a.get('CollegeCode')) == code and
                       lower(a.get('Category')) == lower(category) and current_assignment(a) and
                       (not date_only(a.get('FromDate')) or date_only(a.get('FromDate')) <= submission_day) and
                       (not date_only(a.get('ToDate')) or submission_day <= date_only(a.get('ToDate')))
                       for a in rows(db, 'TrainerAssignments')) if submission_day else False
        if not assigned:
            return True, fail('You are not assigned to this college and category.')
        if not submission_day or not s(p.get('topicCovered')).strip():
            return True, fail('Date and topic are required.')
        if any(lower(r.get('TrainerUsername')) == actor.username and s(r.get('CollegeCode')) == code and
               lower(r.get('Category')) == lower(category) and date_only(r.get('Date')) == submission_day
               for r in rows(db, 'DailyTrainingLog')):
            return True, fail('Daily update already submitted for this date and category.')
        attendance = s(p.get('attendance')).strip().rstrip('%')
        if attendance:
            try:
                if not 0 <= float(attendance) <= 100:
                    raise ValueError()
            except ValueError:
                return True, fail('Attendance must be between 0 and 100 percent.')
        log_id = str(uuid4())
        insert(db, 'DailyTrainingLog', {'LogID': log_id, 'CollegeCode': code,
            'Date': as_date(p.get('date')), 'Category': category, 'TopicCovered': s(p.get('topicCovered')),
            'Attendance': s(p.get('attendance')), 'TrainerUsername': actor.username,
            'TrainerName': actor.full_name, 'SubmittedOn': now()})
        plan = next((r for r in sheet_objects(db, 'CategoryPlanning') if s(r.data.get('CollegeCode')) == code and lower(r.data.get('Category')) == lower(category)), None)
        if plan:
            amend(plan, CompletedDays=n(plan.data.get('CompletedDays')) + 1)
        insert(db, 'Syllabus', {'SyllabusID': str(uuid4()), 'LogID': log_id, 'CollegeCode': code,
            'Category': category, 'Topic': s(p.get('topicCovered')),
            'TrainerUsername': actor.username, 'TrainerStatus': 'Submitted',
            'RMStatus': 'Pending', 'RMUsername': '', 'UpdatedOn': now()})
        return True, ok()
    if name == 'getPendingApprovals':
        if actor.role not in {'Reporting Manager', 'Admin'}:
            raise HTTPException(403, 'Manager role required')
        from .unified_projects import pending_external
        existing = [{**r, 'ProjectType': 'LeSuccess', 'CollegeName': s(r.get('CollegeCode'))}
            for r in rows(db, 'Syllabus') if s(r.get('RMStatus')) == 'Pending' and
            syllabus_approver(db, actor, r.get('TrainerUsername')) and
            (not arg(args, 0) or s(r.get('CollegeCode')) == s(arg(args, 0)))]
        external = pending_external(db, actor)
        if arg(args, 0):
            external = [r for r in external if r['CollegeCode'] == s(arg(args, 0))]
        return True, existing + external
    if name == 'approveSyllabus':
        if actor.role not in {'Reporting Manager', 'Admin'}:
            raise HTTPException(403, 'Reporting Manager or Admin required')
        from .unified_projects import review_external
        external_result = review_external(db, actor, s(arg(args, 0)), s(arg(args, 2)))
        if external_result is not None:
            return True, external_result
        record = find(db, 'Syllabus', 'SyllabusID', arg(args, 0))
        if not record:
            return True, fail('Syllabus entry not found.')
        decision = s(arg(args, 2))
        if decision not in ('Approved', 'Rejected'):
            return True, fail('Invalid decision.')
        if record.data.get('RMStatus') != 'Pending':
            return True, fail('Already reviewed.')
        if not syllabus_approver(db, actor, record.data.get('TrainerUsername')):
            raise HTTPException(403, 'This syllabus entry is not in your reporting hierarchy')
        amend(record, RMStatus=decision, RMUsername=actor.username, UpdatedOn=now())
        return True, ok()

    if name == 'submitLeaveRequest':
        submitter(actor)
        p = payload(args)
        self_only(actor, p.get('employeeUsername'))
        start, end = date_only(p.get('startDate')), date_only(p.get('endDate'))
        count = working_days(start, end)
        if not count:
            return True, fail('Please provide a valid working-day date range.')
        if any(lower(r.get('EmployeeUsername')) == actor.username and
               s(r.get('Status')) in ('Pending', 'Approved') and
               overlap(start, end, r.get('StartDate'), r.get('EndDate'))
               for r in rows(db, 'LeaveRequests')):
            return True, fail('A pending or approved leave already overlaps these dates.')
        boss = person(db, actor.reporting_manager_username)
        if not boss or not boss.active:
            return True, fail('A reporting manager must be mapped before submitting leave.')
        leave_id = str(uuid4())
        insert(db, 'LeaveRequests', {'LeaveID': leave_id, 'EmployeeUsername': actor.username,
            'EmployeeName': actor.full_name, 'Role': actor.role,
            'ReportingManagerUsername': boss.username, 'ReportingManagerName': boss.full_name,
            'StartDate': start.isoformat(), 'EndDate': end.isoformat(),
            'NumberOfDays': count, 'Comments': s(p.get('comments')).strip(),
            'Status': 'Pending', 'SubmittedOn': now(), 'ReviewedBy': '',
            'ReviewedOn': '', 'ReviewComments': '', 'AlertStatus': 'Pending'})
        alert(db, 'Leave Submitted', boss.username, f'{actor.full_name} submitted a leave request.', related_leave=leave_id)
        return True, ok()
    if name == 'getLeaveRequests':
        self_only(actor, arg(args, 0))
        values = rows(db, 'LeaveRequests')
        if actor.role == 'Trainer':
            values = [r for r in values if lower(r.get('EmployeeUsername')) == actor.username]
        elif actor.role in {'Team Leader', 'Reporting Manager'}:
            values = [r for r in values if lower(r.get('EmployeeUsername')) == actor.username or lower(r.get('ReportingManagerUsername')) == actor.username]
        return True, [leave_dict(r) for r in sorted(values, key=lambda x: s(x.get('SubmittedOn')), reverse=True)]
    if name == 'reviewLeaveRequest':
        manager(actor)
        record = find(db, 'LeaveRequests', 'LeaveID', arg(args, 0))
        if not record:
            return True, fail('Leave request not found.')
        if lower(record.data.get('ReportingManagerUsername')) != actor.username:
            raise HTTPException(403, 'Only stamped manager may review this request')
        if record.data.get('Status') != 'Pending':
            return True, fail('This leave request has already been reviewed.')
        decision = s(arg(args, 2))
        if decision not in ('Approved', 'Rejected'):
            return True, fail('Invalid leave decision.')
        amend(record, Status=decision, ReviewedBy=actor.username, ReviewedOn=now(),
            ReviewComments=s(arg(args, 3)), AlertStatus='Reviewed')
        alert(db, f'Leave {decision}', s(record.data.get('EmployeeUsername')),
              f'Your leave request was {decision.lower()}.', related_leave=s(record.data.get('LeaveID')))
        return True, ok()
    if name == 'getLeaveAlerts':
        self_only(actor, arg(args, 0))
        return True, leave_alerts(db, actor)
    if name == 'getLeaveDashboardSummary':
        self_only(actor, arg(args, 0))
        if actor.role not in MANAGEMENT:
            return True, []
        start = date.today().replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        leaves = [r for r in rows(db, 'LeaveRequests') if r.get('Status') == 'Approved' and overlap(r.get('StartDate'), r.get('EndDate'), start, end)]
        projects = []
        for a in rows(db, 'TrainerAssignments'):
            if a.get('AssignmentStatus') == 'Running' and current_assignment(a):
                projects.append({'username': lower(a.get('TrainerUsername')), 'start': a.get('FromDate'),
                    'end': a.get('ToDate'), 'projectName': s(a.get('CollegeCode')), 'source': 'LeSuccess'})
        for tab, username_key, source in [('VendorProjects', 'TrainerUsername', 'Vendor'), ('FreelanceProjects', 'TrainerUsername', 'Freelance')]:
            for p in rows(db, tab):
                if p.get('Status') == 'Running':
                    projects.append({'username': lower(p.get(username_key)), 'start': p.get('StartDate'),
                        'end': p.get('EndDate'), 'projectName': s(p.get('CollegeName')), 'source': source})
        result = []
        for r in leaves:
            if actor.role != 'Admin' and lower(r.get('ReportingManagerUsername')) != actor.username:
                continue
            for project in projects:
                if project['username'] == lower(r.get('EmployeeUsername')) and overlap(r.get('StartDate'), r.get('EndDate'), project['start'], project['end']):
                    effective_start = max(filter(None, (date_only(r.get('StartDate')), date_only(project['start']), start)))
                    effective_end = min(filter(None, (date_only(r.get('EndDate')), date_only(project['end']), end)))
                    count = working_days(effective_start, effective_end)
                    if count:
                        result.append({'leaveID': s(r.get('LeaveID')), 'employeeUsername': s(r.get('EmployeeUsername')),
                            'employeeName': s(r.get('EmployeeName')), 'startDate': d(r.get('StartDate')),
                            'endDate': d(r.get('EndDate')), 'numberOfDays': count, 'status': 'Approved',
                            'comments': s(r.get('Comments')), 'projectName': project['projectName'], 'projectSource': project['source']})
        return True, result

    if name == 'createActivityMaster':
        admin(actor)
        p = payload(args)
        code, activity = s(p.get('code')).strip(), s(p.get('name')).strip()
        if not code or not activity:
            return True, fail('Activity Code and Activity Name are required.')
        if find(db, 'ActivityMaster', 'ActivityCode', code):
            return True, fail('This Activity Code already exists.')
        insert(db, 'ActivityMaster', {'ActivityCode': code, 'ActivityName': activity, 'Active': True,
            'CreatedBy': actor.username, 'CreatedOn': now()})
        return True, ok()
    if name == 'setActivityMasterActive':
        admin(actor)
        r = find(db, 'ActivityMaster', 'ActivityCode', arg(args, 0))
        if not r:
            return True, fail('Activity Code not found.')
        amend(r, Active=bool(arg(args, 1)))
        return True, ok()
    if name == 'submitDailyActivity':
        submitter(actor)
        p = payload(args)
        self_only(actor, p.get('trainerUsername'))
        activity = find(db, 'ActivityMaster', 'ActivityCode', p.get('activityCode'))
        if not activity or s(activity.data.get('Active')).lower() in ('false', '0'):
            return True, fail('Please select a valid Activity.')
        day = date_only(p.get('date'))
        hours = n(p.get('hours'))
        if not day or hours <= 0 or hours > 24 or not s(p.get('topicCovered')).strip():
            return True, fail('Valid date, work description and hours (up to 24) required.')
        a_name = s(activity.data.get('ActivityName'))
        college_name = 'In-House'
        class_mode = ''
        if a_name == 'Class Handling':
            college_name = s(p.get('collegeName')).strip()
            class_mode = s(p.get('classMode'))
            allowed_names = {c['collegeName'] for c in colleges(db)} | {'Company Training Center'}
            if college_name not in allowed_names or class_mode not in ('Online', 'Offline'):
                return True, fail('Choose a valid College/Center and class mode.')
        if hours + sum(n(r.get('Hours')) for r in rows(db, 'DailyActivityTracker')
               if lower(r.get('TrainerUsername')) == actor.username and date_only(r.get('Date')) == day) > 24:
            return True, fail('Daily Tracker hours cannot exceed 24 in one day.')
        boss = person(db, actor.reporting_manager_username)
        if not boss or not boss.active:
            return True, fail('A reporting manager must be mapped before submitting the Daily Tracker.')
        entry = str(uuid4())
        insert(db, 'DailyActivityTracker', {'EntryID': entry, 'TrainerUsername': actor.username,
            'TrainerName': actor.full_name, 'Date': day.isoformat(), 'ActivityCode': s(p.get('activityCode')),
            'ActivityName': a_name, 'CollegeName': college_name, 'ClassMode': class_mode,
            'TopicCovered': s(p.get('topicCovered')), 'Hours': hours, 'Status': 'Pending',
            'ApproverUsername': boss.username,
            'SubmittedOn': now(), 'ReviewedBy': '', 'ReviewedOn': '', 'ReviewComments': ''})
        alert(db, 'Daily Tracker Submitted', boss.username, f'{actor.full_name} submitted Daily Tracker.', related_assignment=entry)
        return True, ok()
    if name == 'getMyDailyActivities':
        self_only(actor, arg(args, 0))
        relevant = [r for r in rows(db, 'DailyActivityTracker') if lower(r.get('TrainerUsername')) == actor.username]
        return True, [daily_activity_dict(r) for r in sorted(relevant, key=lambda x: s(x.get('Date')), reverse=True)]
    if name == 'getDailyActivityApprovals':
        manager(actor)
        self_only(actor, arg(args, 0))
        team = {u.username for u in get_team(db, actor)}
        relevant = [r for r in rows(db, 'DailyActivityTracker') if
            lower(r.get('ApproverUsername') or (person(db, r.get('TrainerUsername')).reporting_manager_username
                if person(db, r.get('TrainerUsername')) else '')) == actor.username]
        return True, [daily_activity_dict(r, True) for r in sorted(relevant, key=lambda x: s(x.get('Date')), reverse=True)]
    if name == 'reviewDailyActivity':
        manager(actor)
        record = find(db, 'DailyActivityTracker', 'EntryID', arg(args, 0))
        if not record:
            return True, fail('Daily Tracker entry not found.')
        employee = person(db, record.data.get('TrainerUsername'))
        if not employee or lower(record.data.get('ApproverUsername') or employee.reporting_manager_username) != actor.username:
            raise HTTPException(403, 'Only stamped manager may review this entry')
        if record.data.get('Status') != 'Pending':
            return True, fail('This entry has already been reviewed.')
        decision = s(arg(args, 2))
        if decision not in ('Approved', 'Rejected'):
            return True, fail('Invalid decision.')
        amend(record, Status=decision, ReviewedBy=actor.username, ReviewedOn=now(), ReviewComments=s(arg(args, 3)))
        alert(db, f'Daily Tracker {decision}', employee.username,
              f'Your Daily Tracker entry was {decision.lower()} by {actor.full_name}.',
              related_assignment=s(record.data.get('EntryID')))
        return True, ok()
    if name == 'getDailyActivityMissingAlerts':
        self_only(actor, arg(args, 0))
        return True, missing_activity_alerts(db, actor)
    if name == 'getTrainerActivityReport':
        admin(actor)
        month = s(arg(args, 0)).strip()
        grouped = {}
        names = {u.username: u.full_name for u in db.scalars(select(User))}
        for row in rows(db, 'DailyActivityTracker'):
            if s(row.get('Status')) != 'Approved' or month and not as_date(row.get('Date')).startswith(month):
                continue
            username, activity = lower(row.get('TrainerUsername')), s(row.get('ActivityName'))
            key = (username, activity)
            item = grouped.setdefault(key, {'trainerUsername': username, 'trainerName': names.get(username, username),
                'activityName': activity, 'count': 0, 'totalHours': 0})
            item['count'] += 1
            item['totalHours'] += n(row.get('Hours'))
        return True, sorted(grouped.values(), key=lambda x: (x['trainerName'], x['activityName']))
    if name == 'getDailyActivityAvailableMonths':
        admin(actor)
        return True, sorted({as_date(r.get('Date'))[:7] for r in rows(db, 'DailyActivityTracker') if as_date(r.get('Date'))}, reverse=True)

    if name in ('getKpiMaster', 'getKpiMasterForAdmin'):
        if name == 'getKpiMasterForAdmin':
            admin(actor)
            self_only(actor, arg(args, 0))
        return True, kpi_master(db)
    if name == 'saveKpiMaster':
        admin(actor)
        self_only(actor, arg(args, 0))
        p = arg(args, 1)
        if not isinstance(p, dict):
            raise HTTPException(400, 'KPI object required')
        kpi_id = int(n(p.get('id'))) if p.get('id') else max([v['id'] for v in kpi_master(db)] + [0]) + 1
        entry = find(db, 'KPI Master', 'id', kpi_id)
        values = {'id': kpi_id, 'category': s(p.get('category')), 'parameter': s(p.get('parameter')), 'target': s(p.get('target'))}
        if entry:
            amend(entry, **values)
        else:
            insert(db, 'KPI Master', values)
        return True, ok(id=kpi_id)
    if name == 'deleteKpiMaster':
        admin(actor)
        self_only(actor, arg(args, 0))
        id_value = int(n(arg(args, 1)))
        master = find(db, 'KPI Master', 'id', id_value)
        if master:
            db.delete(master)
        for record in sheet_objects(db, 'Evaluations'):
            if int(n(record.data.get('kpiId'))) == id_value:
                db.delete(record)
        return True, ok()
    if name == 'getKpiDashboardData':
        self_only(actor, arg(args, 0))
        return True, kpi_data(db, actor)
    if name == 'submitRating':
        self_only(actor, arg(args, 0))
        id_value = int(n(arg(args, 1)))
        maximum = next((weight(k['target']) for k in kpi_master(db) if k['id'] == id_value), None)
        if maximum is None:
            return True, fail('KPI parameter not found.')
        try:
            rating = float(arg(args, 2))
        except (ValueError, TypeError):
            return True, fail('Please enter a valid rating.')
        if not (0 <= rating <= maximum):
            return True, fail(f'Rating must be between 0 and {maximum}.')
        key = f'{id_value}_{actor.username}'
        record = find(db, 'Evaluations', 'recordKey', key)
        if record and s(record.data.get('status')) in ('Submitted', 'Approved'):
            return True, fail('This rating is already submitted/approved.')
        boss = person(db, actor.reporting_manager_username)
        has_manager = bool(boss and boss.active)
        if actor.role != 'Admin' and not has_manager:
            return True, fail('A reporting manager must be mapped before rating submission.')
        entry = {'recordKey': key, 'kpiId': id_value, 'employeeId': actor.username,
            'trainerRating': rating, 'rmRating': '', 'vpRating': '', 'status': 'Submitted' if has_manager else 'Approved',
            'locked': not has_manager, 'trainerSubmittedDate': now(),
            'rmSubmittedDate': '' if has_manager else now(), 'vpSubmittedDate': '',
            'employeeRole': actor.role, 'approverId': boss.username if has_manager else '',
            'approverRole': boss.role if has_manager else '', 'returnReason': ''}
        if record:
            amend(record, **entry)
        else:
            insert(db, 'Evaluations', entry)
        if has_manager:
            alert(db, 'KPI Submitted', boss.username, f'{actor.full_name} submitted KPI rating.', related_assignment=key)
        return True, ok()
    if name in ('decideOnRating', 'unlockRating'):
        manager(actor)
        self_only(actor, arg(args, 0))
        id_value, employee = int(n(arg(args, 1))), lower(arg(args, 2))
        record = find(db, 'Evaluations', 'recordKey', f'{id_value}_{employee}')
        if not record:
            return True, fail('Rating not found.')
        if lower(record.data.get('approverId')) != actor.username:
            raise HTTPException(403, 'Only stamped approver may review this rating')
        if name == 'decideOnRating':
            if s(record.data.get('status')) != 'Submitted':
                return True, fail('This rating is not awaiting review.')
            decision = s(arg(args, 3))
            if decision not in ('Approved', 'Returned'):
                return True, fail('Invalid decision.')
            amend(record, status=decision, locked=decision == 'Approved',
                rmSubmittedDate=now() if decision == 'Approved' else '', returnReason=s(arg(args, 4)) if decision == 'Returned' else '')
            alert(db, 'KPI ' + decision, employee, f'Your KPI rating was {decision.lower()}.', related_assignment=s(record.data.get('recordKey')))
        else:
            if s(record.data.get('status')) != 'Approved':
                return True, fail('Only approved ratings can be reopened.')
            amend(record, status='Returned', locked=False, rmSubmittedDate='', returnReason='Reopened for revision')
        return True, ok()

    if name == 'markAlertRead':
        note = find(db, 'Alerts', 'AlertID', arg(args, 0))
        if not note:
            return True, fail('Notification not found.')
        if lower(note.data.get('RecipientUserID')) != actor.username:
            raise HTTPException(403, 'Not your notification')
        amend(note, AlertStatus='Read', ReadOn=now())
        return True, ok()
    if name == 'getAlerts':
        self_only(actor, arg(args, 0))
        return True, get_alerts(db, actor)
    if name == 'getAlertCount':
        self_only(actor, arg(args, 0))
        return True, len(get_alerts(db, actor))
    return False, None
