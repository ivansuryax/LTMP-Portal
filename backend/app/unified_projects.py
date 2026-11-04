"""Cross-project trainer portal workflows (LeSuccess + Vendor + Freelancer).

Preserves legacy SheetRow data untouched. External training updates use a new
additive SQL table with project IDs as stable references and reviewer snapshots.
"""
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import select, func
from fastapi import HTTPException

from .db import ExternalTrainingUpdate, User, SheetRow
from .identifiers import username as normalize_username
from .queries import rows, colleges, active_assignment, n, s

EXTERNAL_SHEETS = {'vendor': 'VendorProjects', 'freelance': 'FreelanceProjects'}
ACTIVE = {'Running', 'Upcoming', 'On Hold'}


def parse_day(value):
    text = s(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).date()
    except ValueError:
        try:
            return datetime.strptime(text, '%d %b %Y').date()
        except ValueError:
            return None


def project_record(db, project_type, project_id):
    sheet = EXTERNAL_SHEETS.get(project_type)
    if not sheet:
        return None
    return next((row for row in db.scalars(select(SheetRow).where(SheetRow.sheet_name == sheet))
                 if s(row.data.get('ProjectID')) == project_id), None)


def assigned_user(db, record):
    """Prefer stable Employee ID; legacy name fallback only if unambiguous."""
    employee_id = normalize_username(record.get('TrainerUsername'))
    if employee_id:
        matched = db.scalar(select(User).where(User.username == employee_id, User.role == 'Trainer'))
        if matched:
            return matched
    # Historic project versions occasionally placed a display name in
    # TrainerUsername. Never guess when the display name is ambiguous.
    name = s(record.get('TrainerName') or record.get('FreelancerName') or record.get('TrainerUsername')).strip().lower()
    if not name:
        return None
    matching = list(db.scalars(select(User).where(func.lower(User.full_name) == name, User.role == 'Trainer')))
    return matching[0] if len(matching) == 1 else None


def project_owner(db, record):
    u = assigned_user(db, record)
    return u.username if u else ''


def external_projects(db, trainer=None, include_inactive=True):
    """Read original project rows without copying or modifying them."""
    result = []
    for typ, sheet in EXTERNAL_SHEETS.items():
        for raw in rows(db, sheet):
            owner = project_owner(db, raw)
            if trainer is not None and owner != normalize_username(trainer):
                continue
            status = s(raw.get('Status') or 'Running')
            if not include_inactive and status not in ACTIVE:
                continue
            p_id = s(raw.get('ProjectID'))
            if not p_id:
                continue
            category = s(raw.get('Category')).strip() or 'General'
            result.append({
                'projectType': typ, 'projectId': p_id, 'projectKey': f'{typ}:{p_id}',
                'projectName': s(raw.get('CollegeName')) or s(raw.get('Vendor')) or 'Unnamed project',
                'vendor': s(raw.get('Vendor')), 'trainerUsername': owner,
                'trainerName': s(raw.get('TrainerName') or raw.get('FreelancerName')),
                'category': category, 'myCategories': [category], 'status': status,
                'startDate': s(raw.get('StartDate')), 'endDate': s(raw.get('EndDate')),
                'startTime': s(raw.get('StartTime')), 'endTime': s(raw.get('EndTime')),
                'batch': s(raw.get('Batch')),
                'plannedDays': n(raw.get('Days')), 'logoURL': s(raw.get('LogoURL')),
                'canSubmit': status == 'Running' and bool(owner),
            })
    return result


def my_projects(db, actor):
    if actor.role != 'Trainer':
        raise HTTPException(403, 'Trainer role required')
    assignments = [x for x in rows(db, 'TrainerAssignments')
                   if normalize_username(x.get('TrainerUsername')) == actor.username and active_assignment(x)]
    by_code = {}
    for a in assignments:
        code = s(a.get('CollegeCode'))
        item = by_code.setdefault(code, {'categories': set(), 'start': [], 'end': [], 'status': 'Running'})
        item['categories'].add(s(a.get('Category')).strip())
        item['start'].append(s(a.get('FromDate')))
        item['end'].append(s(a.get('ToDate')))
        item['status'] = s(a.get('AssignmentStatus') or 'Upcoming')
    college_list = []
    for col in colleges(db):
        code = col['collegeCode']
        if code not in by_code:
            continue
        a = by_code[code]
        college_list.append({
            'projectType': 'lesuccess', 'projectId': code, 'projectKey': f'lesuccess:{code}',
            'projectName': col['collegeName'], 'trainerUsername': actor.username,
            'myCategories': sorted(x for x in a['categories'] if x), 'category': ', '.join(sorted(a['categories'])),
            'status': col['status'], 'startDate': min((x for x in a['start'] if x), default=''),
            'endDate': max((x for x in a['end'] if x), default=''),
            'plannedDays': col['totalPlannedDays'], 'logoURL': col['logoURL'],
            'canSubmit': col['status'] == 'Running' and a['status'] == 'Running',
            'progressPercent': col['progressPercent'],
        })
    return college_list + external_projects(db, trainer=actor.username, include_inactive=False)


