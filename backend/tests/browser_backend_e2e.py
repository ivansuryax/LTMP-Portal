"""Browser DOM -> real FastAPI TestClient -> disposable SQL DB regression.
Uses a direct Python browser bridge because loopback browser networking is blocked
in the authoring environment. It does NOT test Vite, Nginx, Docker or TLS.
"""
import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright
from fastapi.testclient import TestClient
from app.db import User, SheetRow, setup_engine, session_factory
from app.security import hash_password
from app.main import create_app

ROOT=Path(__file__).resolve().parents[2]
SHELL=(ROOT/'frontend/src/original-shell.html').read_text()
CSS=(ROOT/'frontend/src/original.css').read_text()
JS=(ROOT/'frontend/public/legacy.js').read_text()

async def main():
    with TemporaryDirectory() as tmp:
        url=f'sqlite+pysqlite:///{tmp}/e2e.db'
        factory=session_factory(setup_engine(url))
        with factory.begin() as db:
            for name,role,boss in [('admin','Admin',''),('rm','Reporting Manager','admin'),
                                   ('lead','Team Leader','rm'),('trainer','Trainer','lead')]:
                db.add(User(username=name,user_id=name,role=role,full_name=name.title(),
                            password_hash=hash_password('test-password-123'),active=True,
                            reporting_manager_username=boss))
            db.add(SheetRow(sheet_name='ActivityMaster',source_row=2,data={
                'ActivityCode':'ACT','ActivityName':'Workshop','Active':True}))
        with TestClient(create_app(url)) as api:
            async with async_playwright() as pw:
                browser=await pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,
                    args=['--no-sandbox','--disable-dev-shm-usage'])
                try:
                    page=await browser.new_page(viewport={'width':1280,'height':900})
                    page.set_default_timeout(9000)
                    errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    async def bridge(name,args):
                        r=api.post('/api/rpc/'+name,json={'args':args})
                        if r.status_code>=400:
                            raise RuntimeError(str(r.json().get('detail',r.status_code)))
                        return r.json()
                    await page.expose_function('ltmpBridge',bridge)
                    await page.set_content(f'<html><head><style>{CSS}</style></head><body>{SHELL}</body></html>',wait_until='domcontentloaded')
                    await page.evaluate('window.ltmpApi={call:(name,...args)=>window.ltmpBridge(name,args)}')
                    await page.add_script_tag(content=JS)
                    async def login(who):
                        await page.fill('#loginUsername',who)
                        await page.fill('#loginPassword','test-password-123')
                        await page.click('button:has-text("Sign In")')
                        await page.wait_for_selector('#appShell.active')
                    await login('trainer')
                    await page.click('.nav-pill[data-page="leave"]')
                    await page.wait_for_selector('#leaveRequestsArea table')
                    await page.fill('#leaveStart','2026-10-14')
                    await page.fill('#leaveEnd','2026-10-16')
                    await page.fill('#leaveComments','Planned personal leave')
                    await page.click('button:has-text("Submit")')
                    await page.wait_for_selector('#leaveRequestsArea tbody tr:has-text("Pending")')
                    print('Trainer leave persisted',flush=True)
                    await page.click('.nav-pill[data-page="dailytracker"]')
                    await page.wait_for_selector('#dtActivity option[value="ACT"]', state='attached')
                    await page.fill('#dtDate','2026-10-14')
                    await page.select_option('#dtActivity','ACT')
                    await page.fill('#dtTopic','Workshop practice')
                    await page.fill('#dtHours','2')
                    await page.click('button:has-text("Submit")')
                    await page.wait_for_selector('#dtMyEntriesArea tbody tr:has-text("Pending")')
                    print('Trainer activity persisted',flush=True)
                    await page.click('button:has-text("Logout")')
                    await login('lead')
                    await page.click('.nav-pill[data-page="leave"]')
                    await page.wait_for_selector('#leaveRequestsArea tbody tr:has-text("Pending")')
                    page.once('dialog',lambda d: asyncio.create_task(d.accept('Approved')))
                    await page.click('#leaveRequestsArea button:has-text("Approve")')
                    await page.wait_for_selector('#leaveRequestsArea tbody tr:has-text("Approved")')
                    print('Team Leader leave approval persisted',flush=True)
                    await page.click('.nav-pill[data-page="dailytracker"]')
                    await page.wait_for_selector('#dtEntriesArea tbody tr:has-text("Pending")')
                    page.once('dialog',lambda d: asyncio.create_task(d.accept('Approved')))
                    await page.click('#dtEntriesArea button:has-text("Approve")')
                    await page.wait_for_selector('#dtEntriesArea tbody tr:has-text("Approved")')
                    print('Team Leader tracker approval persisted',flush=True)
                    await page.click('button:has-text("Logout")')
                    await login('rm')
                    await page.click('.nav-pill[data-page="leave"]')
                    await page.wait_for_selector('#leaveRequestsArea table')
                    await page.click('button:has-text("Logout")')
                    await login('admin')
                    await page.click('.nav-pill[data-page="leave"]')
                    await page.wait_for_selector('#leaveRequestsArea tbody tr:has-text("Approved")')
                    await page.click('.nav-pill[data-page="dailytracker"]')
                    await page.wait_for_selector('#dtEntriesArea table')
                    assert not errors,errors
                    print('Chromium original shell + real FastAPI/DB: four role E2E passed',flush=True)
                finally:
                    await browser.close()
if __name__=='__main__':asyncio.run(main())
