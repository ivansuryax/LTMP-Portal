"""Regression tests derived from the supplied LTMP functionality traversal report.
Uses disposable fixtures; never prints or stores original employee passwords.
"""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

from app.db import User, SheetRow, session_factory, setup_engine
from app.main import create_app
from app.security import hash_password
from app.identifiers import username
from scripts.import_excel import import_workbook
from scripts.repair_identifiers import repair


@pytest.fixture()
def env(tmp_path):
    url = f'sqlite+pysqlite:///{tmp_path / "audit.db"}'
    Factory = session_factory(setup_engine(url))
    with Factory.begin() as db:
        for name, role, boss in [('admin', 'Admin', ''), ('rm', 'Reporting Manager', 'admin'),
                                 ('lead', 'Team Leader', 'rm'), ('trainer', 'Trainer', 'lead'),
                                 ('lead2', 'Team Leader', 'rm'), ('trainer2', 'Trainer', 'lead2')]:
            db.add(User(username=name, user_id=name, role=role, full_name=name.title(),
                        password_hash=hash_password('testing-only-strong-password'),
                        reporting_manager_username=boss, active=True))
        db.add(SheetRow(sheet_name='KPI Master', source_row=2,
                        data={'id': 1, 'category': 'Performance', 'parameter': 'Delivery', 'target': 0.05}))
        db.add(SheetRow(sheet_name='ActivityMaster', source_row=2,
                        data={'ActivityCode': 'ACT', 'ActivityName': 'Workshop', 'Active': True}))
    with TestClient(create_app(url)) as client:
        yield client, url


def rpc(client, name, *args):
    return client.post('/api/rpc/' + name, json={'args': list(args)})


def log(client, username):
    result = rpc(client, 'login', username, 'testing-only-strong-password')
    assert result.json().get('success') is True


def setup_college(c):
    log(c, 'admin')
    created = rpc(c, 'createCollege', {'collegeName': 'Example College', 'status': 'Running',
        'categories': [{'category': 'Communication', 'plannedDays': 15}]}).json()
    assert created['success']
    return created['collegeCode']


def assign(c, code, employee='trainer', status='Running'):
    log(c, 'admin')
    result = rpc(c, 'assignTrainer', {'collegeCode': code, 'trainerUsername': employee,
        'category': 'Communication', 'fromDate': '2026-10-01', 'toDate': '2026-10-31',
        'assignmentStatus': status}).json()
    assert result['success']


def test_numeric_username_login_and_repair_preexisting_database(env):
    c, url = env
    factory = session_factory(setup_engine(url))
    with factory.begin() as db:
        u = db.scalar(select(User).where(User.username == 'lead'))
        u.username = '12999.0'
        subordinate = db.scalar(select(User).where(User.username == 'trainer'))
        subordinate.reporting_manager_username = '12999.0'
        db.add(SheetRow(sheet_name='LeaveRequests', source_row=2,
            data={'LeaveID': 'one', 'EmployeeUsername': 'trainer',
                  'ReportingManagerUsername': '12999.0', 'Status': 'Pending'}))
    result = rpc(c, 'login', '12999', 'testing-only-strong-password').json()
    assert result['success']
    assert result['user']['role'] == 'Team Leader'
    out = repair(url)
    assert out['normalized_usernames'] == 1
    assert repair(url)['normalized_usernames'] == 0
    with factory() as db:
        assert db.scalar(select(User).where(User.username == '12999'))
        leave = db.scalar(select(SheetRow).where(SheetRow.sheet_name == 'LeaveRequests'))
        assert leave.data['ReportingManagerUsername'] == '12999'
    assert rpc(c, 'login', '12999', 'testing-only-strong-password').json()['success']


def test_roles_and_permission_guards(env):
    c, _ = env
    for role in ['trainer', 'lead', 'rm', 'admin']:
        log(c, role)
        assert rpc(c, 'getKpiDashboardData', role).status_code == 200
        assert rpc(c, 'getLeaveRequests', role).status_code == 200
    log(c, 'trainer')
    assert rpc(c, 'createUser', {'employeeId':'evil', 'role':'Admin','password':'longsecretpassword'}).status_code == 403
    assert c.get('/api/admin/account-diagnostics').status_code == 403
    log(c, 'admin')
    breakdown = c.get('/api/admin/account-diagnostics').json()
    assert breakdown['roles']['Reporting Manager']['active'] == 1
    assert breakdown['roles']['Team Leader']['active'] == 2


