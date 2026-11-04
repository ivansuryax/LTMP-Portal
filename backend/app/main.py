"""LTMP integrated-development FastAPI implementation.

RPC routes preserve the original Google Apps Script function names while
frontend navigation is incrementally converted to React components.
Unported operations explicitly return HTTP 501 (never silently succeed).
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .db import ImportSheet, SessionToken, SheetRow, User, session_factory, setup_engine
from .queries import active_assignment, colleges, dashboard, d, n, project_list, roster, rows, s, users, assignment_diagnostics
from .security import hash_password, make_session_token, session_digest, verify_password
from .identifiers import username as normalize_username
from .workflows import handle as handle_workflow, alert
from .scheduling import enforce, validate_slot
from .unified_projects import (my_projects, create_update, progress as project_progress,
                               external_projects, project_owner, notify_external_assignment)

ROLES = ['Trainer', 'Team Leader', 'Reporting Manager', 'Admin']
MANAGER = {'Trainer': 'Team Leader', 'Team Leader': 'Reporting Manager', 'Reporting Manager': 'Admin'}
DESIGNATIONS = ['CEO', 'Director', 'Vice President', 'Operations Manager', 'Project Manager']
SESSION_AGE = 60 * 60 * 8


class Call(BaseModel):
    args: list = Field(default_factory=list)


def create_app(db_url=None):
    engine = setup_engine(db_url)
    Factory = session_factory(engine)
    app = FastAPI(title='LTMP API', version='0.2.0')
    # Local Vite uses a separate dev origin; Render serves React and FastAPI from
    # the SAME HTTPS origin so no cross-site cookies/CORS are required.
    is_render_bundle = os.getenv('SERVE_FRONTEND', '').lower() == 'true'
    default_origin = '' if is_render_bundle else 'http://localhost:5173'
    extra_origins = [origin.strip().rstrip('/') for origin in
                     os.getenv('FRONTEND_ORIGIN', default_origin).split(',') if origin.strip()]
    app.add_middleware(CORSMiddleware,
                       allow_origins=extra_origins,
                       allow_credentials=True, allow_methods=['GET', 'POST'],
                       allow_headers=['Content-Type'])

    @app.middleware('http')
    async def verify_post_origin(request: Request, call_next):
        # Browser POST requests include Origin. Enforce it independently of CORS:
        # CORS alone does not prevent state-changing requests/CSRF.
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.url.path.startswith('/api/'):
            origin = request.headers.get('origin', '').rstrip('/')
            if origin:
                secure = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
                protocol = 'https' if secure else request.url.scheme
                host = request.headers.get('host', '')
                expected = f'{protocol}://{host}'
                if origin != expected and origin not in extra_origins:
                    return JSONResponse({'detail': 'Cross-origin request is not permitted'}, status_code=403)
        outgoing = await call_next(request)
        # Render terminates TLS at the edge and redirects HTTP to HTTPS.
        # Secure cookies and HSTS still apply to the public browser origin.
        if os.getenv('COOKIE_SECURE', 'false').lower() == 'true':
            outgoing.headers['Strict-Transport-Security'] = 'max-age=31536000'
        outgoing.headers['X-Content-Type-Options'] = 'nosniff'
        outgoing.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return outgoing

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'stage': 'integrated-development'}

    @app.get('/api/migration/status')
    def migration_status(request: Request):
        with Factory() as db:
            _require_user(db, request)
            result = {name: count for name, count in db.execute(
                select(SheetRow.sheet_name, func.count()).group_by(SheetRow.sheet_name))}
            result['Users'] = db.scalar(select(func.count()).select_from(User))
            return result

    @app.get('/api/admin/account-diagnostics')
    def account_diagnostics(request: Request):
        """Aggregate counts, no passwords or private personal identifiers exposed."""
        with Factory() as db:
            actor = _require_user(db, request)
            _admin(actor)
            breakdown = {}
            for u in db.scalars(select(User)):
                item = breakdown.setdefault(u.role, {'active': 0, 'inactive': 0, 'unmapped_active': 0})
                item['active' if u.active else 'inactive'] += 1
                if u.active and u.role != 'Admin' and not u.reporting_manager_username:
                    item['unmapped_active'] += 1
            return {'roles': breakdown, 'total': sum(v['active'] + v['inactive'] for v in breakdown.values())}

    @app.post('/api/rpc/{name}')
    def rpc(name: str, call: Call, request: Request, response: Response):
        args = call.args
        with Factory.begin() as db:
            if name == 'login':
                if len(args) < 2 or not args[0] or not args[1]:
                    return {'success': False, 'message': 'Invalid username or password.'}
                login_id = normalize_username(args[0])
                person = db.scalar(select(User).where(User.username == login_id))
                # Old installations imported Excel numeric IDs as e.g. 12999.0.
                if person is None and login_id.isdigit():
                    person = db.scalar(select(User).where(User.username == login_id + '.0'))
                if not person or not person.active or not verify_password(s(args[1]), person.password_hash):
                    return {'success': False, 'message': 'Invalid username or password.'}
                token, digest = make_session_token()
                db.add(SessionToken(token_hash=digest, user_id=person.id,
                                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=SESSION_AGE)))
                response.set_cookie('ltmp_session', token, max_age=SESSION_AGE, httponly=True,
                                    secure=os.getenv('COOKIE_SECURE', 'false').lower() == 'true',
                                    samesite='lax', path='/api')
                return {'success': True, 'user': {
                    'username': person.username, 'fullName': person.full_name,
                    'role': person.role, 'designation': person.designation, 'email': person.email}}

            actor = _require_user(db, request)
            # Apply this before routing to ANY mutator (including legacy RPC
            # names). A forged browser username must never grant reassignment.
            if actor.role == 'Trainer' and name in {
                    'assignTrainer', 'removeTrainerAssignment',
                    'updateTrainerAssignmentStatus', 'reassignJob',
                    'createVendorProject', 'updateVendorProject', 'deleteVendorProject',
                    'createFreelanceProject', 'updateFreelanceProject', 'deleteFreelanceProject',
                    'createCollege', 'updateReportingManagerMapping'}:
                raise HTTPException(403, 'Trainers are not permitted to reassign jobs')
            if name == 'logout':
                raw = request.cookies.get('ltmp_session', '')
                session = db.scalar(select(SessionToken).where(SessionToken.token_hash == session_digest(raw)))
                if session:
                    db.delete(session)
                response.delete_cookie('ltmp_session', path='/api')
                return {'success': True}
            if name == 'changePassword':
                if len(args) < 3 or s(args[0]).lower() != actor.username:
                    raise HTTPException(403, 'Can only change your own password')
                if not verify_password(s(args[1]), actor.password_hash):
                    return {'success': False, 'message': 'Current password is incorrect.'}
                if len(s(args[2])) < 10:
                    return {'success': False, 'message': 'Password must contain at least 10 characters.'}
                actor.password_hash = hash_password(s(args[2]))
                db.query(SessionToken).filter(SessionToken.user_id == actor.id).delete(synchronize_session=False)
                response.delete_cookie('ltmp_session', path='/api')
                return {'success': True}

            handled, result = handle_workflow(db, actor, name, args)
            if handled:
                return result

            if name == 'getDashboardData':
                _management(actor)
                return dashboard(db)
            if name == 'getDashboardSummary':
                _management(actor)
                return dashboard(db)['summary']
            if name == 'getTrainerRoster':
                _management(actor)
                return roster(db)
            if name == 'getColleges':
                _management(actor)
                return colleges(db)
            if name == 'getRMColleges':
                _management(actor)
                return [c for c in colleges(db) if c['status'] != 'Cancelled']
            if name == 'getMyProjects':
                _require_self_or_management(actor, args)
                if actor.role != 'Trainer':
                    raise HTTPException(403, 'Trainer portal required')
                return my_projects(db, actor)
            if name == 'getProjectProgress':
                _management(actor)
                summaries = []
                for c in colleges(db):
                    summaries.append({'projectType': 'lesuccess', 'projectId': c['collegeCode'],
                        'projectName': c['collegeName'], **project_progress(db, 'lesuccess', c['collegeCode'], c['totalPlannedDays'])})
                for project in external_projects(db):
                    summaries.append({**project, **project_progress(db, project['projectType'],
                        project['projectId'], project['plannedDays'])})
                return summaries
            if name == 'getMyColleges':
                _require_self_or_management(actor, args)
                target = normalize_username(args[0]) if args else normalize_username(actor.username)
                # Imported numeric employee IDs may be represented as 12999 or 12999.0.
                # Compare normalized identifiers on both sides, including pre-upgrade rows.
                mine = [x for x in rows(db, 'TrainerAssignments')
                        if normalize_username(x.get('TrainerUsername')) == target and active_assignment(x)]
                code_categories = {}
                for assignment in mine:
                    code_categories.setdefault(s(assignment.get('CollegeCode')).strip(), set()).add(s(assignment.get('Category')).strip())
                return [{**c, 'myCategories': sorted(c for c in code_categories[c['collegeCode']] if c)}
                        for c in colleges(db) if c['collegeCode'] in code_categories]
            if name in ('getMyAssignmentStatus', 'getTrainerAssignmentDiagnostics'):
                if name == 'getTrainerAssignmentDiagnostics':
                    _admin(actor)
                    target = normalize_username(args[0]) if args else ''
                    if not target:
                        raise HTTPException(400, 'Trainer username required')
                else:
                    _require_self_or_management(actor, args)
                    target = normalize_username(args[0]) if args else actor.username
                return assignment_diagnostics(db, target)
            if name == 'getCollegeProfile':
                code = s(args[0]) if args else ''
                if actor.role == 'Trainer' and not any(
                    s(a.get('CollegeCode')).strip() == code and
                    normalize_username(a.get('TrainerUsername')) == actor.username and
                    active_assignment(a)
                    for a in rows(db, 'TrainerAssignments')
                ):
                    raise HTTPException(403, 'No current assignment to this college')
                col = next((x for x in colleges(db) if x['collegeCode'] == code), None)
                if not col:
                    return None
                category = [x for x in rows(db, 'CategoryPlanning') if s(x.get('CollegeCode')) == code]
                assignment = [x for x in rows(db, 'TrainerAssignments') if s(x.get('CollegeCode')) == code]
                all_users = {u.username: u.full_name for u in db.scalars(select(User))}
                return {
                    'college': col, 'categories': [{
                        'category': s(x.get('Category')), 'plannedDays': n(x.get('PlannedDays')),
                        'completedDays': n(x.get('CompletedDays')),
                        'progressPercent': round(n(x.get('CompletedDays')) / n(x.get('PlannedDays')) * 100)
                        if n(x.get('PlannedDays')) else 0} for x in category],
                    'trainers': [{
                        'assignmentID': s(x.get('AssignmentID')), 'trainerUsername': s(x.get('TrainerUsername')),
                        'trainerName': all_users.get(s(x.get('TrainerUsername')).lower(), s(x.get('TrainerName'))),
                        'category': s(x.get('Category')), 'fromDate': d(x.get('FromDate')),
                        'toDate': d(x.get('ToDate')), 'assignmentStatus': s(x.get('AssignmentStatus')) or 'Upcoming',
                        'createdBy': s(x.get('CreatedBy'))} for x in assignment],
                    'dailyLog': [x for x in rows(db, 'DailyTrainingLog') if s(x.get('CollegeCode')) == code],
                    'syllabus': [x for x in rows(db, 'Syllabus') if s(x.get('CollegeCode')) == code],
                    'history': [x for x in rows(db, 'StatusHistory') if s(x.get('CollegeCode')) == code]
                }
            if name == 'getVendorProjects':
                _management(actor)
                result = project_list(db, 'vendor')
                return [{**item, **project_progress(db, 'vendor', item['projectID'], item['days'])} for item in result]
            if name == 'getFreelanceProjects':
                _management(actor)
                result = project_list(db, 'freelance')
                return [{**item, **project_progress(db, 'freelance', item['projectID'], item['days'])} for item in result]
            if name == 'getUsers':
                _admin(actor)
                return users(db)
            if name in ('getTrainerUsers', 'getAllTrainerUsersForDropdown'):
                _management(actor)
                query = select(User).where(User.role == 'Trainer')
                if name == 'getTrainerUsers':
                    query = query.where(User.active.is_(True))
                return [{'username': u.username, 'fullName': u.full_name} for u in db.scalars(query)]
            if name in ('getReportingManagers', 'getTeamLeaders', 'getAdmins'):
                role = {'getReportingManagers': 'Reporting Manager', 'getTeamLeaders': 'Team Leader', 'getAdmins': 'Admin'}[name]
                return [{'username': u.username, 'fullName': u.full_name, 'active': u.active,
                         'designation': u.designation} for u in db.scalars(select(User).where(User.role == role))]
            if name == 'getManagersForRole':
                role = MANAGER.get(s(args[0]) if args else '')
                if role is None:
                    return []
                return [{'username': u.username, 'fullName': u.full_name} for u in db.scalars(
                    select(User).where(User.role == role, User.active.is_(True)))]
            if name == 'getAdminDesignationOptions':
                _admin(actor)
                return DESIGNATIONS
            if name == 'getAlertCount':
                return 0 if not rows(db, 'Alerts') else _alert_count(db, actor)
            if name == 'getCategoryWiseProgress':
                _management(actor)
                grouped = {}
                for c in rows(db, 'CategoryPlanning'):
                    v = grouped.setdefault(s(c.get('Category')), {'plannedDays': 0, 'completedDays': 0})
                    v['plannedDays'] += n(c.get('PlannedDays'))
                    v['completedDays'] += n(c.get('CompletedDays'))
                return [{'category': key, **value,
                         'progressPercent': round(100 * value['completedDays'] / value['plannedDays']) if value['plannedDays'] else 0}
                        for key, value in grouped.items()]
            if name == 'getAttendanceReport':
                _management(actor)
                return [{k: c[k] for k in ('collegeCode', 'collegeName', 'avgAttendance', 'logoURL')} for c in colleges(db)]
            if name == 'getStatusWiseReport':
                _management(actor)
                result = {}
                for c in colleges(db):
                    result.setdefault(c['status'], []).append(c['collegeName'])
                return result
            if name == 'getCollegeWiseReport':
                _management(actor)
                return colleges(db)
            if name == 'getTrainerWiseReport':
                _management(actor)
                assigned = {}
                for x in rows(db, 'TrainerAssignments'):
                    if not active_assignment(x):
                        continue
                    key = s(x.get('TrainerUsername'))
                    assigned.setdefault(key, set()).add(s(x.get('CollegeCode')))
                logs = {}
                for log in rows(db, 'DailyTrainingLog'):
                    key = s(log.get('TrainerUsername'))
                    logs[key] = logs.get(key, 0) + 1
                fullnames = {u.username: u.full_name for u in db.scalars(select(User))}
                return [{'trainerUsername': key, 'trainerName': fullnames.get(key.lower(), key),
                         'assignedColleges': len(value), 'sessionsSubmitted': logs.get(key, 0)}
                        for key, value in assigned.items()]
            if name in ('getActivityMaster', 'getActivityMasterAdmin'):
                if name == 'getActivityMasterAdmin':
                    _admin(actor)
                return _activities(db, include_inactive=name == 'getActivityMasterAdmin')
            if name == 'getKpiMasterForAdmin':
                _admin(actor)
                return [{**r, 'id': int(n(r.get('id')))} for r in rows(db, 'KPI Master')]
            if name == 'getClassLocationOptions':
                return sorted({c['collegeName'] for c in colleges(db) if c['collegeName']}) + ['Company Training Center']
            if name == 'getTrainerAvailability':
                _management(actor)
                from .scheduling import check
                return check(db, actor, {'trainerUsername': args[0] if args else '',
                    'startDate': args[1] if len(args)>1 else '',
                    'endDate': args[2] if len(args)>2 else ''})
            if name == 'createCollege':
                _admin(actor)
                return _create_college(db, args, actor)
            if name == 'updateCollege':
                _admin(actor)
                return _update_college(db, args, actor)
            if name in ('createVendorProject', 'createFreelanceProject'):
                _admin(actor)
                return _create_project(db, name == 'createVendorProject', args, actor)
            if name in ('updateVendorProject', 'updateFreelanceProject'):
                _management(actor)
                return _update_project(db, name == 'updateVendorProject', args, actor)
            if name in ('deleteVendorProject', 'deleteFreelanceProject'):
                _admin(actor)
                return _delete_project(db, name == 'deleteVendorProject', args)
            if name == 'reassignJob':
                _management(actor)
                return _reassign_job(db, args, actor)
            if name == 'createUser':
                _admin(actor)
                return _create_user(db, args)
            if name == 'setUserActive':
                _admin(actor)
                return _update_user_field(db, args, 'active')
            if name == 'setUserDesignation':
                _admin(actor)
                return _update_user_field(db, args, 'designation')
            if name == 'updateReportingManagerMapping':
                _admin(actor)
                return _change_manager(db, args)

            # Explicit acknowledgement: partial migration, not a fake backend.
            raise HTTPException(501, f'{name} is not ported yet; original source remains available for next phase')

    # Mount the compiled React frontend LAST. All /api/* endpoints above take
    # precedence; static assets and '/' then work on one Render HTTPS hostname.
    if is_render_bundle:
        dist = Path(os.getenv('FRONTEND_DIST_DIR', '/app/frontend/dist'))
        if not (dist / 'index.html').is_file():
            raise RuntimeError(f'React production build missing: {dist / "index.html"}')
        app.mount('/', StaticFiles(directory=str(dist), html=True), name='ltmp-frontend')

    return app


def _require_user(db, request):
    token = request.cookies.get('ltmp_session', '')
    if not token:
        raise HTTPException(401, 'Please sign in')
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == session_digest(token)))
    if not session or session.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(401, 'Session expired; please sign in again')
    actor = db.get(User, session.user_id)
    if not actor or not actor.active:
        raise HTTPException(401, 'Account is inactive')
    return actor


def _management(user):
    if user.role not in ('Team Leader', 'Reporting Manager', 'Admin'):
        raise HTTPException(403, 'Manager role required')


def _admin(user):
    if user.role != 'Admin':
        raise HTTPException(403, 'Admin permission required')


def _require_self_or_management(actor, args):
    if args and normalize_username(args[0]) != normalize_username(actor.username) and actor.role == 'Trainer':
        raise HTTPException(403, 'Not permitted to read another trainer')


def _alert_count(db, actor):
    return sum(1 for r in rows(db, 'Alerts') if
               s(r.get('RecipientUserID')).lower() in (actor.username, actor.user_id.lower())
               and s(r.get('AlertStatus')).lower() not in ('read', 'dismissed'))


def _activities(db, include_inactive=False):
    data = rows(db, 'ActivityMaster')
    if not include_inactive:
        data = [r for r in data if s(r.get('Active')).lower() in ('true', '1', 'yes')]
    if include_inactive:
        return [{'code': s(r.get('ActivityCode')), 'name': s(r.get('ActivityName')),
                 'active': s(r.get('Active')).lower() in ('true', '1', 'yes'),
                 'createdBy': s(r.get('CreatedBy')), 'createdOn': d(r.get('CreatedOn'))}
                for r in data]
    return [{'code': s(r.get('ActivityCode')), 'name': s(r.get('ActivityName'))} for r in data]


def _availability(db, args):
    # Read-only approximation; leave approval workflows are not yet ported.
    if len(args) < 3:
        raise HTTPException(400, 'Expected trainer, start and end date')
    person, start, end = s(args[0]).lower(), s(args[1]), s(args[2])
    overlap = [r for r in rows(db, 'LeaveRequests') if s(r.get('EmployeeUsername')).lower() == person
               and s(r.get('Status')) == 'Approved' and s(r.get('StartDate')) <= end
               and s(r.get('EndDate')) >= start]
    return {'available': not overlap, 'alerts': [{'type': 'leave', 'message': 'Approved leave overlaps selected dates.'} for _ in overlap]}


def _arg_payload(args):
    if not args or not isinstance(args[0], dict):
        raise HTTPException(400, 'Expected payload object')
    return args[0]


def _insert_row(db, sheet, data):
    max_row = db.scalar(select(func.max(SheetRow.source_row)).where(SheetRow.sheet_name == sheet)) or 1
    db.add(SheetRow(sheet_name=sheet, source_row=max_row + 1, data=data))


def _create_project(db, vendor, args, actor=None):
    p = _arg_payload(args)
    sheet = 'VendorProjects' if vendor else 'FreelanceProjects'
    trainer_name_key = 'TrainerName' if vendor else 'FreelancerName'
    if not s(p.get('collegeName')).strip():
        return {'success': False, 'message': 'College name is required.'}
    person_id = normalize_username(p.get('trainerUsername'))
    chosen = db.scalar(select(User).where(User.username == person_id)) if person_id else None
    if vendor and not chosen:
        by_name = s(p.get('trainerName')).strip().lower()
        matches = list(db.scalars(select(User).where(func.lower(User.full_name) == by_name))) if by_name else []
        chosen = matches[0] if len(matches) == 1 else None
    if person_id and not chosen:
        return {'success': False, 'message': 'Selected Trainer Employee ID does not exist.'}
    if vendor and chosen and chosen.role != 'Trainer':
        return {'success': False, 'message': 'Vendor project trainer must be a Trainer user.'}
    validate_slot(p.get('startDate'), p.get('endDate'), p.get('startTime'), p.get('endTime'))
    conflict_rows = enforce(db, actor, {**p, 'trainerUsername': chosen.username}) if chosen else []
    values = {'ProjectID': str(uuid4()), 'Vendor': s(p.get('vendor')),
              'CollegeName': s(p.get('collegeName')), 'LogoURL': s(p.get('logoURL')),
              trainer_name_key: (chosen.full_name if vendor and chosen else s(p.get('trainerName'))) if vendor else s(p.get('freelancerName')),
              'TrainerUsername': chosen.username if chosen else '', 'Days': n(p.get('days')),
              'Category': s(p.get('category')), 'Status': s(p.get('status')) or 'Running',
              'StartDate': s(p.get('startDate')), 'EndDate': s(p.get('endDate')),
              'StartTime': s(p.get('startTime')), 'EndTime': s(p.get('endTime')),
              'Batch': s(p.get('batch')), 'Location': s(p.get('location')),
              'Comments': s(p.get('comments')),
              'CreatedBy': s(p.get('createdBy')), 'CreatedOn': datetime.now(timezone.utc).isoformat()}
    _insert_row(db, sheet, values)
    # A typed portal assignment needs an unambiguous employee account; free-text
    # freelancer names are preserved as external records without portal access.
    notify_external_assignment(db, 'vendor' if vendor else 'freelance', values)
    if conflict_rows:
        alert(db, 'Schedule Override', actor.username,
              f'Admin acknowledged {len(conflict_rows)} booking conflict(s) for {chosen.full_name} — {values["CollegeName"]}.',
              related_assignment=values['ProjectID'])
    return {'success': True, 'projectID': values['ProjectID'],
            'portalAssignment': bool(project_owner(db, values))}


def _update_project(db, vendor, args, actor):
    p = _arg_payload(args)
    sheet = 'VendorProjects' if vendor else 'FreelanceProjects'
    row = next((r for r in db.scalars(select(SheetRow).where(SheetRow.sheet_name == sheet))
                if s(r.data.get('ProjectID')) == s(p.get('projectID'))), None)
    if not row:
        return {'success': False, 'message': 'Project not found.'}
    if actor.role != 'Admin':
        allowed_manager_fields = {'projectID', 'trainerUsername', 'startDate',
                                  'endDate', 'startTime', 'endTime', 'batch',
                                  'acknowledgeConflict'}
        if set(p) - allowed_manager_fields:
            raise HTTPException(403, 'Managers can change assignment ownership/schedule only')
    mapping = {'vendor': 'Vendor', 'collegeName': 'CollegeName', 'logoURL': 'LogoURL',
               'trainerUsername': 'TrainerUsername', 'trainerName': 'TrainerName',
               'freelancerName': 'FreelancerName', 'days': 'Days', 'category': 'Category',
               'status': 'Status', 'startDate': 'StartDate', 'endDate': 'EndDate',
               'startTime': 'StartTime', 'endTime': 'EndTime', 'batch': 'Batch',
               'location': 'Location', 'comments': 'Comments'}
    allowed = {k: v for k, v in mapping.items() if (vendor and k != 'freelancerName') or
               (not vendor and k != 'trainerName')}
    previous_owner = project_owner(db, row.data)
    changed = {column: p[key] for key, column in allowed.items() if key in p}
    if 'TrainerUsername' in changed:
        chosen_id = normalize_username(changed['TrainerUsername'])
        if chosen_id and not db.scalar(select(User).where(User.username == chosen_id, User.role == 'Trainer')):
            return {'success': False, 'message': 'Select a valid Trainer Employee ID.'}
        changed['TrainerUsername'] = chosen_id
    if vendor and changed.get('TrainerUsername'):
        user = db.scalar(select(User).where(User.username == changed['TrainerUsername']))
        changed['TrainerName'] = user.full_name
    candidate = {**row.data, **changed}
    validate_slot(candidate.get('StartDate'), candidate.get('EndDate'),
                  candidate.get('StartTime'), candidate.get('EndTime'))
    selected_owner = project_owner(db, candidate)
    conflict_rows = []
    if selected_owner:
        conflict_rows = enforce(db, actor, {
            'trainerUsername': selected_owner, 'startDate': candidate.get('StartDate'),
            'endDate': candidate.get('EndDate'), 'startTime': candidate.get('StartTime'),
            'endTime': candidate.get('EndTime'), 'status': candidate.get('Status'),
            'acknowledgeConflict': p.get('acknowledgeConflict', False)},
            exclude_type='vendor' if vendor else 'freelance', exclude_id=s(candidate.get('ProjectID')))
    row.data = candidate
    notify_external_assignment(db, 'vendor' if vendor else 'freelance', row.data, previous_owner)
    if conflict_rows:
        alert(db, 'Schedule Override', actor.username,
              f'Admin acknowledged {len(conflict_rows)} booking conflict(s) for {selected_owner} — {s(candidate.get("CollegeName"))}.',
              related_assignment=s(candidate.get('ProjectID')))
    return {'success': True, 'portalAssignment': bool(project_owner(db, row.data))}



def _reassign_job(db, args, actor):
    p = _arg_payload(args)
    typ = s(p.get('projectType')).lower()
    if typ not in ('vendor', 'freelance', 'lesuccess'):
        raise HTTPException(400, 'Choose a valid project type')
    if typ == 'lesuccess':
        # LeSuccess's category-specific assignment has a dedicated guarded RPC.
        raise HTTPException(400, 'Use assignTrainer to change a LeSuccess trainer/category')
    change = {'projectID': s(p.get('projectId')),
              'trainerUsername': normalize_username(p.get('trainerUsername')),
              'acknowledgeConflict': p.get('acknowledgeConflict', False)}
    for key in ('startDate', 'endDate', 'startTime', 'endTime', 'batch'):
        if key in p:
            change[key] = p[key]
    return _update_project(db, typ == 'vendor', [change], actor)


def _delete_project(db, vendor, args):
    if not args:
        raise HTTPException(400, 'Project ID required')
    sheet = 'VendorProjects' if vendor else 'FreelanceProjects'
    item = next((r for r in db.scalars(select(SheetRow).where(SheetRow.sheet_name == sheet))
                 if s(r.data.get('ProjectID')) == s(args[0])), None)
    if not item:
        return {'success': False, 'message': 'Project not found.'}
    db.delete(item)
    return {'success': True}


def _create_user(db, args):
    p = _arg_payload(args)
    username = normalize_username(p.get('employeeId') or p.get('username'))
    role = s(p.get('role'))
    password = s(p.get('password'))
    if not username or role not in ROLES:
        return {'success': False, 'message': 'Valid employee ID and role required.'}
    if len(password) < 10:
        return {'success': False, 'message': 'Password must be at least 10 characters.'}
    if db.scalar(select(User).where(User.username.in_([username, username + '.0']))):
        return {'success': False, 'message': 'Employee ID already exists.'}
    boss_name = normalize_username(p.get('reportingManagerUsername'))
    if role != 'Admin':
        boss = db.scalar(select(User).where(User.username == boss_name))
        if not boss or not boss.active or boss.role != MANAGER[role]:
            return {'success': False, 'message': 'Choose an active direct manager of the correct role.'}
    db.add(User(user_id=username, username=username, password_hash=hash_password(password),
                full_name=s(p.get('fullName')), role=role, designation=s(p.get('designation')),
                email=s(p.get('email')), phone=s(p.get('phone')), active=True,
                reporting_manager_username=boss_name))
    return {'success': True}


def _update_user_field(db, args, field):
    if len(args) < 2:
        raise HTTPException(400, 'Username and value required')
    user = db.scalar(select(User).where(User.username == s(args[0]).lower()))
    if not user:
        return {'success': False, 'message': 'User not found.'}
    if field == 'active':
        active = args[1] is True or s(args[1]).lower() in ('true', '1')
        user.active = active
        if not active:
            db.query(SessionToken).filter(SessionToken.user_id == user.id).delete(synchronize_session=False)
    else:
        val = s(args[1])
        if val and val not in DESIGNATIONS:
            return {'success': False, 'message': 'Invalid designation.'}
        user.designation = val
    return {'success': True}


def _change_manager(db, args):
    if len(args) < 2:
        raise HTTPException(400, 'Employee and manager required')
    subordinate = db.scalar(select(User).where(User.username == s(args[0]).lower()))
    manager = db.scalar(select(User).where(User.username == s(args[1]).lower()))
    if not subordinate or not manager:
        return {'success': False, 'message': 'Employee or manager not found.'}
    if not manager.active:
        return {'success': False, 'message': 'The selected manager account is inactive.'}
    if MANAGER.get(subordinate.role) != manager.role:
        return {'success': False, 'message': 'Manager must be exactly one role above employee.'}
    subordinate.reporting_manager_username = manager.username
    return {'success': True}


app = create_app()


def _college_code(db, name):
    import re
    initials = ''.join(word[0] for word in re.sub(r'[^a-zA-Z ]', '', name).split() if word).upper()[:4] or 'LSC'
    existing = {s(r.get('CollegeCode')) for r in rows(db, 'Colleges')}
    index = 1
    while f'{initials}{index:03d}' in existing:
        index += 1
    return f'{initials}{index:03d}'


def _create_college(db, args, actor):
    p = _arg_payload(args)
    college_name = s(p.get('collegeName')).strip()
    if not college_name:
        return {'success': False, 'message': 'College name is required.'}
    categories = p.get('categories', [])
    if not isinstance(categories, list):
        return {'success': False, 'message': 'Categories must be a list.'}
    names = [s(r.get('category')).strip().lower() for r in categories if isinstance(r, dict)]
    if len(names) != len(set(names)) or any(not name for name in names):
        return {'success': False, 'message': 'Categories cannot be blank or duplicated.'}
    if any(n(r.get('plannedDays')) < 0 for r in categories if isinstance(r, dict)):
        return {'success': False, 'message': 'Planned days must be nonnegative.'}
    if s(p.get('startDate')) and s(p.get('endDate')) and s(p.get('endDate')) < s(p.get('startDate')):
        return {'success': False, 'message': 'End date cannot precede start date.'}
    # Validate initial trainer assignments and overlaps before writing any rows.
    initial_overrides = {}
    for item in p.get('trainers', []):
        if not s(item.get('trainerUsername')).strip():
            continue
        category = s(item.get('category')).strip()
        if not category or category.lower() not in names:
            return {'success': False, 'message': 'Trainer assignment category must match a planned category.'}
        start, end = s(item.get('fromDate')).strip(), s(item.get('toDate')).strip()
        if not start or not end or start > end:
            return {'success': False, 'message': 'Trainer assignments need valid From and To dates.'}
        state = s(item.get('assignmentStatus')) or 'Upcoming'
        if state not in ('Upcoming', 'Running', 'On Hold', 'Completed', 'Not Active'):
            return {'success': False, 'message': 'Invalid initial trainer assignment status.'}
        validate_slot(start, end, item.get('startTime'), item.get('endTime'), require_dates=True)
        overlaps = enforce(db, actor, item, start_key='fromDate', end_key='toDate')
        if overlaps:
            initial_overrides[(s(item.get('trainerUsername')), category)] = overlaps
    code = _college_code(db, college_name)
    _insert_row(db, 'Colleges', {
        'CollegeCode': code, 'CollegeName': college_name, 'LogoURL': s(p.get('logoURL')),
        'StudentStrength': n(p.get('studentStrength')),
        'Status': s(p.get('status')) or 'Upcoming',
        'StartDate': s(p.get('startDate')), 'EndDate': s(p.get('endDate')),
        'AttendanceSheetLink': s(p.get('attendanceSheetLink')),
        'CreatedBy': actor.username, 'CreatedOn': datetime.now(timezone.utc).isoformat(),
        'Notes': s(p.get('notes'))
    })
    for cat in categories:
        if not s(cat.get('category')).strip():
            continue
        _insert_row(db, 'CategoryPlanning', {
            'CollegeCode': code, 'Category': s(cat['category']),
            'PlannedDays': n(cat.get('plannedDays')), 'CompletedDays': 0
        })
    for item in p.get('trainers', []):
        if not s(item.get('trainerUsername')).strip():
            continue
        target = db.scalar(select(User).where(User.username == s(item['trainerUsername']).lower()))
        if not target or target.role != 'Trainer' or not target.active:
            raise HTTPException(400, 'Unknown trainer in assignment')
        assignment_id = str(uuid4())
        _insert_row(db, 'TrainerAssignments', {
            'AssignmentID': assignment_id, 'CollegeCode': code,
            'TrainerUsername': target.username, 'TrainerName': target.full_name,
            'Category': s(item.get('category')).strip(), 'FromDate': s(item.get('fromDate')),
            'ToDate': s(item.get('toDate')), 'StartTime': s(item.get('startTime')),
            'EndTime': s(item.get('endTime')), 'Batch': s(item.get('batch')),
            'AssignmentStatus': s(item.get('assignmentStatus')) or 'Upcoming',
            'ActualCompletedDays': 0, 'PlannedDays': n(item.get('plannedDays')),
            'CurrentAssignment': s(item.get('assignmentStatus') or 'Upcoming') in ('Upcoming', 'Running', 'On Hold'),
            'CreatedBy': actor.username, 'CreatedOn': datetime.now(timezone.utc).isoformat()
        })
        alert(db, 'Trainer Assigned', target.username,
              f'You have been assigned to {college_name} — {s(item.get("category")).strip()}.',
              related_assignment=assignment_id)
        recorded = initial_overrides.get((s(item.get('trainerUsername')), s(item.get('category')).strip()))
        if recorded:
            alert(db, 'Schedule Override', actor.username,
                  f'Admin acknowledged {len(recorded)} overlapping booking(s) for {target.full_name} — {college_name}.',
                  related_assignment=assignment_id)
    _insert_row(db, 'StatusHistory', {
        'StatusTimelineID': str(uuid4()), 'CollegeCode': code,
        'Activity': (s(p.get('status')) or 'Upcoming') + ' - project created',
        'Date': datetime.now(timezone.utc).isoformat(), 'RecordedBy': actor.username
    })
    return {'success': True, 'collegeCode': code}


def _update_college(db, args, actor):
    p = _arg_payload(args)
    code = s(p.get('collegeCode'))
    row = next((r for r in db.scalars(select(SheetRow).where(SheetRow.sheet_name == 'Colleges'))
                if s(r.data.get('CollegeCode')) == code), None)
    if not row:
        return {'success': False, 'message': 'College not found.'}
    mapping = {'collegeName': 'CollegeName', 'logoURL': 'LogoURL', 'studentStrength': 'StudentStrength',
               'startDate': 'StartDate', 'endDate': 'EndDate', 'attendanceSheetLink': 'AttendanceSheetLink',
               'notes': 'Notes', 'status': 'Status'}
    updated = {**row.data, **{v: p[k] for k, v in mapping.items() if k in p}}
    changed_status = 'status' in p and updated.get('Status') != row.data.get('Status')
    row.data = updated
    if changed_status:
        _insert_row(db, 'StatusHistory', {
            'StatusTimelineID': str(uuid4()), 'CollegeCode': code,
            'Activity': 'Training ' + s(updated.get('Status')),
            'Date': datetime.now(timezone.utc).isoformat(), 'RecordedBy': actor.username
        })
    return {'success': True}
