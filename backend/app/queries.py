from collections import defaultdict
from datetime import datetime
from sqlalchemy import select
from .db import SheetRow, User
from .identifiers import username as normalize_username


def s(v):
    return '' if v is None else str(v)


def n(v):
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


def d(v):
    if not v:
        return ''
    try:
        return datetime.fromisoformat(s(v).replace('Z', '+00:00')).strftime('%d %b %Y')
    except ValueError:
        return s(v)


def rows(db, name):
    return [r.data for r in db.scalars(select(SheetRow).where(SheetRow.sheet_name == name).order_by(SheetRow.source_row))]


def _tables(db):
    """Single scan for dashboard rather than repeatedly reading source sheets."""
    sheets = ['Colleges', 'TrainerAssignments', 'CategoryPlanning', 'DailyTrainingLog']
    out = {name: [] for name in sheets}
    for item in db.scalars(select(SheetRow).where(SheetRow.sheet_name.in_(sheets))):
        out[item.sheet_name].append(item.data)
    return out


def active_assignment(item):
    current = str(item.get('CurrentAssignment', '')).lower()
    return str(item.get('AssignmentStatus') or 'Upcoming') in ('Upcoming', 'Running', 'On Hold') and current not in ('false', '0', 'no')


def colleges(db, cache=None):
    tab = cache or _tables(db)
    all_users = db.scalars(select(User)).all()
    names = {u.username.lower(): u.full_name for u in all_users}
    plans = defaultdict(list)
    assignments = defaultdict(list)
    attendance = defaultdict(list)
    for p in tab['CategoryPlanning']:
        plans[s(p.get('CollegeCode'))].append(p)
    for a in tab['TrainerAssignments']:
        if active_assignment(a):
            assignments[s(a.get('CollegeCode'))].append(a)
    for log in tab['DailyTrainingLog']:
        attendance[s(log.get('CollegeCode'))].append(log)
    result = []
    for c in tab['Colleges']:
        code = s(c.get('CollegeCode'))
        cat = plans[code]
        a = assignments[code]
        planned = sum(n(p.get('PlannedDays')) for p in cat)
        done = sum(n(p.get('CompletedDays')) for p in cat)
        vals = [n(s(x.get('Attendance')).replace('%', '')) for x in attendance[code] if s(x.get('Attendance')).strip()]
        result.append({
            'collegeCode': code, 'collegeName': s(c.get('CollegeName')),
            'logoURL': s(c.get('LogoURL')), 'studentStrength': n(c.get('StudentStrength')),
            'status': s(c.get('Status')), 'startDate': d(c.get('StartDate')),
            'endDate': d(c.get('EndDate')), 'attendanceSheetLink': s(c.get('AttendanceSheetLink')),
            'createdBy': s(c.get('CreatedBy')), 'createdOn': d(c.get('CreatedOn')),
            'notes': s(c.get('Notes')), 'totalPlannedDays': planned,
            'completedDays': done, 'remainingDays': max(planned - done, 0),
            'progressPercent': round(done / planned * 100) if planned > 0 else 0,
            'trainerCount': len(a),
            'trainerNames': [names.get(normalize_username(x.get('TrainerUsername')), s(x.get('TrainerName') or x.get('TrainerUsername'))) for x in a],
            'categories': [{
                'category': s(p.get('Category')), 'plannedDays': n(p.get('PlannedDays')),
                'completedDays': n(p.get('CompletedDays')),
                'remainingDays': max(0, n(p.get('PlannedDays')) - n(p.get('CompletedDays'))),
                'progressPercent': round(n(p.get('CompletedDays')) / n(p.get('PlannedDays')) * 100) if n(p.get('PlannedDays')) > 0 else 0
            } for p in cat],
            'avgAttendance': sum(vals) / len(vals) if vals else 0
        })
    return result


def roster(db, cache=None):
    tab = cache or _tables(db)
    users = db.scalars(select(User).where(User.role == 'Trainer')).all()
    by_user = defaultdict(list)
    for a in tab['TrainerAssignments']:
        if active_assignment(a):
            by_user[normalize_username(a.get('TrainerUsername'))].append(a)
    plan_by_key = {(s(p.get('CollegeCode')), s(p.get('Category')).lower()): p for p in tab['CategoryPlanning']}
    college_names = {s(c.get('CollegeCode')): s(c.get('CollegeName')) for c in tab['Colleges']}
    output = []
    for u in users:
        a = sorted(by_user[u.username.lower()], key=lambda x: s(x.get('FromDate')), reverse=True)
        if not a:
            output.append({'username': u.username, 'fullName': u.full_name or u.username, 'active': False})
            continue
        current = a[0]
        code, cat = s(current.get('CollegeCode')), s(current.get('Category'))
        p = plan_by_key.get((code, cat.lower()), {})
        output.append({
            'username': u.username, 'fullName': u.full_name or u.username, 'active': True,
            'collegeCode': code, 'collegeName': college_names.get(code, code),
            'category': cat, 'totalDays': n(p.get('PlannedDays')),
            'completedDays': n(p.get('CompletedDays')),
            'fromDate': d(current.get('FromDate')), 'toDate': d(current.get('ToDate'))
        })
    return output


