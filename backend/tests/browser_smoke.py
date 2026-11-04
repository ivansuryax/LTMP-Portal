"""Playwright smoke test of real Chromium rendering original LTMP shell/legacy JS.
Uses stub RPCs, not a live database; independent of npm/Vite availability.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
SHELL = (ROOT / 'frontend/src/original-shell.html').read_text()
CSS = (ROOT / 'frontend/src/original.css').read_text()
JS = (ROOT / 'frontend/public/legacy.js').read_text()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path='/usr/bin/chromium',
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            tested = []
            for role in ['Admin', 'Reporting Manager', 'Team Leader', 'Trainer']:
                print('Starting role',role,flush=True)
                page = await browser.new_page(viewport={'width': 1400, 'height': 900})
                page.set_default_timeout(3500)
                errors = []
                page.on('pageerror', lambda ex: errors.append(str(ex)))
                await page.set_content(f'<html><head><style>{CSS}</style></head><body>{SHELL}</body></html>',wait_until='domcontentloaded')
                await page.evaluate('''role => {
                    window.ltmpApi={call:async (name,...args) => {
                        if(name==='login')return {success:true,user:{username:'sample',fullName:'Test User',role,email:''}};
                        if(name==='getLeaveRequests')return [{leaveID:'L1',employeeUsername:'sample',employeeName:'Trainer Test',status:'Pending',startDate:'2026-10-14',endDate:'2026-10-16',numberOfDays:3,reportingManagerUsername:'sample',comments:'Example'}];
                        if(name==='getLeaveAlerts'||name==='getAlerts')return [];
                        if(name==='getAlertCount')return 0;
                        if(name==='getDashboardData')return {summary:{totalColleges:0,totalTrainers:0,activeTrainers:0,nonActiveTrainers:0,running:0,completed:0,upcoming:0,onHold:0,cancelled:0},colleges:[],roster:[]};
                        if(name==='getKpiDashboardData')return {myKpis:[],teamKpis:[]};
                        if(name==='getDailyActivityApprovals'||name==='getMyDailyActivities'||name==='getActivityMaster'||name==='getClassLocationOptions'||name==='getDailyActivityMissingAlerts')return [];
                        if(name==='getVendorProjects'||name==='getFreelanceProjects'||name==='getUsers'||name==='getTrainerUsers'||name==='getMyColleges'||name==='getMyDailyUpdates')return [];
                        return [];
                    }};
                }''', role)
                await page.add_script_tag(content=JS)
                await page.fill('#loginUsername','sample')
                await page.fill('#loginPassword','testing')
                await page.click('button:has-text("Sign In")')
                await page.wait_for_selector('#appShell.active')
                print(role, 'logged in',flush=True)
                if role != 'Trainer':
                    print(role,'open leave',flush=True)
                    await page.click('.nav-pill[data-page="leave"]')
                    await page.wait_for_selector('#leaveRequestsArea table')
                    if role == 'Admin':
                        assert await page.locator('text=Assigned Approver').count() >= 1
                    print(role,'open tracker',flush=True)
                    await page.click('.nav-pill[data-page="dailytracker"]')
                    await page.wait_for_selector('#dtEntriesArea table')
                else:
                    print(role,'open leave',flush=True)
                    await page.click('.nav-pill[data-page="leave"]')
                    await page.wait_for_selector('#leaveRequestsArea table')
                await page.screenshot(path=str(ROOT / ('qa-' + role.lower().replace(' ','-') + '.png')), full_page=True)
                if errors:
                    raise AssertionError(f'{role} browser errors: {errors[:2]}')
                tested.append(role)
                await page.close()
            print('Chromium shell smoke passed:', ', '.join(tested))
        finally:
            await browser.close()

if __name__=='__main__':
    asyncio.run(main())
