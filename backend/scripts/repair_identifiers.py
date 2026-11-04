"""Idempotent, non-destructive identity repair for pre-fix PostgreSQL installs.
Runs after import. Do not use --replace or destroy database volumes.
"""
import json
from pathlib import Path
import sys
from sqlalchemy import select
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import User, SheetRow, setup_engine, session_factory
from app.identifiers import username

IDENTITY_FIELDS = ('TrainerUsername', 'EmployeeUsername', 'ReportingManagerUsername',
  'RMUsername', 'ReviewedBy', 'CreatedBy', 'StatusUpdatedBy', 'RecipientUserID',
  'RecordedBy', 'approverId', 'employeeId', 'Username', 'CreatedByUsername')


def repair(url=None):
    factory = session_factory(setup_engine(url))
    changed_users, changed_links = 0, 0
    with factory.begin() as db:
        people = list(db.scalars(select(User)))
        current = {u.username for u in people}
        for u in people:
            name = username(u.username)
            if u.username != name:
                if name in current:
                    raise ValueError('Username repair conflict detected; no changes committed')
                current.remove(u.username); current.add(name)
                u.username = name
                changed_users += 1
            boss = username(u.reporting_manager_username)
            if u.reporting_manager_username != boss:
                u.reporting_manager_username = boss
                changed_links += 1
        for r in db.scalars(select(SheetRow)):
            data = dict(r.data)
            updated = False
            for field in IDENTITY_FIELDS:
                if field in data and data[field] is not None:
                    name = username(data[field])
                    if name != str(data[field]):
                        data[field] = name
                        updated = True
            if 'recordKey' in data:
                key = str(data['recordKey'])
                if '_' in key:
                    start, end = key.split('_', 1)
                    new_key = start + '_' + username(end)
                    if key != new_key:
                        data['recordKey'] = new_key
                        updated = True
            if updated:
                r.data = data
                changed_links += 1
    return {'normalized_usernames': changed_users, 'updated_references': changed_links}


if __name__ == '__main__':
    print(json.dumps(repair()))
