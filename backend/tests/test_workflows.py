"""Workflow regression tests against a temporary sqlite DB; no real user data."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import create_app
from app.db import User, SheetRow, setup_engine, session_factory
from app.security import hash_password


@pytest.fixture()
def env(tmp_path):
    url = f'sqlite+pysqlite:///{tmp_path / "flow.db"}'
    db = session_factory(setup_engine(url))
    people = [('admin', 'Admin', ''), ('rm', 'Reporting Manager', 'admin'),
              ('lead', 'Team Leader', 'rm'), ('trainer', 'Trainer', 'lead'),
              ('other', 'Trainer', 'lead')]
    with db.begin() as session:
        for username, role, boss in people:
            session.add(User(user_id=username, username=username, full_name=username.title(),
                role=role, password_hash=hash_password('password-test-123'),
                reporting_manager_username=boss, active=True))
        session.add(SheetRow(sheet_name='KPI Master', source_row=2,
                data={'id': 1, 'category': 'Quality', 'parameter': 'Delivery', 'target': '5%'}))
        session.add(SheetRow(sheet_name='ActivityMaster', source_row=2,
                data={'ActivityCode': 'TEST', 'ActivityName': 'Demo', 'Active': True}))
    with TestClient(create_app(url)) as client:
        yield client


def call(client, method, *args):
    return client.post(f'/api/rpc/{method}', json={'args': list(args)})


def login(client, name):
    result = call(client, 'login', name, 'password-test-123')
    assert result.status_code == 200
    assert result.json()['success']


def test_college_assignment_daily_and_syllabus(env):
    login(env, 'admin')
    c = call(env, 'createCollege', {'collegeName': 'Test School', 'status': 'Running',
        'categories': [{'category': 'Communication', 'plannedDays': 3}]}).json()
    assert c['success']
    code = c['collegeCode']
    assert call(env, 'assignTrainer', {'collegeCode': code, 'trainerUsername': 'trainer',
        'category': 'Communication', 'fromDate': '2026-10-10', 'toDate': '2026-10-20'}).json()['success']
    # update planning must preserve completed-days progress
    assert call(env, 'updateCategoryPlanning', code, [{'category': 'Communication', 'plannedDays': 5}], 'admin').json()['success']
    profile = call(env, 'getCollegeProfile', code).json()
    assert profile['categories'][0]['plannedDays'] == 5
    assert len(profile['trainers']) == 1
    a_id = profile['trainers'][0]['assignmentID']
    assert call(env, 'updateTrainerAssignmentStatus', a_id, 'Running', 'admin', 'Started').json()['success']
    assert len(call(env, 'getTrainerAssignmentStatusTimeline', a_id).json()) == 2
    login(env, 'trainer')
    assert call(env, 'submitDailyUpdate', {'trainerUsername': 'trainer', 'collegeCode': code,
        'category': 'Communication', 'date': '2026-10-14', 'topicCovered': 'Introduction',
        'attendance': '85%'}).json()['success']
    assert call(env, 'getCollegeProfile', code).json()['categories'][0]['completedDays'] == 1
    assert len(call(env, 'getMyDailyUpdates', 'trainer').json()) == 1
    login(env, 'rm')
    approvals = call(env, 'getPendingApprovals', code).json()
    assert len(approvals) == 1
    assert call(env, 'approveSyllabus', approvals[0]['SyllabusID'], 'rm', 'Approved').json()['success']
    login(env, 'trainer')
    assert call(env, 'getMyDailyUpdates', 'trainer').json()[0]['rmStatus'] == 'Approved'


def test_leave_and_activity_approval_role_security(env):
    login(env, 'trainer')
    leave = call(env, 'submitLeaveRequest', {'employeeUsername': 'trainer', 'startDate': '2026-10-14',
        'endDate': '2026-10-16', 'comments': 'Personal'}).json()
    assert leave['success']
    l_id = call(env, 'getLeaveRequests', 'trainer').json()[0]['leaveID']
    assert call(env, 'reviewLeaveRequest', l_id, 'trainer', 'Approved', '').status_code == 403
    activity = call(env, 'submitDailyActivity', {'trainerUsername': 'trainer', 'date': '2026-10-14',
        'activityCode': 'TEST', 'hours': 3, 'topicCovered': 'Demo presentation'}).json()
    assert activity['success']
    own = call(env, 'getMyDailyActivities', 'trainer').json()
    assert len(own) == 1
    assert call(env, 'getMyDailyActivities', 'other').status_code == 403
    login(env, 'rm')
    assert call(env, 'reviewLeaveRequest', l_id, 'rm', 'Approved', '').status_code == 403
    # Admin can monitor a trainer's pending leave, but only the trainer's
    # stamped direct manager may approve it.
    login(env, 'admin')
    admin_view = call(env, 'getLeaveRequests', 'admin').json()
    assert any(r['leaveID'] == l_id and r['status'] == 'Pending'
               and r['reportingManagerUsername'] == 'lead' for r in admin_view)
    assert call(env, 'reviewLeaveRequest', l_id, 'admin', 'Approved', '').status_code == 403
    login(env, 'lead')
    assert call(env, 'reviewLeaveRequest', l_id, 'lead', 'Approved', 'OK').json()['success']
    approval = call(env, 'getDailyActivityApprovals', 'lead').json()
    assert len(approval) == 1
    assert call(env, 'reviewDailyActivity', approval[0]['entryID'], 'lead', 'Approved', '').json()['success']
    login(env, 'admin')
    assert next(r for r in call(env, 'getLeaveRequests', 'admin').json()
                if r['leaveID'] == l_id)['status'] == 'Approved'
    assert call(env, 'getTrainerActivityReport', '2026-10').json()[0]['totalHours'] == 3
    assert call(env, 'getDailyActivityAvailableMonths').json() == ['2026-10']


def test_kpi_stamped_approver_return_and_unlock(env):
    login(env, 'trainer')
    assert call(env, 'submitRating', 'trainer', 1, 6).json()['success'] is False
    assert call(env, 'submitRating', 'trainer', 1, 4).json()['success']
    assert call(env, 'submitRating', 'trainer', 1, 3).json()['success'] is False
    login(env, 'rm')
    assert call(env, 'decideOnRating', 'rm', 1, 'trainer', 'Approved', '').status_code == 403
    login(env, 'lead')
    dashboard = call(env, 'getKpiDashboardData', 'lead').json()
    assert any(x['status'] == 'Submitted' for x in dashboard['teamKpis'])
    assert call(env, 'decideOnRating', 'lead', 1, 'trainer', 'Returned', 'Please revise').json()['success']
    login(env, 'trainer')
    assert call(env, 'getKpiDashboardData', 'trainer').json()['myKpis'][0]['returnReason'] == 'Please revise'
    assert call(env, 'submitRating', 'trainer', 1, 3).json()['success']
    login(env, 'lead')
    assert call(env, 'decideOnRating', 'lead', 1, 'trainer', 'Approved', '').json()['success']
    assert call(env, 'unlockRating', 'lead', 1, 'trainer').json()['success']


def test_admin_changes_activity_and_multi_insert_ids(env):
    login(env, 'admin')
    assert call(env, 'createActivityMaster', {'code': 'TEST2', 'name': 'Workshop'}).json()['success']
    assert call(env, 'createActivityMaster', {'code': 'TEST3', 'name': 'Interview'}).json()['success']
    assert call(env, 'setActivityMasterActive', 'TEST2', False, 'admin').json()['success']
    assert call(env, 'getActivityMaster').json() == [ {'code': 'TEST', 'name': 'Demo'}, {'code': 'TEST3', 'name': 'Interview'}]
    assert call(env, 'saveKpiMaster', 'admin', {'category': 'Output', 'parameter': 'Task', 'target': '10'}).json()['success']
    assert len(call(env, 'getKpiMaster').json()) == 2
