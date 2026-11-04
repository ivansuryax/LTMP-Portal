"""One-time migration of user's 19-sheet workbook. Requires --file path.

Does NOT embed workbook content, passwords, or private records in the ZIP.
By default refuses to overwrite existing database data; --replace explicitly
clears existing user accounts and imported source rows (destructive).
"""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from openpyxl import load_workbook
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db import ImportSheet, SessionToken, SheetRow, User, session_factory, setup_engine
from app.security import hash_password
from app.identifiers import username as normalize_username


def serialize(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def text(v):
    return '' if v is None else str(v).strip()


def truthy(v):
    return v is True or text(v).lower() in ('true', '1', 'yes')


def import_workbook(filename: str, url: Optional[str] = None, replace: bool = False, if_empty: bool = False):
    wb = load_workbook(filename, data_only=True, read_only=True)
    engine = setup_engine(url)
    Factory = session_factory(engine)
    summary = {}
    with Factory.begin() as db:
        if db.scalar(select(func.count()).select_from(User)) or db.scalar(select(func.count()).select_from(SheetRow)):
            if not replace:
                if if_empty:
                    wb.close()
                    return {'status': 'already_initialized'}
                raise ValueError('Database already contains data. Refusing overwrite; pass --replace ONLY after backup.')
            db.query(SessionToken).delete()
            db.query(User).delete()
            db.query(SheetRow).delete()
            db.query(ImportSheet).delete()
        for sh in wb:
            iterator = sh.iter_rows(values_only=True)
            head = next(iterator, None)
            if not head:
                continue
            columns = [text(v) for v in head]
            if any(not v for v in columns):
                raise ValueError(f'Blank column header found in {sh.title}')
            db.add(ImportSheet(name=sh.title, columns=columns))
            count = 0
            for row_number, values in enumerate(iterator, start=2):
                if not any(value is not None and value != '' for value in values):
                    continue
                record = {col: serialize(values[i]) if i < len(values) else None for i, col in enumerate(columns)}
                # Normalize employee references consistently across sheets.
                for field in ('Username', 'TrainerUsername', 'EmployeeUsername', 'ReportingManagerUsername',
                              'RMUsername', 'ReviewedBy', 'CreatedBy', 'StatusUpdatedBy',
                              'RecipientUserID', 'RecordedBy', 'approverId', 'employeeId'):
                    if field in record and record[field] is not None:
                        record[field] = normalize_username(record[field])
                if sh.title == 'Users':
                    username = normalize_username(record.get('Username'))
                    if not username:
                        continue
                    if not text(record.get('Password')):
                        raise ValueError(f'Missing password for user on source row {row_number}; fix source before import')
                    db.add(User(
                        user_id=text(record.get('UserID')), username=username.lower(),
                        password_hash=hash_password(record['Password']),
                        full_name=text(record.get('FullName')), role=text(record.get('Role')),
                        designation=text(record.get('Designation')), email=text(record.get('Email')),
                        phone=text(record.get('Phone')), active=truthy(record.get('Active')),
                        reporting_manager_username=normalize_username(record.get('ReportingManagerUsername'))
                    ))
                else:
                    if 'Password' in record:
                        raise ValueError(f'Sensitive Password column unexpectedly present in {sh.title}')
                    db.add(SheetRow(sheet_name=sh.title, source_row=row_number, data=record))
                count += 1
            summary[sh.title] = count
    wb.close()
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', required=True, help='Path to source LTMP.xlsx')
    parser.add_argument('--replace', action='store_true', help='DESTRUCTIVE: remove existing database data')
    parser.add_argument('--if-empty', action='store_true', help='Import on first startup only; subsequent runs leave records intact')
    args = parser.parse_args()
    result = import_workbook(args.file, replace=args.replace, if_empty=args.if_empty)
    print(json.dumps(result, indent=2))
