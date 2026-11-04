"""Security, booking, manager/TL approval, and non-destructive data tests."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import create_app
from app.db import User, SheetRow, setup_engine, session_factory
from app.security import hash_password


@pytest.fixture
def env(tmp_path):
    url = f'sqlite+pysqlite:///{tmp_path / "booking.db"}'
    factory = session_factory(setup_engine(url))
    with factory.begin() as db:
        for username, role, parent in [
            ('admin', 'Admin', ''), ('rm', 'Reporting Manager', 'admin'),
            ('tl', 'Team Leader', 'rm'), ('trainer', 'Trainer', 'tl'),
            ('trainer2', 'Trainer', 'tl')]:
            db.add(User(user_id=username, username=username, full_name=username,
                        role=role, reporting_manager_username=parent, active=True,
                        password_hash=hash_password('secure-password-123')))
        db.add(SheetRow(sheet_name='ActivityMaster',source_row=2,data={
            'ActivityCode':'CODE','ActivityName':'Internal Work','Active':True}))
    with TestClient(create_app(url)) as client:
        yield client, factory


def rpc(c, name, *args):
    return c.post('/api/rpc/'+name, json={'args':list(args)})


def login(c, name):
    result=rpc(c,'login',name,'secure-password-123')
    assert result.status_code==200 and result.json()['success']


def project(c, name, kind='vendor', trainer='trainer', st='09:00', en='11:00', **kwargs):
    payload={'collegeName':name,'vendor':'Example','trainerUsername':trainer,
             'trainerName':trainer,'freelancerName':'Outside','category':'Aptitude',
             'startDate':'2026-10-13','endDate':'2026-10-15','startTime':st,
             'endTime':en,'status':'Running','days':10, **kwargs}
    method='createVendorProject' if kind=='vendor' else 'createFreelanceProject'
    return rpc(c,method,payload)


def college(c,name):
    result=rpc(c,'createCollege',{'collegeName':name,'status':'Running',
        'categories':[{'category':'Python','plannedDays':10}]})
    assert result.status_code==200 and result.json()['success']
    return result.json()['collegeCode']


def assign(c,code, trainer='trainer', st='09:00',en='11:00',**kwargs):
    return rpc(c,'assignTrainer',{'collegeCode':code,'trainerUsername':trainer,
          'category':'Python','fromDate':'2026-10-13','toDate':'2026-10-15',
          'startTime':st,'endTime':en,'batch':'A','assignmentStatus':'Running',**kwargs})


def test_trainer_direct_api_ownership_mutations_are_403_with_exact_message(env):
    c,_=env
    login(c,'trainer')
    for name,args in [
        ('assignTrainer',[{'trainerUsername':'trainer2'}]),
        ('removeTrainerAssignment',['nonexistent']),
        ('updateTrainerAssignmentStatus',['nonexistent','Completed']),
        ('reassignJob',[{'projectType':'vendor','projectId':'id','trainerUsername':'trainer2'}]),
        ('updateVendorProject',[{'projectID':'id','trainerUsername':'trainer2'}]),
        ('createVendorProject',[{'collegeName':'x','trainerUsername':'trainer2'}]),
        ('updateFreelanceProject',[{'projectID':'id','trainerUsername':'trainer2'}]),
        ('createFreelanceProject',[{'collegeName':'x','trainerUsername':'trainer2'}]),
        ('updateReportingManagerMapping',['trainer','trainer2'])]:
        result=rpc(c,name,*args)
        assert result.status_code==403, (name,result.status_code,result.text)
        assert result.json()['detail']=='Trainers are not permitted to reassign jobs'
    assert rpc(c,'checkTrainerSchedule',{'trainerUsername':'trainer','startDate':'2026-10-13',
         'endDate':'2026-10-14'}).status_code==403


def test_preflight_409_then_explicit_admin_override_preserves_original_rows(env):
    c,db_factory=env
    login(c,'admin')
    code=college(c,'ABC College')
    assert assign(c,code).json()['success']
    preview=rpc(c,'checkTrainerSchedule',{'trainerUsername':'trainer',
        'startDate':'2026-10-14','endDate':'2026-10-14','startTime':'10:00','endTime':'12:00'})
    assert preview.status_code==200 and preview.json()['is_occupied']
    assert preview.json()['conflicts'][0]['projectName']=='ABC College'
    blocked=project(c,'ramco', st='10:00', en='12:00')
    assert blocked.status_code==409 and blocked.json()['detail']['is_occupied']
    with db_factory.begin() as db:
        assert not list(db.scalars(select(SheetRow).where(SheetRow.sheet_name=='VendorProjects')))
    allowed=project(c,'ramco',st='10:00',en='12:00',acknowledgeConflict=True)
    assert allowed.status_code==200 and allowed.json()['success']
    with db_factory.begin() as db:
        assert len(list(db.scalars(select(SheetRow).where(SheetRow.sheet_name=='VendorProjects'))))==1
        assert len(list(db.scalars(select(SheetRow).where(SheetRow.sheet_name=='TrainerAssignments'))))==1
    with db_factory.begin() as db:
        assert any('Override' in x.data['AlertType'] for x in
                   db.scalars(select(SheetRow).where(SheetRow.sheet_name=='Alerts')))


def test_no_conflict_for_nonoverlapping_slots_touching_end_boundary(env):
    c,_=env
    login(c,'admin')
    a=project(c,'morning',st='09:00',en='11:00')
    assert a.json()['success']
    b=project(c,'afternoon',kind='freelance',st='11:00',en='12:00')
    assert b.status_code==200 and b.json()['success']
    check=rpc(c,'checkTrainerSchedule',{'trainerUsername':'trainer',
        'startDate':'2026-10-13','endDate':'2026-10-13','startTime':'12:00','endTime':'14:00'})
    assert check.json()['is_occupied'] is False


def test_manager_can_reassign_unoccupied_only_and_never_override(env):
    c,_=env
    login(c,'admin')
    created=project(c,'old allocation')
    assert created.json()['success']
    other=project(c,'trainer2 booked',trainer='trainer2',st='10:00',en='12:00')
    assert other.json()['success']
    login(c,'tl')
    payload={'projectType':'vendor','projectId':created.json()['projectID'],
             'trainerUsername':'trainer2'}
    blocked=rpc(c,'reassignJob',payload)
    assert blocked.status_code==409
    unauthorized=rpc(c,'reassignJob',{**payload,'acknowledgeConflict':True})
    assert unauthorized.status_code==403
    assert 'Only Admin' in unauthorized.json()['detail']
    successful=rpc(c,'reassignJob',{**payload, 'trainerUsername':'trainer'})
    assert successful.status_code==200 and successful.json()['success']
    login(c,'admin')
    permitted=rpc(c,'reassignJob',{**payload,'acknowledgeConflict':True})
    assert permitted.status_code==200 and permitted.json()['success']


def test_manager_can_assign_without_conflict_and_trainer_cannot(env):
    c,_=env
    login(c,'admin')
    code=college(c,'Manager College')
    login(c,'rm')
    assert assign(c,code).json()['success']
    login(c,'trainer')
    assert assign(c,code,'trainer2').status_code==403


def test_daily_tracker_immediate_team_leader_not_reporting_manager_and_comments(env):
    c,_=env
    login(c,'trainer')
    res=rpc(c,'submitDailyActivity',{'trainerUsername':'trainer',
        'activityCode':'CODE','date':'2026-10-13','topicCovered':'Work','hours':2})
    assert res.status_code==200 and res.json()['success']
    listing=rpc(c,'getMyDailyActivities','trainer').json()
    assert len(listing)==1 and listing[0]['status']=='Pending'
    assert listing[0]['approverUsername']=='tl'
    entry=listing[0]['entryID']
    login(c,'rm')
    assert not rpc(c,'getDailyActivityApprovals','rm').json()
    assert rpc(c,'reviewDailyActivity',entry,'rm','Approved','').status_code==403
    login(c,'tl')
    assert any(x['entryID']==entry for x in rpc(c,'getDailyActivityApprovals','tl').json())
    done=rpc(c,'reviewDailyActivity',entry,'tl','Approved','Verified hours')
    assert done.json()['success']
    login(c,'trainer')
    latest=rpc(c,'getMyDailyActivities','trainer').json()[0]
    assert latest['status']=='Approved' and latest['reviewComments']=='Verified hours'
    assert any('Daily Tracker' in x['message'] for x in rpc(c,'getAlerts','trainer').json())


@pytest.mark.parametrize('start,end,a,b',[
    ('2026-10-15','2026-10-14','',''),
    ('2026-10-13','2026-10-14','12:00','10:00'),
    ('2026-10-13','2026-10-14','10:00',''),
])
def test_invalid_calendar_range_or_slot_rejected(env,start,end,a,b):
    c,_=env
    login(c,'admin')
    r=rpc(c,'checkTrainerSchedule',{'trainerUsername':'trainer','startDate':start,
        'endDate':end,'startTime':a,'endTime':b})
    assert r.status_code==400


def test_approved_leave_is_a_booking_conflict_and_requires_admin_ack(env):
    c,factory=env
    with factory.begin() as db:
        db.add(SheetRow(sheet_name='LeaveRequests',source_row=2,data={
            'LeaveID':'L1','EmployeeUsername':'trainer', 'Status':'Approved',
            'StartDate':'2026-10-14','EndDate':'2026-10-14'}))
    login(c,'admin')
    preview=rpc(c,'checkTrainerSchedule',{'trainerUsername':'trainer',
            'startDate':'2026-10-14','endDate':'2026-10-14','startTime':'14:00','endTime':'15:00'})
    assert preview.status_code==200
    assert preview.json()['conflicts'][0]['type']=='leave'
    blocked=project(c,'Approved leave overlap', st='14:00',en='15:00')
    assert blocked.status_code==409
    override=project(c,'Approved leave overlap',st='14:00',en='15:00',acknowledgeConflict=True)
    assert override.status_code==200 and override.json()['success']


def test_active_portal_assignment_requires_dates_and_history_is_not_rewritten(env):
    c,factory=env
    login(c,'admin')
    response=rpc(c,'createVendorProject',{'collegeName':'Undated',
                         'trainerUsername':'trainer','status':'Running'})
    assert response.status_code==400
    with factory.begin() as db:
        assert not list(db.scalars(select(SheetRow).where(SheetRow.sheet_name=='VendorProjects')))
    # Historical rows remain in their existing form; no mandatory migration/overwrite.
    with factory.begin() as db:
        db.add(SheetRow(sheet_name='VendorProjects',source_row=2,data={
            'ProjectID':'historical','TrainerUsername':'trainer',
            'CollegeName':'Old event','Status':'Completed'}))
    assert rpc(c,'getVendorProjects').status_code==200


def test_create_college_initial_trainer_booking_requires_override(env):
    c,factory=env
    login(c,'admin')
    assert project(c,'Existing slot').json()['success']
    payload={'collegeName':'Second College','status':'Running',
       'categories':[{'category':'Python','plannedDays':3}],
       'trainers':[{'trainerUsername':'trainer','category':'Python',
                    'fromDate':'2026-10-13','toDate':'2026-10-15',
                    'assignmentStatus':'Running'}]}
    rejected=rpc(c,'createCollege',payload)
    assert rejected.status_code==409
    with factory.begin() as db:
        assert not list(db.scalars(select(SheetRow).where(SheetRow.sheet_name=='Colleges')))
    payload['trainers'][0]['acknowledgeConflict']=True
    saved=rpc(c,'createCollege',payload)
    assert saved.status_code==200 and saved.json()['success']
    with factory.begin() as db:
        assert any(r.data['AlertType']=='Schedule Override' for r in db.scalars(
              select(SheetRow).where(SheetRow.sheet_name=='Alerts')))