def reporting_manager(db, actor):
    """Find active RM above trainer (TL -> RM), else active Admin in chain."""
    seen = set()
    person = actor
    admin_candidate = None
    while person and person.username not in seen:
        seen.add(person.username)
        if person.role == 'Reporting Manager' and person.active:
            return person
        if person.role == 'Admin' and person.active:
            admin_candidate = person
        boss = normalize_username(person.reporting_manager_username)
        person = db.scalar(select(User).where(User.username == boss)) if boss else None
    return admin_candidate


def create_update(db, actor, data):
    if actor.role != 'Trainer':
        raise HTTPException(403, 'Trainer role required')
    typ = s(data.get('projectType')).lower()
    if typ not in EXTERNAL_SHEETS:
        return {'success': False, 'message': 'Choose a Vendor or Freelancer project.'}
    identifier = s(data.get('projectId'))
    project = project_record(db, typ, identifier)
    if not project:
        return {'success': False, 'message': 'Project not found.'}
    raw = project.data
    if project_owner(db, raw) != actor.username:
        raise HTTPException(403, 'This project is not assigned to your Employee ID')
    if not actor.active:
        raise HTTPException(403, 'Inactive employee')
    if s(raw.get('Status') or 'Running') != 'Running':
        return {'success': False, 'message': 'Project must be Running to submit training updates.'}
    day = parse_day(data.get('date'))
    start, end = parse_day(raw.get('StartDate')), parse_day(raw.get('EndDate'))
    if not day or (start and day < start) or (end and day > end):
        return {'success': False, 'message': 'Select a valid date within your assignment period.'}
    category = s(raw.get('Category')).strip() or 'General'
    if s(data.get('category')).strip().casefold() != category.casefold():
        return {'success': False, 'message': 'Category does not match the assigned project.'}
    topic = s(data.get('topicCovered')).strip()
    if not topic:
        return {'success': False, 'message': 'Topic covered is required.'}
    raw_attendance = s(data.get('attendance')).strip().rstrip('%')
    attendance = None
    if raw_attendance:
        try:
            attendance = float(raw_attendance)
        except ValueError:
            return {'success': False, 'message': 'Attendance must be between 0 and 100.'}
        if not 0 <= attendance <= 100:
            return {'success': False, 'message': 'Attendance must be between 0 and 100.'}
    if db.scalar(select(ExternalTrainingUpdate).where(
        ExternalTrainingUpdate.project_type == typ,
        ExternalTrainingUpdate.project_id == identifier,
        ExternalTrainingUpdate.trainer_username == actor.username,
        ExternalTrainingUpdate.category == category,
        ExternalTrainingUpdate.training_date == day)):
        return {'success': False, 'message': 'A daily update for this project/category/date already exists.'}
    reviewer = reporting_manager(db, actor)
    if not reviewer:
        return {'success': False, 'message': 'Admin must map an active Reporting Manager for training approvals.'}
    update = ExternalTrainingUpdate(
        update_id=str(uuid4()), project_type=typ, project_id=identifier,
        project_name=s(raw.get('CollegeName')), trainer_username=actor.username,
        trainer_name=actor.full_name, reviewer_username=reviewer.username,
        training_date=day, category=category, topic=topic, attendance=attendance,
        status='Pending', submitted_at=datetime.now(timezone.utc),
    )
    db.add(update)
    db.flush()
    from .workflows import alert
    alert(db, 'Training Update Submitted', reviewer.username,
          f'{actor.full_name} submitted a {typ.title()} update for {update.project_name}.',
          related_assignment=f'{typ}:{identifier}')
    return {'success': True, 'updateID': update.update_id, 'status': 'Pending'}


def format_update(row):
    return {'logID': row.update_id, 'date': row.training_date.strftime('%d %b %Y'),
            'projectType': row.project_type, 'projectId': row.project_id,
            'projectName': row.project_name, 'collegeName': row.project_name,
            'collegeCode': row.project_id, 'category': row.category,
            'topicCovered': row.topic, 'attendance': '' if row.attendance is None else f'{row.attendance:g}%',
            'trainerUsername': row.trainer_username, 'trainerName': row.trainer_name,
            'rmStatus': row.status, 'reviewComments': row.review_comments or '',
            'reviewerUsername': row.reviewer_username}


def update_history(db, actor):
    return [format_update(x) for x in db.scalars(select(ExternalTrainingUpdate)
            .where(ExternalTrainingUpdate.trainer_username == actor.username)
            .order_by(ExternalTrainingUpdate.training_date.desc()))]


