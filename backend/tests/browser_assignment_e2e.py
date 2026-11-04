"""Admin UI creates/assigns college -> Trainer UI sees notification and Daily Update.

Uses a disposable SQLite DB with FastAPI TestClient as an in-process RPC bridge.
Chromium renders real LTMP legacy HTML/CSS/JS. This is NOT a Docker/Nginx test.
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
        url = f'sqlite+pysqlite:///{tmp}/assignment_e2e.db'
        factory = session_factory(setup_engine(url))
        with factory.begin() as db:
            for username, role, manager in [('admin', 'Admin', ''), ('trainer1', 'Trainer', 'admin')]:
                db.add(User(user_id=username, username=username, full_name=username.title(),
                    role=role, reporting_manager_username=manager, active=True,
                    password_hash=hash_password('test-password-123')))
        with TestClient(create_app(url)) as api:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(executable_path='/usr/bin/chromium',
                    headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                try:
                    page = await browser.new_page(viewport={'width': 1400, 'height': 1000})
                    page.set_default_timeout(12000)
                    js_errors = []
                    page.on('pageerror', lambda e: js_errors.append(str(e)))

                    async def bridge(name, args):
                        response = api.post('/api/rpc/' + name, json={'args': args})
                        if response.status_code >= 400:
                            raise RuntimeError(str(response.json().get('detail', response.status_code)))
                        return response.json()

                    await page.expose_function('ltmpBridge', bridge)
                    await page.set_content('<html><head><style>' + CSS + '</style></head><body>' + SHELL + '</body></html>',
                                           wait_until='domcontentloaded')
                    await page.evaluate('window.ltmpApi={call:(name,...args)=>window.ltmpBridge(name,args)}')
                    await page.add_script_tag(content=JS)

                    async def login(username):
                        await page.fill('#loginUsername', username)
                        await page.fill('#loginPassword', 'test-password-123')
                        await page.click('button:has-text("Sign In")')
                        await page.wait_for_selector('#appShell.active')

                    await login('admin')
                    await page.evaluate('openCreateCollege()')
                    await page.fill('#ncName', 'Testing College')
                    await page.select_option('#ncStatus', 'Running')
                    category_inputs = page.locator('#categoryRowsArea input')
                    await category_inputs.nth(0).fill('Java')
                    await category_inputs.nth(1).fill('10')
                    await page.click('#modalFooter button:has-text("Create Project")')
                    await page.wait_for_selector('#modalOverlay:not(.active)', state='attached')
                    result = api.post('/api/rpc/getColleges', json={'args': []})
                    assert result.status_code == 200
                    data = result.json()
                    code = next(x['collegeCode'] for x in data if x['collegeName'] == 'Testing College')
                    print('Admin college creation -> database passed', flush=True)

                    await page.evaluate('(code) => renderCollegeProfile(code)', code)
                    await page.wait_for_selector('#profileTabs')
                    await page.evaluate('(code) => openAssignTrainer(code)', code)
                    await page.wait_for_selector('#atUsername option[value="trainer1"]', state='attached')
                    await page.select_option('#atUsername', 'trainer1')
                    if await page.locator('#atCategory').evaluate('(el) => el.tagName') == 'SELECT':
                        await page.select_option('#atCategory', 'Java')
                        assert await page.locator('#atCategory option').count() == 2
                    else:
                        await page.fill('#atCategory', 'Java')
                    await page.fill('#atFrom', '2026-10-01')
                    await page.fill('#atTo', '2026-10-31')
                    await page.select_option('#atStatus', 'Running')
                    await page.click('#modalFooter button:has-text("Assign")')
                    await page.wait_for_selector('#modalOverlay:not(.active)', state='attached')
                    print('Admin trainer assignment -> persisted', flush=True)

                    await page.click('button:has-text("Logout")')
                    await login('trainer1')
                    await page.wait_for_selector('#myProjectList:has-text("Testing College")')
                    await page.click('.nav-pill[data-page="mycolleges"]')
                    await page.wait_for_selector('#collegeGridArea:has-text("Testing College")')
                    await page.click('.nav-pill[data-page="alerts"]')
                    await page.wait_for_selector('.alert-row:has-text("Assigned to Testing College")')
                    await page.click('.alert-row:has-text("Assigned to Testing College")')
                    await page.wait_for_selector('#myProjectList:has-text("Testing College")')
                    print('Trainer alert opened My Projects -> passed', flush=True)

                    await page.click('.nav-pill[data-page="dailyupdate"]')
                    await page.wait_for_selector('#duCollege')
                    assert await page.locator('#duCollege').input_value() == 'lesuccess:' + code
                    assert await page.locator('#duCategory').input_value() == 'Java'
                    await page.fill('#duDate', '2026-10-13')
                    await page.fill('#duTopic', 'Collections Practice')
                    await page.fill('#duAttendance', '85')
                    await page.click('button:has-text("Submit Update")')
                    await page.wait_for_selector('#myDailyUpdatesArea tbody tr:has-text("Collections Practice")')
                    assert not js_errors, js_errors
                    print('Trainer Daily Update submit -> persisted / history rendered', flush=True)
                    print('PASS Chromium UI + FastAPI real DB assignment/notification/daily update', flush=True)
                finally:
                    await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
