from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import create_app
from scripts.import_excel import import_workbook
from app.db import SheetRow, User, engine_for, session_factory
from sqlalchemy import select


@pytest.fixture()
def example_db(tmp_path):
    filename = tmp_path / 'source.xlsx'
    url = f'sqlite+pysqlite:///{tmp_path / "test.db"}'
    w = Workbook()
    us = w.active
    us.title = 'Users'
    us.append(['UserID', 'Username', 'Password', 'FullName', 'Role', 'Designation', 'Email',
               'Phone', 'Active', 'CreatedOn', 'ReportingManagerID', 'ReportingManagerName', 'ReportingManagerUsername'])
    us.append(['a1', 'Admin01', 'SafeTestPassword_123', 'The Admin', 'Admin', '', '', '', True, '', '', '', ''])
    us.append(['t1', 'trainer01', 'TrainerPassword_123', 'A Trainer', 'Trainer', '', '', '', True, '', '', '', ''])
    us.append(['t2', 'inactive', 'InactivePassword_123', 'Inactive Trainer', 'Trainer', '', '', '', False, '', '', '', ''])
    cols = w.create_sheet('Colleges')
    cols.append(['CollegeCode', 'CollegeName', 'LogoURL', 'StudentStrength', 'Status', 'StartDate',
                 'EndDate', 'AttendanceSheetLink', 'CreatedBy', 'CreatedOn', 'Notes'])
    cols.append(['A1', 'College Alpha', '', 230, 'Running', '', '', '', 'Admin01', '', ''])
    a = w.create_sheet('TrainerAssignments')
    a.append(['AssignmentID', 'CollegeCode', 'TrainerUsername', 'TrainerName', 'Category', 'FromDate', 'ToDate'])
    a.append(['one', 'A1', 'trainer01', 'A Trainer', 'Soft Skills', '2026-01-01', '2026-01-10'])
    cp = w.create_sheet('CategoryPlanning')
    cp.append(['CollegeCode', 'Category', 'PlannedDays', 'CompletedDays'])
    cp.append(['A1', 'Soft Skills', 20, 5])
    lg = w.create_sheet('DailyTrainingLog')
    lg.append(['LogID', 'CollegeCode', 'Attendance'])
    lg.append(['L1', 'A1', '90%'])
    w.save(filename)
    result = import_workbook(str(filename), url=url)
    assert result['Users'] == 3
    return url


@pytest.fixture()
def client(example_db):
    with TestClient(create_app(example_db)) as c:
        yield c


def call(client, fn, *args):
    return client.post(f'/api/rpc/{fn}', json={'args': list(args)})


def test_protected_and_login(client):
    assert call(client, 'getDashboardData').status_code == 401
    assert call(client, 'login', 'admin01', 'wrong').json()['success'] is False
    assert call(client, 'login', 'inactive', 'InactivePassword_123').json()['success'] is False
    resp = call(client, 'login', 'Admin01', 'SafeTestPassword_123')
    assert resp.json()['success'] is True
    assert resp.cookies.get('ltmp_session')
    cookie = resp.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=lax' in cookie
    assert call(client, 'getDashboardData').status_code == 200


def test_dashboard_and_college_calculations(client):
    call(client, 'login', 'admin01', 'SafeTestPassword_123')
    body = call(client, 'getDashboardData').json()
    assert body['summary']['totalColleges'] == 1
    assert body['summary']['totalTrainers'] == 2
    assert body['summary']['activeTrainers'] == 1
    assert body['colleges'][0]['progressPercent'] == 25
    assert body['colleges'][0]['avgAttendance'] == 90
    assert body['colleges'][0]['trainerNames'] == ['A Trainer']
    assert call(client, 'getMyColleges', 'trainer01').json()[0]['myCategories'] == ['Soft Skills']


def test_user_data_sanitized(example_db, client):
    db = session_factory(engine_for(example_db))()
    try:
        users = db.scalars(select(User)).all()
        assert all(u.password_hash.startswith('$argon2id$') for u in users)
        assert all('SafeTestPassword_123' not in u.password_hash for u in users)
        assert all(r.sheet_name != 'Users' for r in db.scalars(select(SheetRow)))
    finally:
        db.close()
    call(client, 'login', 'admin01', 'SafeTestPassword_123')
    response_text = call(client, 'getUsers').text
    assert 'password' not in response_text.lower()


def test_role_security(client):
    call(client, 'login', 'trainer01', 'TrainerPassword_123')
    assert call(client, 'getUsers').status_code == 403
    assert call(client, 'createVendorProject', {'collegeName': 'Should fail'}).status_code == 403
    assert call(client, 'getMyColleges', 'admin01').status_code == 403


def test_vendor_project_crud(client):
    call(client, 'login', 'admin01', 'SafeTestPassword_123')
    assert call(client, 'createVendorProject', {'collegeName': 'Vendor Campus', 'trainerName': 'A Trainer', 'days': 10, 'startDate':'2026-10-13','endDate':'2026-10-19'}).json()['success']
    project = call(client, 'getVendorProjects').json()[0]
    assert project['collegeName'] == 'Vendor Campus'
    assert call(client, 'updateVendorProject', {'projectID': project['projectID'], 'status': 'Completed'}).json()['success']
    assert call(client, 'getVendorProjects').json()[0]['status'] == 'Completed'
    assert call(client, 'deleteVendorProject', project['projectID'], 'admin01').json()['success']
    assert call(client, 'getVendorProjects').json() == []


def test_unported_action_explicit(client):
    call(client, 'login', 'admin01', 'SafeTestPassword_123')
    result = call(client, 'thisFunctionDoesNotExist', {})
    assert result.status_code == 501
    assert 'not ported' in result.json()['detail']


def test_logout_invalidates_session(client):
    call(client, 'login', 'admin01', 'SafeTestPassword_123')
    assert call(client, 'logout').json()['success']
    assert call(client, 'getDashboardData').status_code == 401


def test_create_college_and_planning(client):
    call(client, 'login', 'admin01', 'SafeTestPassword_123')
    reply = call(client, 'createCollege', {
        'collegeName': 'Beta Engineering College', 'studentStrength': 150,
        'categories': [{'category': 'Aptitude', 'plannedDays': 12}],
        'trainers': [{'trainerUsername': 'trainer01', 'category': 'Aptitude',
                      'fromDate': '2026-02-01', 'toDate': '2026-02-12'}]
    })
    assert reply.status_code == 200
    code = reply.json()['collegeCode']
    assert code == 'BEC001'
    saved = call(client, 'getCollegeProfile', code).json()
    assert saved['college']['collegeName'] == 'Beta Engineering College'
    assert saved['college']['totalPlannedDays'] == 12
    assert saved['college']['trainerCount'] == 1
    assert len(saved['history']) == 1


def test_activity_master_shape(client):
    call(client, 'login', 'admin01', 'SafeTestPassword_123')
    assert call(client, 'getActivityMaster').json() == []
    assert call(client, 'getActivityMasterAdmin', 'admin01').json() == []


def test_admin_leave_management_ui_contract():
    """Guard against hiding pending requests from the Admin navigation again."""
    js = (Path(__file__).resolve().parents[2] / 'frontend' / 'public' / 'legacy.js').read_text()
    admin_menu = js.split('Admin: [', 1)[1].split('],', 1)[0]
    assert "{id:'leave', label:'Leave Management'}" in admin_menu
    assert 'if(isAdminUser()) return;' not in js.split('function renderLeavePage(){', 1)[1].split('function filterLeaveRequests()', 1)[0]
    assert "if(isAdminUser()) loadAdminPendingLeaveCount();" in js