def test_inactive_manager_and_role_validation(env):
    c, _ = env
    log(c, 'admin')
    assert rpc(c, 'setUserActive', 'lead', False).json()['success']
    bad = rpc(c, 'createUser', {'employeeId': 'fresh', 'role':'Trainer',
        'password':'longsecretpassword', 'reportingManagerUsername':'lead'}).json()
    assert bad['success'] is False
    assert rpc(c, 'login', 'lead', 'testing-only-strong-password').json()['success'] is False


def test_college_and_assignment_lifecycle(env):
    c, _ = env
    log(c, 'admin')
    assert rpc(c, 'createCollege', {'collegeName':'Bad', 'categories':[
        {'category':'Communication','plannedDays':1}, {'category':'Communication','plannedDays':2}]}).json()['success'] is False
    assert rpc(c, 'createCollege', {'collegeName':'Bad', 'categories':[
        {'category':'Communication','plannedDays':-2}]}).json()['success'] is False
    code = setup_college(c)
    assert rpc(c, 'assignTrainer', {'collegeCode':code,'trainerUsername':'trainer',
        'category':'Communication','fromDate':'2026-10-31','toDate':'2026-10-01'}).json()['success'] is False
    assign(c, code)
    assert rpc(c, 'getDashboardData').json()['summary']['activeTrainers'] == 1
    profile = rpc(c, 'getCollegeProfile', code).json()
    assert profile['college']['trainerCount'] == 1
    aid = profile['trainers'][0]['assignmentID']
    assert rpc(c, 'updateTrainerAssignmentStatus', aid, 'Completed', 'admin', '').json()['success']
    assert rpc(c, 'getDashboardData').json()['summary']['activeTrainers'] == 0
    log(c, 'trainer')
    assert rpc(c, 'getMyColleges', 'trainer').json() == []


def test_daily_updates_deduplicate_rejected_bad_attendance_and_syllabus(env):
    c, _ = env
    code = setup_college(c)
    assign(c, code)
    log(c, 'trainer')
    body = {'trainerUsername':'trainer','collegeCode':code,'category':'Communication',
            'date':'2026-10-14','topicCovered':'Introduction', 'attendance':'85%'}
    assert rpc(c,'submitDailyUpdate',body).json()['success']
    assert rpc(c,'submitDailyUpdate',body).json()['success'] is False
    wrong = {**body, 'date': '2026-10-15', 'attendance':'110%'}
    assert rpc(c,'submitDailyUpdate',wrong).json()['success'] is False
    new = {**body, 'date': '2026-10-15'}
    assert rpc(c,'submitDailyUpdate',new).json()['success']
    own = rpc(c,'getMyDailyUpdates','trainer').json()
    assert len(own) == 2
    assert rpc(c,'getMyColleges','trainer').json()[0]['completedDays'] == 2
    log(c, 'rm')
    queue = rpc(c, 'getPendingApprovals',code).json()
    assert len(queue) == 2
    assert rpc(c, 'approveSyllabus',queue[0]['SyllabusID'],'rm','Approved').json()['success']
    log(c, 'trainer')
    statuses = {r['date']:r['rmStatus'] for r in rpc(c,'getMyDailyUpdates','trainer').json()}
    assert set(statuses.values()) == {'Approved','Pending'}


def test_unrelated_rm_cannot_review_syllabus(env):
    c,_=env
    code=setup_college(c);assign(c,code)
    log(c,'trainer')
    assert rpc(c,'submitDailyUpdate',{'trainerUsername':'trainer','collegeCode':code,
          'category':'Communication','date':'2026-10-14','topicCovered':'Demo'}).json()['success']
    log(c,'rm')
    item=rpc(c,'getPendingApprovals',code).json()[0]
    log(c,'lead')
    assert rpc(c,'approveSyllabus',item['SyllabusID'],'lead','Approved').status_code==403
    log(c,'rm')
    assert rpc(c,'approveSyllabus',item['SyllabusID'],'rm','Rejected').json()['success']
    assert rpc(c,'approveSyllabus',item['SyllabusID'],'rm','Approved').json()['success'] is False