def pending_external(db, actor):
    if actor.role not in {'Reporting Manager', 'Admin'}:
        raise HTTPException(403, 'Reporting Manager or Admin required')
    return [{'SyllabusID': row.update_id, 'CollegeCode': row.project_id,
             'CollegeName': row.project_name, 'ProjectType': row.project_type.title(),
             'Category': row.category, 'Topic': row.topic,
             'TrainerUsername': row.trainer_username, 'TrainerName': row.trainer_name,
             'RMStatus': row.status, 'UpdateDate': row.training_date.isoformat()}
            for row in db.scalars(select(ExternalTrainingUpdate).where(
                ExternalTrainingUpdate.status == 'Pending',
                ExternalTrainingUpdate.reviewer_username == actor.username))]


def review_external(db, actor, update_id, decision):
    record = db.scalar(select(ExternalTrainingUpdate).where(ExternalTrainingUpdate.update_id == update_id))
    if not record:
        return None
    if actor.role not in {'Reporting Manager', 'Admin'} or actor.username != record.reviewer_username:
        raise HTTPException(403, 'Only the assigned reviewer can review this submission')
    if record.status != 'Pending':
        return {'success': False, 'message': 'This training update was already reviewed.'}
    if decision not in ('Approved', 'Rejected'):
        return {'success': False, 'message': 'Invalid approval decision.'}
    record.status = decision
    record.reviewed_by = actor.username
    record.reviewed_at = datetime.now(timezone.utc)
    from .workflows import alert
    alert(db, f'Training Update {decision}', record.trainer_username,
          f'{record.project_type.title()} training update for {record.project_name} was {decision.lower()}.',
          related_assignment=f'{record.project_type}:{record.project_id}')
    return {'success': True}


def progress(db, project_type, project_id, planned):
    if project_type == 'lesuccess':
        logs = [x for x in rows(db, 'DailyTrainingLog') if s(x.get('CollegeCode')) == project_id]
        syllabus = [x for x in rows(db, 'Syllabus') if s(x.get('CollegeCode')) == project_id and s(x.get('RMStatus')) == 'Approved']
        approved_ids = {s(x.get('LogID')) for x in syllabus if s(x.get('LogID'))}
        approved_days = len({s(x.get('Date')) for x in logs if s(x.get('LogID')) in approved_ids})
        pending = sum(1 for x in rows(db, 'Syllabus') if s(x.get('CollegeCode')) == project_id and x.get('RMStatus') == 'Pending')
        submitted = len(logs)
    else:
        updates = list(db.scalars(select(ExternalTrainingUpdate).where(
            ExternalTrainingUpdate.project_type == project_type,
            ExternalTrainingUpdate.project_id == project_id)))
        approved_days = len({x.training_date for x in updates if x.status == 'Approved'})
        pending = sum(x.status == 'Pending' for x in updates)
        submitted = len(updates)
    planned = n(planned)
    return {'completedDays': approved_days, 'plannedDays': planned,
            'progressPercent': min(100, round(approved_days / planned * 100)) if planned > 0 else 0,
            'pendingUpdates': pending, 'submittedUpdates': submitted,
            'progressBasis': 'Approved unique training dates'}


def notify_external_assignment(db, typ, record, previous_owner=''):
    """New/moved assignments generate recipient-specific persistent alerts."""
    from .workflows import alert
    owner = project_owner(db, record)
    if owner and s(record.get('Status') or 'Running') in ACTIVE:
        if owner != previous_owner:
            alert(db, 'External Project Assigned', owner,
                  f'{typ.title()} project {s(record.get("CollegeName"))} assigned to you. Open My Projects.',
                  related_assignment=f'{typ}:{s(record.get("ProjectID"))}')
        elif previous_owner:
            alert(db, 'External Project Updated', owner,
                  f'{typ.title()} project {s(record.get("CollegeName"))} assignment was updated.',
                  related_assignment=f'{typ}:{s(record.get("ProjectID"))}')
    if previous_owner and previous_owner != owner:
        alert(db, 'External Assignment Replaced', previous_owner,
              f'Your {typ.title()} project {s(record.get("CollegeName"))} assignment was changed.',
              related_assignment=f'{typ}:{s(record.get("ProjectID"))}')


def external_assignment_notices(db, actor):
    from .workflows import lower
    notes = []
    for x in rows(db, 'Alerts'):
        if lower(x.get('RecipientUserID')) != actor.username or s(x.get('AlertStatus')) == 'Read':
            continue
        typ = s(x.get('AlertType'))
        if typ in ('External Project Assigned', 'External Project Updated', 'External Assignment Replaced',
                   'Training Update Submitted', 'Training Update Approved', 'Training Update Rejected'):
            notes.append({'notificationID': s(x.get('AlertID')), 'collegeCode': '',
                          'collegeName': 'My Projects' if actor.role == 'Trainer' else 'Training Approvals',
                          'projectType': s(x.get('RelatedAssignmentID')).split(':', 1)[0],
                          'message': s(x.get('Message')), 'level': 'blue', 'group': 'attention'})
    return notes
