"""Regression coverage for Vendor/Freelancer + LeSuccess unified trainer flow."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.db import User, SheetRow, ExternalTrainingUpdate, setup_engine, session_factory
from app.security import hash_password
from scripts.backfill_external_assignments import backfill


@pytest.fixture()
def env(tmp_path):
    url = f'sqlite+pysqlite:///{tmp_path / "unified.db"}'
    factory = session_factory(setup_engine(url))
    with factory.begin() as db:
        for username, fullname, role, manager in [
            ('admin', 'Admin Account', 'Admin', ''),
            ('rm', 'Reporting Manager', 'Reporting Manager', 'admin'),
            ('other_rm', 'Another RM', 'Reporting Manager', 'admin'),
            ('tl', 'Team Leader', 'Team Leader', 'rm'),
            ('tk01103', 'Suguna', 'Trainer', 'tl'),
            ('someone', 'Someone Else', 'Trainer', 'tl')]:
            db.add(User(user_id=username, username=username, full_name=fullname,
                role=role, reporting_manager_username=manager, active=True,
                password_hash=hash_password('test-password-123')))
    with TestClient(create_app(url)) as client:
        yield client, url


def rpc(c, name, *args):
    return c.post('/api/rpc/' + name, json={'args': list(args)})


def login(c, username):
    response = rpc(c, 'login', username, 'test-password-123')
    assert response.status_code == 200 and response.json()['success']


def create(c, kind, name, trainer='tk01103', status='Running'):
    login(c, 'admin')
    call = 'createVendorProject' if kind == 'vendor' else 'createFreelanceProject'
    payload = {'vendor': 'TestVendor', 'collegeName': name, 'trainerUsername': trainer,
        'trainerName': 'Suguna', 'freelancerName': 'Outside Freelancer',
        'category': 'Aptitude', 'startDate': '2026-10-01', 'endDate': '2026-10-31',
        'status': status, 'days': 15}
    answer = rpc(c, call, payload).json()
    assert answer['success'], answer
    return answer['projectID']


@pytest.mark.parametrize('kind', ['vendor', 'freelance'])
def test_all_external_projects_notify_submit_review_and_progress(env, kind):
    c, url = env
    project_id = create(c, kind, 'ramco')
    login(c, 'tk01103')
    assigned = rpc(c, 'getMyProjects', 'tk01103').json()
    assert len(assigned) == 1
    assert assigned[0]['projectType'] == kind and assigned[0]['projectId'] == project_id
    assert assigned[0]['canSubmit'] is True
    notes = rpc(c, 'getAlerts', 'tk01103').json()
    assert any('ramco' in n['message'] and n.get('notificationID') for n in notes)
    response = rpc(c, 'submitDailyUpdate', {'projectType':kind,'projectId':project_id,
        'trainerUsername':'tk01103','category':'Aptitude','date':'2026-10-13',
        'topicCovered':'Percentages','attendance':'85%'})
    assert response.status_code == 200 and response.json()['success']
    update_id = response.json()['updateID']
    assert not rpc(c, 'submitDailyUpdate', {'projectType':kind,'projectId':project_id,
        'trainerUsername':'tk01103','category':'Aptitude','date':'2026-10-13',
        'topicCovered':'Percentages','attendance':'85%'}).json()['success']
    assert any(x['projectType'] == kind and x['rmStatus'] == 'Pending'
               for x in rpc(c, 'getMyDailyUpdates','tk01103').json())
    login(c, 'other_rm')
    assert not rpc(c, 'getPendingApprovals', None).json()
    assert rpc(c, 'approveSyllabus', update_id, 'other_rm', 'Approved').status_code == 403
    login(c, 'rm')
    pending = rpc(c, 'getPendingApprovals', None).json()
    assert len(pending) == 1 and pending[0]['SyllabusID'] == update_id
    assert pending[0]['ProjectType'].lower() == kind
    assert rpc(c, 'approveSyllabus', update_id, 'rm', 'Approved').json()['success']
    assert not rpc(c, 'approveSyllabus', update_id, 'rm', 'Approved').json()['success']
    login(c, 'admin')
    progress = next(x for x in rpc(c, 'getProjectProgress').json()
                    if x['projectType'] == kind and x['projectId'] == project_id)
    assert progress['completedDays'] == 1
    assert progress['submittedUpdates'] == 1 and progress['pendingUpdates'] == 0
    listing = rpc(c, 'getVendorProjects' if kind == 'vendor' else 'getFreelanceProjects').json()[0]
    assert listing['completedDays'] == 1
    # Rebuild/backup semantics: original project row remains untouched by training updates.
    factory = session_factory(setup_engine(url))
    with factory.begin() as db:
        row = db.scalar(select(ExternalTrainingUpdate))
        assert row.project_id == project_id and row.project_type == kind
        assert len(list(db.scalars(select(SheetRow).where(SheetRow.sheet_name == ('VendorProjects' if kind == 'vendor' else 'FreelanceProjects'))))) == 1
    assert backfill(url) == 0


def test_existing_vendor_name_resolves_uniquely_and_backfills(env):
    c, url = env
    factory = session_factory(setup_engine(url))
    with factory.begin() as db:
        db.add(SheetRow(sheet_name='VendorProjects', source_row=2, data={
            'ProjectID':'legacy-ramco', 'CollegeName':'ramco',
            'TrainerName':'Suguna','TrainerUsername':'', 'Category':'Aptitude',
            'Status':'Running','Days':12,
            'StartDate':'2026-10-01','EndDate':'2026-10-31'}))
    assert backfill(url) == 1
    assert backfill(url) == 0
    login(c,'tk01103')
    assert rpc(c,'getMyProjects','tk01103').json()[0]['projectId'] == 'legacy-ramco'
    assert any('Existing Vendor assignment' in n['message'] for n in rpc(c,'getAlerts','tk01103').json())


def test_external_security_validations_and_preserve_prior_work(env):
    c,url=env
    project_id=create(c,'vendor','ramco')
    login(c,'someone')
    assert rpc(c,'getMyProjects','tk01103').status_code == 403
    assert rpc(c,'submitDailyUpdate', {'projectType':'vendor','projectId':project_id,
        'trainerUsername':'someone','date':'2026-10-13','category':'Aptitude','topicCovered':'Wrong user'}).status_code == 403
    login(c,'tk01103')
    for date,category,attendance in [('2026-09-01','Aptitude','75'),('2026-10-13','Python','75'),('2026-10-13','Aptitude','110')]:
        reply = rpc(c,'submitDailyUpdate', {'projectType':'vendor','projectId':project_id,
            'trainerUsername':'tk01103','date':date,'category':category,'attendance':attendance,'topicCovered':'Test'})
        assert reply.json()['success'] is False
    login(c,'admin')
    assert rpc(c,'updateVendorProject',{'projectID':project_id,'status':'On Hold'}).json()['success']
    login(c,'tk01103')
    assert rpc(c,'getMyProjects','tk01103').json()[0]['canSubmit'] is False
    assert not rpc(c,'submitDailyUpdate',{'projectType':'vendor','projectId':project_id,
        'trainerUsername':'tk01103','date':'2026-10-13','category':'Aptitude','topicCovered':'Test'}).json()['success']


def test_lesuccess_keeps_daily_update_and_in_unified_listing(env):
    c,_=env
    login(c,'admin')
    col = rpc(c,'createCollege', {'collegeName':'LeSuccess Training','status':'Running',
        'categories':[{'category':'Java','plannedDays':10}]}).json()
    assert col['success']
    code=col['collegeCode']
    assert rpc(c,'assignTrainer',{'collegeCode':code,'trainerUsername':'tk01103',
        'category':'Java','fromDate':'2026-10-01','toDate':'2026-10-31',
        'assignmentStatus':'Running'}).json()['success']
    login(c,'tk01103')
    mine=rpc(c,'getMyProjects','tk01103').json()
    assert len(mine)==1 and mine[0]['projectType']=='lesuccess'
    answer=rpc(c,'submitDailyUpdate',{'collegeCode':code,'trainerUsername':'tk01103',
        'category':'Java','date':'2026-10-13','topicCovered':'Java basics','attendance':'75%'})
    assert answer.json()['success']
    login(c,'rm')
    pending=rpc(c,'getPendingApprovals',None).json()
    assert len(pending)==1 and pending[0]['ProjectType']=='LeSuccess'
    assert rpc(c,'approveSyllabus',pending[0]['SyllabusID'],'rm','Approved').json()['success']
    login(c,'admin')
    assert any(p['projectType']=='lesuccess' and p['completedDays']==1 for p in rpc(c,'getProjectProgress').json())


def test_legacy_username_field_full_name_uses_unique_employee_identity(env):
    c, url = env
    factory = session_factory(setup_engine(url))
    with factory.begin() as db:
        db.add(SheetRow(sheet_name='VendorProjects', source_row=2, data={
            'ProjectID':'legacy-name-in-id', 'CollegeName':'ramco',
            'TrainerUsername':'Suguna', 'TrainerName':'Suguna', 'Category':'Aptitude',
            'Status':'Running', 'Days':15}))
    assert backfill(url) == 1
    login(c, 'tk01103')
    assert any(x['projectId'] == 'legacy-name-in-id' for x in rpc(c, 'getMyProjects', 'tk01103').json())