def test_leave_overlap_and_review_stamped(env):
    c,_=env
    log(c,'trainer')
    data={'employeeUsername':'trainer','startDate':'2026-10-14','endDate':'2026-10-16','comments':'personal'}
    assert rpc(c,'submitLeaveRequest',data).json()['success']
    assert rpc(c,'submitLeaveRequest',data).json()['success'] is False
    log(c,'admin')
    leaves=rpc(c,'getLeaveRequests','admin').json()
    assert len(leaves)==1 and leaves[0]['reportingManagerUsername']=='lead'
    assert rpc(c,'reviewLeaveRequest',leaves[0]['leaveID'],'admin','Approved','').status_code==403
    log(c,'lead')
    assert rpc(c,'reviewLeaveRequest',leaves[0]['leaveID'],'lead','Approved','okay').json()['success']


def test_tracker_review_stamped_after_reassignment(env):
    c,_=env
    log(c,'trainer')
    body={'trainerUsername':'trainer','date':'2026-10-14','activityCode':'ACT',
          'hours':4,'topicCovered':'Presentations'}
    assert rpc(c,'submitDailyActivity',body).json()['success']
    assert rpc(c,'submitDailyActivity',{**body,'hours':21}).json()['success'] is False
    log(c,'admin')
    assert rpc(c,'updateReportingManagerMapping','trainer','lead2').json()['success']
    log(c,'lead2')
    assert rpc(c,'getDailyActivityApprovals','lead2').json()==[]
    log(c,'lead')
    first=rpc(c,'getDailyActivityApprovals','lead').json()
    assert len(first)==1
    assert rpc(c,'reviewDailyActivity',first[0]['entryID'],'lead','Approved','').json()['success']


def test_kpi_original_excel_percent_and_stamped_review(env):
    c,_=env
    log(c,'trainer')
    own=rpc(c,'getKpiDashboardData','trainer').json()['myKpis'][0]
    assert own['target']=='5%'
    assert rpc(c,'submitRating','trainer',1,5).json()['success']
    log(c,'admin')
    assert rpc(c,'updateReportingManagerMapping','trainer','lead2').json()['success']
    log(c,'lead2')
    assert not any(x['status']=='Submitted' for x in rpc(c,'getKpiDashboardData','lead2').json()['teamKpis'])
    log(c,'lead')
    assert any(x['status']=='Submitted' for x in rpc(c,'getKpiDashboardData','lead').json()['teamKpis'])
    assert rpc(c,'decideOnRating','lead',1,'trainer','Approved','').json()['success']


def test_vendor_trainer_identity(env):
    c,_=env
    log(c,'admin')
    created=rpc(c,'createVendorProject',{'vendor':'Vendor', 'collegeName':'Example',
           'trainerName':'Trainer','trainerUsername':'trainer','status':'Running', 'startDate':'2026-10-13', 'endDate':'2026-10-19'}).json()
    assert created['success']
    item=rpc(c,'getVendorProjects').json()[0]
    assert item['trainerUsername']=='trainer'


def test_original_workbook_role_logins_and_import_types(tmp_path):
    source = Path(__file__).resolve().parents[2] / 'imports' / 'LTMP.xlsx'
    if not source.exists():
        pytest.skip('Private workbook omitted in source-only package')
    url=f'sqlite+pysqlite:///{tmp_path / "real-data.db"}'
    counts=import_workbook(str(source),url=url)
    assert counts['Users']==119
    sheet=load_workbook(source,data_only=True,read_only=True)['Users']
    it=sheet.values;head=next(it)
    people=[dict(zip(head,row)) for row in it if any(value is not None for value in row)]
    with TestClient(create_app(url)) as client:
        for role in ['Admin','Reporting Manager','Team Leader','Trainer']:
            sample=next(p for p in people if p['Role']==role and p['Active'] is True)
            result=rpc(client,'login',username(sample['Username']),str(sample['Password'])).json()
            assert result['success'] is True, f'{role} login failed'
            assert result['user']['role']==role
        active_numeric=[p for p in people if p['Active'] is True and isinstance(p['Username'],float)]
        assert active_numeric
        tested_active = 0
        tested_inactive = 0
        for sample in people:
            auth = rpc(client,'login',username(sample['Username']),str(sample['Password'])).json()
            expected = sample['Active'] is True
            assert auth['success'] is expected, f'Imported {sample["Role"]} account state mismatch'
            if expected: tested_active += 1
            else: tested_inactive += 1
        assert tested_active == 59
        assert tested_inactive == 60
