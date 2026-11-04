# LTMP — Login and account troubleshooting

## Why previous Team Leader / Reporting Manager logins failed

The original workbook contains 96 employee IDs stored as Excel numeric cells.
The original importer converted numeric IDs like `12999.0` to the literal
username `12999.0`. People naturally type `12999`, so login incorrectly
returned "Invalid username or password". This was an import format defect,
not a permission to limit login to Admin/Trainer.

The corrected import normalizes only integral numeric IDs ending in `.0`
while preserving textual IDs and leading zeros. The login endpoint also
accepts the unnormalized numeric alias on **previous installations**. In
addition, the API Docker startup runs an idempotent reference-repair script
without replacing existing records.

## Verified workbook state (2026-10-13 snapshot)

| Role | Active | Inactive |
|---|---:|---:|
| Admin | 6 | 0 |
| Reporting Manager | 5 | 0 |
| Team Leader | 10 | 0 |
| Trainer | 38 | 60 |
| **Total** | **59** | **60** |

All 119 supplied workbook user rows were imported into a temporary database,
and their **actual workbook passwords** were verified in memory: all 59 active
accounts accepted, and all 60 inactive accounts were denied, as intended.
Neither test logs nor SQL stores plaintext passwords. Passwords are immediately
hashed using Argon2id in the new database.

## Usage and diagnostics

1. Use the **Username / Employee ID** field (not Full Name). For numeric IDs,
   enter the number without a trailing `.0`.
2. Use the password for **that account** in the original workbook, or one
   set subsequently in this application. Credentials are not shared across roles.
3. An **inactive** account is intentionally blocked. Admin can activate it
   from User Management after verifying authorization.
4. After importing, authenticate as Admin, then open the aggregate diagnostics
   endpoint `GET /api/admin/account-diagnostics` (requires admin session) to
   see active/inactive/unmapped counts without exposing account passwords.
5. Missing reporting-manager mappings do not block login; they **do** block
   actions requiring a direct approver (e.g. leave / tracker / KPI). There were
   16 active non-admin users without a reporting-manager mapping in the source
   workbook. An Admin must map the correct direct manager for those employees.
6. When upgrading an existing database, use the same Docker project and named
   volume. Automatic identifier repair runs after the no-overwrite importer.
   You can also inspect logs: `docker compose logs --tail=100 api`.

### Existing PostgreSQL database upgrade

Make a verified backup first. **Do not delete or recreate pgdata volume.**

```bash
docker compose exec -T db pg_dump -U ltmp ltmp > ltmp-backup.sql
docker compose up -d --build
```

Startup runs `python scripts/repair_identifiers.py`. The repair is designed to
be idempotent and transactional, with collision detection before commit.
Always inspect logs after first upgraded startup. If a collision is detected,
stop and investigate rather than overwriting accounts.

**Do not post screenshots of credentials or upload the private workbook to a
public code repository. Rotate the legacy credentials before production use.**
