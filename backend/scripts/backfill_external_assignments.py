"""Idempotent startup repair: notify trainers of existing external assignments.

This does not alter VendorProjects/FreelanceProjects rows or any old alerts.
Only uniquely resolved internal Trainer accounts receive notices.
"""
import sys
from pathlib import Path
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db import User, session_factory, setup_engine
from app.queries import rows, s
from app.unified_projects import external_projects
from app.workflows import alert


def backfill(url=None):
    Factory = session_factory(setup_engine(url))
    count = 0
    with Factory.begin() as db:
        notified = {(s(x.get('RelatedAssignmentID')), s(x.get('RecipientUserID')).lower())
                    for x in rows(db, 'Alerts')
                    if s(x.get('AlertType')) in ('External Project Assigned', 'External Project Updated', 'External Assignment Replaced')}
        active = {u.username for u in db.scalars(select(User).where(User.role == 'Trainer', User.active.is_(True)))}
        for project in external_projects(db, include_inactive=False):
            owner = project['trainerUsername']
            key = (project['projectKey'], owner)
            if not owner or owner not in active or key in notified:
                continue
            alert(db, 'External Project Assigned', owner,
                  f'Existing {project["projectType"].title()} assignment: {project["projectName"]}. Open My Projects.',
                  related_assignment=project['projectKey'])
            notified.add(key)
            count += 1
    return count


if __name__ == '__main__':
    print(f'Existing external trainer notifications backfilled: {backfill()}')