def dashboard(db):
    tab = _tables(db)
    college_list = colleges(db, tab)
    roster_list = roster(db, tab)
    trainer_count = len(roster_list)
    active = sum(1 for u in roster_list if u['active'])
    summary = {
        'totalColleges': len(college_list), 'totalTrainers': trainer_count,
        'activeTrainers': active, 'nonActiveTrainers': trainer_count - active
    }
    for label, key in [('running', 'running'), ('upcoming', 'upcoming'), ('onHold', 'on hold'),
                       ('completed', 'completed'), ('cancelled', 'cancelled')]:
        summary[label] = sum(1 for x in college_list if x['status'].lower() == key)
    return {'summary': summary, 'colleges': college_list, 'roster': roster_list}


def project_list(db, kind):
    sheet = 'VendorProjects' if kind == 'vendor' else 'FreelanceProjects'
    people = {u.full_name.lower(): u.username for u in db.scalars(select(User))}
    logo = {s(x.get('CollegeName')).lower(): s(x.get('LogoURL')) for x in rows(db, 'Colleges')}
    result = []
    for p in rows(db, sheet):
        trainer_name = s(p.get('TrainerName' if kind == 'vendor' else 'FreelancerName'))
        name = s(p.get('CollegeName'))
        result.append({
            'projectID': s(p.get('ProjectID')), 'vendor': s(p.get('Vendor')),
            'collegeName': name, 'logoURL': s(p.get('LogoURL')),
            'trainerUsername': s(p.get('TrainerUsername')) or people.get(trainer_name.lower(), ''),
            'trainerName': trainer_name, 'freelancerName': trainer_name,
            'startDate': s(p.get('StartDate')), 'endDate': s(p.get('EndDate')),
            'startTime': s(p.get('StartTime')), 'endTime': s(p.get('EndTime')),
            'batch': s(p.get('Batch')),
            'days': n(p.get('Days')), 'category': s(p.get('Category')),
            'status': s(p.get('Status')), 'location': s(p.get('Location')),
            'comments': s(p.get('Comments')), 'collegeLogo': s(p.get('LogoURL')) or logo.get(name.lower(), ''),
            'createdBy': s(p.get('CreatedBy')), 'createdOn': d(p.get('CreatedOn'))
        })
    return result


def users(db):
    return [{
        'userID': u.user_id, 'username': u.username, 'fullName': u.full_name,
        'role': u.role, 'designation': u.designation, 'email': u.email,
        'phone': u.phone, 'active': u.active,
        'reportingManagerUsername': u.reporting_manager_username
    } for u in db.scalars(select(User).order_by(User.id))]


def assignment_diagnostics(db, trainer_username):
    """Explain why a Trainer's Daily Update form may be empty.

    Accessible only by that Trainer or an authorized admin/manager via RPC.
    No passwords or other employees' assignments are returned.
    """
    target = normalize_username(trainer_username)
    all_assignments = [x for x in rows(db, 'TrainerAssignments')
                       if normalize_username(x.get('TrainerUsername')) == target]
    known_colleges = {s(c.get('CollegeCode')).strip(): s(c.get('CollegeName'))
                      for c in rows(db, 'Colleges')}
    entries = []
    for x in all_assignments:
        code = s(x.get('CollegeCode')).strip()
        active = active_assignment(x)
        available = code in known_colleges
        entries.append({'collegeCode': code, 'collegeName': known_colleges.get(code, ''),
                        'category': s(x.get('Category')).strip(),
                        'status': s(x.get('AssignmentStatus')) or 'Upcoming',
                        'current': active, 'collegeExists': available,
                        'fromDate': s(x.get('FromDate')), 'toDate': s(x.get('ToDate'))})
    visible = [x for x in entries if x['current'] and x['collegeExists']]
    if visible:
        message = f'{len(visible)} assigned college(s) available. Open Daily Update again.'
    elif not entries:
        message = ('No LeSuccess college assignment was found for this Employee ID. '
                   'Ask Admin to assign this exact Trainer account to a college and category.')
    elif any(not x['collegeExists'] and x['current'] for x in entries):
        message = ('An assignment exists, but its College record is missing. '
                   'Ask Admin to check the College Code.')
    else:
        message = ('Assignments exist, but none are current. Check whether they were '
                   'marked Completed / Not Active or replaced by a newer assignment.')
    return {'username': target, 'totalAssignments': len(entries),
            'currentAssignments': sum(x['current'] for x in entries),
            'visibleColleges': len({x['collegeCode'] for x in visible}),
            'message': message, 'assignments': entries}
