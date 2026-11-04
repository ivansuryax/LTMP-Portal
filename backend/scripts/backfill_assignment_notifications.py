"""One-time, repeat-safe backfill for assignments created before in-app alerts existed.

Only current, valid LeSuccess college assignments are included. This script
never edits assignment rows or notification history, and will not recreate an
alert that was previously marked read. Run during startup after import/repair.
"""
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db import SheetRow, User, session_factory, setup_engine
from app.identifiers import username as normalize_username
from app.queries import rows, active_assignment, s
from app.workflows import alert


def backfill(url=None):
    Factory = session_factory(setup_engine(url))
    count = 0
    with Factory.begin() as db:
        users = {u.username for u in db.scalars(select(User)).all() if u.active and u.role == 'Trainer'}
        cols = {s(c.get('CollegeCode')).strip(): s(c.get('CollegeName')).strip() for c in rows(db, 'Colleges')}
        already = {s(x.get('RelatedAssignmentID')) for x in rows(db, 'Alerts')
                   if s(x.get('AlertType')) == 'Trainer Assigned'}
        for item in rows(db, 'TrainerAssignments'):
            assignment_id = s(item.get('AssignmentID')).strip()
            recipient = normalize_username(item.get('TrainerUsername'))
            code = s(item.get('CollegeCode')).strip()
            if (not assignment_id or assignment_id in already or
                recipient not in users or code not in cols or not active_assignment(item)):
                continue
            category = s(item.get('Category')).strip() or 'Training'
            alert(db, 'Trainer Assigned', recipient,
                  f'Current assignment: {cols[code]} ({category}). Open My Colleges for details.',
                  related_assignment=assignment_id)
            already.add(assignment_id)
            count += 1
    return count


if __name__ == '__main__':
    print(f'Assignment notifications backfilled: {backfill()}')
