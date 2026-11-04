"""Daily Update assignment visibility and in-app alert regression tests."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.db import SheetRow, User, setup_engine, session_factory
from app.security import hash_password
from scripts.backfill_assignment_notifications import backfill


@pytest.fixture()
def env(tmp_path):
    url = f'sqlite+pysqlite:///{tmp_path / "assignments.db"}'
    factory = session_factory(setup_engine(url))
    with factory.begin() as db:
        for name, role, mgr in [('admin', 'Admin', ''), ('12345', 'Trainer', 'admin'),
                                ('other', 'Trainer', 'admin')]:
            db.add(User(user_id=name, username=name, full_name=name,
                role=role, reporting_manager_username=mgr,
                password_hash=hash_password('test-password-123'), active=True))
    with TestClient(create_app(url)) as client:
        yield client, url


def rpc(client, name, *args):
    return client.post('/api/rpc/' + name, json={'args': list(args)})


def login(c, who):
    r = rpc(c, 'login', who, 'test-password-123')
    assert r.status_code == 200 and r.json()['success']


def make_college(c, trainers=None):
    login(c, 'admin')
    return rpc(c, 'createCollege', {
        'collegeName': 'Sample College', 'status': 'Running',
        'categories': [{'category': 'Java', 'plannedDays': 10}],
        'trainers': trainers or []
    }).json()


def test_trainer_assignment_creates_in_app_alert_and_shows_daily_update_form_data(env):
    c, url = env
    college = make_college(c)
    assert college['success']
    code = college['collegeCode']
    assigned = rpc(c, 'assignTrainer', {'collegeCode': code, 'trainerUsername': '12345',
        'category': 'Java', 'fromDate': '2026-10-10', 'toDate': '2026-10-30',
        'assignmentStatus': 'Running'}).json()
    assert assigned['success']
    login(c, '12345')
    mine = rpc(c, 'getMyColleges', '12345').json()
    assert len(mine) == 1 and mine[0]['myCategories'] == ['Java']
    notes = rpc(c, 'getAlerts', '12345').json()
    message = next((x for x in notes if 'Assigned to Sample College' in x['message']), None)
    assert message and message['notificationID']
    assert rpc(c, 'getAlertCount', '12345').json() >= 1
    assert rpc(c, 'markAlertRead', message['notificationID']).json()['success']
    assert not any(x.get('notificationID') == message['notificationID']
                   for x in rpc(c, 'getAlerts', '12345').json())
    assert backfill(url) == 0  # Read notifications must never be recreated.


def test_only_recipient_can_read_own_assignment_notice(env):
    c, _ = env
    code = make_college(c)['collegeCode']
    assert rpc(c, 'assignTrainer', {'collegeCode': code, 'trainerUsername': '12345',
       'category':'Java', 'fromDate':'2026-10-01','toDate':'2026-10-31'}).json()['success']
    login(c, '12345')
    nid = next(x['notificationID'] for x in rpc(c, 'getAlerts', '12345').json()
               if x.get('notificationID'))
    login(c, 'other')
    assert rpc(c, 'markAlertRead', nid).status_code == 403
    assert rpc(c, 'getMyColleges', '12345').status_code == 403
    assert not any(x.get('notificationID') == nid for x in rpc(c, 'getAlerts', 'other').json())
    assert rpc(c, 'getMyAssignmentStatus', 'other').json()['totalAssignments'] == 0


def test_legacy_numeric_identifier_is_normalized_and_diagnostics_help(env):
    c, url = env
    code = make_college(c)['collegeCode']
    factory = session_factory(setup_engine(url))
    with factory.begin() as db:
        db.add(SheetRow(sheet_name='TrainerAssignments',source_row=2,data={
            'AssignmentID':'old-a', 'TrainerUsername':'12345.0',
            'CollegeCode':code,'Category':'Java', 'AssignmentStatus':'Running',
            'CurrentAssignment':True}))
    login(c, '12345')
    result=rpc(c, 'getMyColleges', '12345').json()
    assert len(result)==1 and result[0]['myCategories']==['Java']
    # The same normalized ID must also authorize opening the college profile.
    assert rpc(c, 'getCollegeProfile', code).status_code == 200
    assert rpc(c, 'getMyAssignmentStatus', '12345').json()['visibleColleges']==1
    login(c,'admin')
    assert rpc(c, 'getTrainerAssignmentDiagnostics', '12345').json()['totalAssignments']==1
    assert backfill(url)==1
    assert backfill(url)==0


def test_initial_college_assignments_alert_and_inactive_state_explains_empty_form(env):
    c, _=env
    trainer={'trainerUsername':'12345', 'category':'Java', 'fromDate':'2026-10-01',
             'toDate':'2026-10-31', 'assignmentStatus':'Upcoming'}
    created = make_college(c,[trainer])
    assert created['success']
    login(c,'12345')
    assert len(rpc(c,'getMyColleges','12345').json())==1
    notes=rpc(c,'getAlerts','12345').json()
    assert any(x.get('notificationID') for x in notes)
    login(c,'admin')
    assignment=rpc(c,'getCollegeProfile',created['collegeCode']).json()['trainers'][0]
    assert rpc(c,'updateTrainerAssignmentStatus',assignment['assignmentID'],'Completed','admin','').json()['success']
    login(c,'12345')
    assert rpc(c,'getMyColleges','12345').json()==[]
    details=rpc(c,'getMyAssignmentStatus','12345').json()
    assert 'none are current' in details['message']
    assert any('changed from Upcoming to Completed' in x['message'] for x in rpc(c,'getAlerts','12345').json())


def test_invalid_assignment_category_is_rejected_with_helpful_message(env):
    c,_=env
    code=make_college(c)['collegeCode']
    result=rpc(c,'assignTrainer',{'collegeCode':code,'trainerUsername':'12345',
             'category':'Not Configured','fromDate':'2026-10-01','toDate':'2026-10-31'}).json()
    assert not result['success']
    login(c,'12345')
    assert rpc(c,'getMyColleges','12345').json()==[]


def test_replacement_marks_previous_assignment_inactive_and_notifies(env):
    c,_=env
    code=make_college(c)['collegeCode']
    for trainer in ('12345','other'):
        result=rpc(c,'assignTrainer',{'collegeCode':code,'trainerUsername':trainer,
              'category':'Java','fromDate':'2026-10-01','toDate':'2026-10-31'}).json()
        assert result['success']
    login(c,'12345')
    assert rpc(c,'getMyColleges','12345').json()==[]
    assert any('was replaced' in x['message'] for x in rpc(c,'getAlerts','12345').json())
    login(c,'other')
    assert len(rpc(c,'getMyColleges','other').json())==1
