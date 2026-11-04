"""Actual Chromium DOM + JS -> FastAPI RPC -> SQLite: 3 project types.

Run: python tests/browser_unified_training_e2e.py
Does not test user local Docker/Nginx or production database.
"""
import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from playwright.async_api import async_playwright
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import User, setup_engine, session_factory
from app.main import create_app
from app.security import hash_password

ROOT = Path(__file__).resolve().parents[2]
SHELL = (ROOT / 'frontend/src/original-shell.html').read_text()
CSS = (ROOT / 'frontend/src/original.css').read_text()
JS = (ROOT / 'frontend/public/legacy.js').read_text()


async def run():
    with TemporaryDirectory() as tmp:
        url = f'sqlite+pysqlite:///{tmp}/unified_browser.db'
        factory = session_factory(setup_engine(url))
        with factory.begin() as db:
            for username, role, manager in [('admin', 'Admin', ''), ('rm', 'Reporting Manager','admin'),
                                            ('tl', 'Team Leader','rm'), ('trainer1', 'Trainer','tl')]:
                db.add(User(user_id=username, username=username, full_name=username.title(),
                    role=role, reporting_manager_username=manager, active=True,
                    password_hash=hash_password('test-password-123')))
        with TestClient(create_app(url)) as api:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                                   args=['--no-sandbox','--disable-dev-shm-usage'])
                try:
                    page = await browser.new_page(viewport={'width':1480,'height':1000})
                    page.set_default_timeout(10000)
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))

                    async def bridge(name, args):
                        response = api.post('/api/rpc/' + name, json={'args': args})
                        if response.status_code >= 400:
                            raise RuntimeError(str(response.json().get('detail', response.status_code)))
                        return response.json()

                    await page.expose_function('ltmpBridge', bridge)
                    await page.set_content('<html><head><style>'+ CSS +'</style></head><body>'+ SHELL + '</body></html>', wait_until='domcontentloaded')
                    await page.evaluate('window.ltmpApi={call:(name,...args)=>window.ltmpBridge(name,args)}')
                    await page.add_script_tag(content=JS)

                    async def login(who):
                        await page.fill('#loginUsername', who)
                        await page.fill('#loginPassword', 'test-password-123')
                        await page.click('button:has-text("Sign In")')
                        await page.wait_for_selector('#appShell.active')

                    async def logout():
                        await page.click('button:has-text("Logout")')
                        await page.wait_for_selector('#loginScreen', state='visible')
                        await page.wait_for_timeout(300)

                    await login('admin')
                    # Project creation through real Admin form (Vendor, then Freelancer)
                    await page.evaluate('openAddVendorProject()')
                    await page.wait_for_selector('#vpTrainerSelect option[value="trainer1"]', state="attached")
                    await page.fill('#vpVendor','Demo Vendor')
                    await page.fill('#vpCollege','ramco')
                    await page.select_option('#vpTrainerSelect','trainer1')
                    await page.fill('#vpDays','15')
                    await page.fill('#vpStartDate','2026-10-01')
                    await page.fill('#vpEndDate','2026-10-31')
                    await page.fill('#vpCategory','Aptitude')
                    await page.click('#modalFooter button:has-text("Add")')
                    await page.wait_for_selector('#modalOverlay:not(.active)',state='attached')

                    await page.evaluate('openAddFreelanceProject()')
                    await page.wait_for_selector('#fpTrainerSelect option[value="trainer1"]', state="attached")
                    await page.fill('#fpVendor','Demo Freelance')
                    await page.fill('#fpCollege','Freelancer Training')
                    await page.select_option('#fpTrainerSelect','trainer1')
                    await page.fill('#fpFreelancer','External Trainer Display')
                    await page.fill('#fpDays','8')
                    await page.fill('#fpStartDate','2026-10-01')
                    await page.fill('#fpEndDate','2026-10-31')
                    await page.fill('#fpCategory','Communication')
                    await page.click('#modalFooter button:has-text("Add")')
                    # Intentional overlapping assignment now requires explicit
                    # Admin acknowledgement before the second record is saved.
                    await page.wait_for_selector('#ltmpBookingConflict:has-text("Trainer is already occupied")')
                    await page.click('#modalFooter button:has-text("Override & Proceed")')
                    await page.wait_for_selector('#modalOverlay:not(.active)',state='attached')

                    await logout()
                    await login('trainer1')
                    await page.click('.nav-pill[data-page="myprojects"]')
                    await page.wait_for_selector('#myProjectList:has-text("ramco")')
                    assert await page.locator('#myProjectList:has-text("Freelancer Training")').count() == 1
                    await page.click('.nav-pill[data-page="alerts"]')
                    await page.wait_for_selector('.alert-row:has-text("ramco")')
                    await page.click('.alert-row:has-text("ramco")')
                    await page.wait_for_selector('#myProjectList:has-text("ramco")')
                    await page.click('.nav-pill[data-page="dailyupdate"]')
                    await page.wait_for_selector('#duCollege')
                    options = await page.locator('#duCollege option').all_text_contents()
                    assert any('Vendor' in o and 'ramco' in o for o in options), options
                    assert any('Freelancer' in o and 'Freelancer Training' in o for o in options), options
                    for kind, topic, category in [('vendor','Training Percentages','Aptitude'),
                                                  ('freelance','Communication Skills','Communication')]:
                        opts = await page.locator('#duCollege option').evaluate_all(
                            '(xs) => xs.map(x => ({label:x.textContent,value:x.value}))')
                        selection = next(x['value'] for x in opts if x['value'].startswith(kind+':'))
                        await page.select_option('#duCollege', selection)
                        assert await page.locator('#duCategory').input_value() == category
                        await page.fill('#duDate','2026-10-13')
                        await page.fill('#duTopic',topic)
                        await page.fill('#duAttendance','87')
                        await page.click('button:has-text("Submit Update")')
                        await page.wait_for_selector(f'#myDailyUpdatesArea tbody tr:has-text("{topic}")')
                    print('PASS Chromium Admin -> 2 external projects -> Trainer My Projects/Alerts/Daily Update',flush=True)
                    await logout()
                    await login('rm')
                    await page.click('.nav-pill[data-page="dashboard"]')
                    await page.click('[data-dtab="vendor"]')
                    await page.wait_for_selector('#externalProjectCardsArea .external-project-card')
                    await page.locator('#externalProjectCardsArea .external-project-card').first.click()
                    await page.wait_for_selector('#reassignTrainer option[value="trainer1"]',state='attached')
                    await page.click('#modalFooter button:has-text("Cancel")')
                    print('PASS Chromium Manager can open dedicated reassignment modal',flush=True)
                    await page.click('.nav-pill[data-page="approvals"]')
                    await page.wait_for_selector('#approvalsArea tbody tr:has-text("Training Percentages")')
                    await page.locator('#approvalsArea tbody tr:has-text("Training Percentages") button:has-text("Approve")').click()
                    await page.wait_for_selector('#approvalsArea tbody tr:has-text("Communication Skills")')
                    await page.locator('#approvalsArea tbody tr:has-text("Communication Skills") button:has-text("Approve")').click()
                    print('PASS Chromium RM approval both project types',flush=True)
                    await logout()
                    await login('admin')
                    await page.click('.nav-pill[data-page="dashboard"]')
                    await page.wait_for_selector('[data-dtab="vendor"]')
                    await page.click('[data-dtab="vendor"]')
                    await page.wait_for_selector('#externalProjectCardsArea:has-text("Approved training days")')
                    assert '1 / 15' in await page.locator('#externalProjectCardsArea').inner_text()
                    await page.click('[data-dtab="freelance"]')
                    await page.wait_for_selector('#externalProjectCardsArea:has-text("Approved training days")')
                    assert '1 / 8' in await page.locator('#externalProjectCardsArea').inner_text()
                    await page.click('[data-dtab="all"]')
                    await page.wait_for_selector('#crossProjectProgress tbody tr:has-text("ramco")')
                    assert 'Freelancer Training' in await page.locator('#crossProjectProgress').inner_text()
                    await page.screenshot(path=str(ROOT / 'qa-unified-dashboard.png'))
                    assert not errors, errors
                    print('PASS Chromium Admin Vendor/Freelancer dashboard approved progress',flush=True)
                finally:
                    await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
