
  /* =====================================================================
     LTMP FRONTEND
     ===================================================================== */
  let currentUser = null;
  let currentPage = 'dashboard';
  let dashboardTab = 'lesuccess';
  let collegesCache = [];
  let trainerUsersCache = []; // active trainers, for assignment dropdowns
  let alertRefreshTimer = null;

  // ---------- helpers ----------
  function showLoading(on){ document.getElementById('loadingOverlay').classList.toggle('active', on); }
  function showToast(msg, isError){
    const t = document.getElementById('toast');
    t.textContent = msg; t.className = 'toast' + (isError ? ' error' : '');
    t.style.display = 'block';
    setTimeout(() => t.style.display = 'none', 3400);
  }
  function callServer(fn, ...args){
    return window.ltmpApi.call(fn, ...args).catch(err => {
      showToast(err.message || String(err), true);
      throw err;
    });
  }
  // Any failure past this point — including a JS error while building the
  // page, not just a server-side one — gets logged to the console and
  // shown to the user, instead of silently leaving a section blank.
  function handleError(err){
    console.error(err);
    showToast('Something went wrong loading this page: ' + (err && err.message ? err.message : String(err)), true);
  }
  function fmtDate(d){
    if(!d) return '—';
    const dt = new Date(d);
    if(isNaN(dt)) return d;
    return dt.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric'});
  }
  function escapeHtml(s){
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function statusClass(status){ return String(status || '').replace(/\s+/g, ''); }

  // ---------- LOGIN ----------
  function doLogin(){
    const u = document.getElementById('loginUsername').value.trim().replace(/^(\d+)\.0$/, '$1');
    const p = document.getElementById('loginPassword').value;
    const errEl = document.getElementById('loginError');
    errEl.textContent = '';
    if(!u || !p){ errEl.textContent = 'Please enter both username and password.'; return; }
    showLoading(true);
    callServer('login', u, p).then(res => {
      showLoading(false);
      if(!res.success){ errEl.textContent = res.message; return; }
      currentUser = res.user;
      document.getElementById('loginScreen').style.display = 'none';
      document.getElementById('appShell').classList.add('active');
      document.getElementById('sbUserName').textContent = currentUser.fullName;
      document.getElementById('sbUserRole').textContent = currentUser.designation ? (currentUser.designation + ' · ' + currentUser.role) : currentUser.role;
      buildNav();
      updateAlertBadge();
      if(alertRefreshTimer) clearInterval(alertRefreshTimer);
      alertRefreshTimer = setInterval(updateAlertBadge, 30000);
      const landing = (currentUser.role === 'Trainer') ? 'myprojects' : 'dashboard';
      navigate(landing);
    }).catch(err => { showLoading(false); handleError(err); });
  }
  function logout(){
    if(alertRefreshTimer) clearInterval(alertRefreshTimer);
    alertRefreshTimer = null;
    window.ltmpApi.call('logout').catch(() => {});
    document.getElementById('modalOverlay')?.classList.remove('active');
    collegesCache = []; trainerUsersCache = [];
    window._vendorTrainerOptions = null;
    currentUser = null;
    document.getElementById('appShell').classList.remove('active');
    document.getElementById('loginScreen').style.display = 'flex';
    document.getElementById('loginUsername').value = '';
    document.getElementById('loginPassword').value = '';
  }

  // Every assignment mutation is checked in the API again at commit.
  // These controls are guidance; authorization cannot depend on the UI.
  function bookingConflictDialog(rows, onOverride){
    const conflicts = Array.isArray(rows) ? rows : [];
    let holder=document.getElementById('ltmpBookingConflict');
    if(!holder){
      holder=document.createElement('div');
      holder.id='ltmpBookingConflict';
      document.getElementById('modalBody').appendChild(holder);
    }
    holder.innerHTML=`<div role="alert" style="background:#fff5ed;border:2px solid #f59e0b;border-radius:10px;padding:15px;margin-top:14px;">
      <strong style="color:#a94109;">⚠ Warning: Trainer is already occupied.</strong>
      <p style="margin:8px 0;">Another session or approved leave overlaps this date/time slot.</p>
      ${conflicts.map(c => `<p style="margin:6px 0;font-size:13px;"><b>${escapeHtml(c.projectName || 'Existing booking')}</b>
        — ${escapeHtml(c.batch || 'All batches')} / ${escapeHtml(c.location || 'Location not specified')}<br>
        ${escapeHtml(c.startDate || '')} to ${escapeHtml(c.endDate || '')}
        ${escapeHtml(c.startTime || '')} ${c.endTime ? '– ' + escapeHtml(c.endTime) : ''}</p>`).join('')}
      <p style="font-size:12px;color:#7d4925;">Only Admin may explicitly override a conflicting booking.</p>
    </div>`;
    const footer=document.getElementById('modalFooter');
    footer.innerHTML='';
    const cancel=document.createElement('button');
    cancel.type='button';cancel.className='btn btn-outline';cancel.textContent='Cancel';
    cancel.onclick=()=>closeModal();
    footer.appendChild(cancel);
    if(isAdminUser()){
      const override=document.createElement('button');
      override.type='button';override.className='btn btn-red';
      override.textContent='Override & Proceed';
      override.onclick=()=>onOverride();
      footer.appendChild(override);
    }
  }
  function assignmentWriteWithSchedule(rpcName, payload, onSaved){
    if(!isApproverUser()){
      showToast('Trainers are not permitted to reassign jobs.',true);return;
    }
    const proceed=(override)=>{
      showLoading(true);
      callServer(rpcName,{...payload,acknowledgeConflict:override}).then(result=>{
        showLoading(false);
        if(result && result.success){onSaved(result);return;}
        showToast(result?.message || 'Could not save assignment.',true);
      }).catch(err=>{
        showLoading(false);
        if(err.status===409 && err.conflicts){bookingConflictDialog(err.conflicts,()=>proceed(true));return;}
        handleError(err);
      });
    };
    // Free-text external freelancer without a portal employee has no schedule.
    if(!payload.trainerUsername || ['Completed','Cancelled','Not Active'].includes(payload.status || payload.assignmentStatus)){
      proceed(false);return;
    }
    showLoading(true);
    callServer('checkTrainerSchedule',{
      trainerUsername:payload.trainerUsername,
      startDate:payload.startDate || payload.fromDate,
      endDate:payload.endDate || payload.toDate,
      startTime:payload.startTime || '',endTime:payload.endTime || '',
      projectType:payload.projectType || '',projectId:payload.projectId || payload.projectID || payload.collegeCode || '',
      category:payload.category || ''
    }).then(result=>{
      showLoading(false);
      if(result.is_occupied){bookingConflictDialog(result.conflicts,()=>proceed(true));return;}
      proceed(false);
    }).catch(err=>{showLoading(false);handleError(err);});
  }

  function setupExternalBookingPreview(prefix,kind,projectId){
    const body=document.getElementById('modalBody');
    if(!body)return;
    const summary=document.createElement('div');
    summary.id='ltmpBookingPreview';
    summary.className='field-hint';
    summary.style.marginTop='12px';
    body.appendChild(summary);
    let generation=0;
    const check=()=>{
      const trainer=document.getElementById(prefix+'TrainerSelect')?.value;
      const from=document.getElementById(prefix+'StartDate')?.value;
      const to=document.getElementById(prefix+'EndDate')?.value;
      const first=document.getElementById(prefix+'StartTime')?.value || '';
      const last=document.getElementById(prefix+'EndTime')?.value || '';
      const token=++generation;
      if(!trainer || trainer==='__other__' || !from || !to){
        summary.textContent='Select a registered Trainer Employee ID and dates to check availability.';
        return;
      }
      summary.textContent='Checking trainer schedule…';
      window.ltmpApi.call('checkTrainerSchedule',{
        trainerUsername:trainer,startDate:from,endDate:to,
        startTime:first,endTime:last,projectType:kind,
        projectId:projectId || '',category:document.getElementById(prefix+'Category')?.value || ''
      }).then(r=>{
        if(token!==generation || !summary.isConnected)return;
        if(r.is_occupied){
          summary.innerHTML='<span style="color:var(--red);font-weight:600;">⚠ Trainer is already occupied.</span> '+
            r.conflicts.map(c=>escapeHtml(c.projectName)+(c.batch?' / '+escapeHtml(c.batch):'')).join('; ')+
            '. Choose another slot or save with explicit Admin override.';
        }else{
          summary.innerHTML='<span style="color:var(--green)">Trainer available for selected dates/time.</span>';
        }
      }).catch(err=>{
        if(token===generation && summary.isConnected)summary.textContent=err.message;
      });
    };
    [prefix+'TrainerSelect',prefix+'StartDate',prefix+'EndDate',
     prefix+'StartTime',prefix+'EndTime'].forEach(key=>{
      document.getElementById(key)?.addEventListener('change',check);
    });
    check();
  }

  // ---------- ROLE HELPERS ----------
  function isAdminUser(){
    return currentUser && String(currentUser.role || '').trim() === 'Admin';
  }

  function isReportingManagerUser(){
    return currentUser && String(currentUser.role || '').trim() === 'Reporting Manager';
  }

  function isTeamLeaderUser(){
    return currentUser && String(currentUser.role || '').trim() === 'Team Leader';
  }

  function isTrainerUser(){
    return currentUser && String(currentUser.role || '').trim() === 'Trainer';
  }

  // Anyone who can approve someone else's Daily Tracker / KPI / Leave —
  // Team Leader, Reporting Manager, or Admin (everyone except Trainer).
  function isApproverUser(){
    return isTeamLeaderUser() || isReportingManagerUser() || isAdminUser();
  }

  // Anyone who submits their own Daily Tracker / KPI / Leave one level up —
  // Trainer, Team Leader, or Reporting Manager (everyone except Admin).
  function isSubmitterUser(){
    return isTrainerUser() || isTeamLeaderUser() || isReportingManagerUser();
  }

  function profileBackPage(){
    return isTrainerUser() ? 'mycolleges' : 'dashboard';
  }

  function profileBackLabel(){
    return isTrainerUser() ? 'Back to My Colleges' : 'Back to Dashboard';
  }

  // ---------- NAV ----------
  const NAV_BY_ROLE = {
    Admin: [
      {id:'dashboard', label:'Dashboard'},
      {id:'kpi', label:'KPI'},
      {id:'alerts', label:'Alerts'},
      {id:'reports', label:'Reports'},
      {id:'activitymaster', label:'Activity Master'},
      {id:'users', label:'User Management'},
      {id:'leave', label:'Leave Management'},
      {id:'dailytracker', label:'Daily Tracker'},
      {id:'approvals', label:'Training Approvals'}
    ],
    'Reporting Manager': [
      {id:'dashboard', label:'Dashboard'},
      {id:'approvals', label:'Training Approvals'},
      {id:'dailytracker', label:'Daily Tracker'},
      {id:'kpi', label:'KPI'},
      {id:'leave', label:'Leave'},
      {id:'alerts', label:'Alerts'},
      {id:'reports', label:'Reports'}
    ],
    'Team Leader': [
      {id:'dashboard', label:'Dashboard'},
      {id:'dailytracker', label:'Daily Tracker'},
      {id:'kpi', label:'KPI'},
      {id:'leave', label:'Leave'},
      {id:'alerts', label:'Alerts'},
      {id:'reports', label:'Reports'}
    ],
    Trainer: [
      {id:'myprojects', label:'My Projects'},
      {id:'mycolleges', label:'My Colleges'},
      {id:'dailyupdate', label:'Daily Update'},
      {id:'dailytracker', label:'Daily Tracker'},
      {id:'kpi', label:'KPI'},
      {id:'leave', label:'Leave'},
      {id:'alerts', label:'Alerts'}
    ]
  };
  function buildNav(){
    const items = NAV_BY_ROLE[currentUser.role] || [];
    document.getElementById('navItems').innerHTML = items.map(i =>
      `<div class="nav-pill" data-page="${i.id}" onclick="navigate('${i.id}')">${i.label}${i.id === 'alerts' ? ' <span id=\"alertBadge\" class=\"alert-badge\" style=\"display:none;\"></span>' : ''}</div>`).join('');
  }
  function setActiveNav(page){
    document.querySelectorAll('.nav-pill').forEach(el => el.classList.toggle('active', el.dataset.page === page));
  }

  // Bell-badge unread count (like WhatsApp) — how many items getAlerts()
  // would currently show this person, across Colleges/Leave/Daily
  // Tracker/KPI. Refreshed on login and after navigating to Alerts (which
  // is when the underlying items usually get cleared).
  function updateAlertBadge(){
    if(!currentUser) return;
    callServer('getAlertCount', currentUser.username).then(count => {
      const el = document.getElementById('alertBadge');
      if(!el) return;
      const n = Number(count) || 0;
      if(n > 0){ el.textContent = n > 99 ? '99+' : String(n); el.style.display = 'inline-block'; }
      else { el.style.display = 'none'; }
    }).catch(() => {});
  }

  function navigate(page, param){
    currentPage = page;
    setActiveNav(page);
    if(page === 'dashboard') renderDashboard();
    else if(page === 'alerts'){ renderAlerts(); setTimeout(updateAlertBadge, 800); }
    else if(page === 'reports') renderReports();
    else if(page === 'users') renderUsers();
    else if(page === 'approvals') renderApprovals();
    else if(page === 'mycolleges') renderMyColleges();
    else if(page === 'myprojects') renderMyProjects();
    else if(page === 'dailyupdate') renderDailyUpdateForm();
    else if(page === 'dailytracker') renderDailyTrackerPage();
    else if(page === 'kpi') renderKpiPage();
    else if(page === 'activitymaster') renderActivityMaster();
    else if(page === 'leave') renderLeavePage();
    else if(page === 'collegeProfile') renderCollegeProfile(param);
  }

  function content(html){ document.getElementById('pageContent').innerHTML = html; }

  // ---------- DASHBOARD (3-way: LeSuccess / Vendor / Freelance) ----------
  function renderDashboard(){
    content(`
      <div class="dash-tab-bar" id="dashTabBar"></div>
      <div id="dashTabContent"></div>
    `);
    document.getElementById('dashTabBar').innerHTML = `
      <button class="dash-tab-btn" data-dtab="all" onclick="switchDashTab('all')">All Projects</button>
      <button class="dash-tab-btn" data-dtab="lesuccess" onclick="switchDashTab('lesuccess')">LeSuccess Projects</button>
      <button class="dash-tab-btn" data-dtab="vendor" onclick="switchDashTab('vendor')">Vendor Projects</button>
      <button class="dash-tab-btn" data-dtab="freelance" onclick="switchDashTab('freelance')">Freelancers</button>

      ${currentUser.role === 'Admin' ? `
        <div class="dash-new-project-wrap" id="newProjectMenuWrap">
          <button type="button"
                  class="dash-new-project-btn"
                  onclick="toggleNewProjectMenu(event)">
            + New Project
          </button>

          <div class="dash-new-project-menu" id="newProjectMenu">
            <button type="button"
                    class="dash-new-project-option"
                    onclick="createProjectFromMenu('lesuccess')">
              LeSuccess Project
            </button>

            <button type="button"
                    class="dash-new-project-option"
                    onclick="createProjectFromMenu('vendor')">
              Vendor Project
            </button>

            <button type="button"
                    class="dash-new-project-option"
                    onclick="createProjectFromMenu('freelance')">
              Freelancer Project
            </button>
          </div>
        </div>
      ` : ''}
    `;
    switchDashTab(dashboardTab);
  }
  function toggleNewProjectMenu(event){
    if(event) event.stopPropagation();
    const menu = document.getElementById('newProjectMenu');
    if(menu) menu.classList.toggle('open');
  }

  function closeNewProjectMenu(){
    const menu = document.getElementById('newProjectMenu');
    if(menu) menu.classList.remove('open');
  }

  function createProjectFromMenu(type){
    closeNewProjectMenu();

    if(currentUser.role !== 'Admin'){
      showToast('Only Admin can create projects.', true);
      return;
    }

    if(type === 'lesuccess'){
      openCreateCollege();
    }else if(type === 'vendor'){
      openAddVendorProject();
    }else if(type === 'freelance'){
      openAddFreelanceProject();
    }
  }

  document.addEventListener('click', function(event){
    const wrap = document.getElementById('newProjectMenuWrap');
    if(wrap && !wrap.contains(event.target)){
      closeNewProjectMenu();
    }
  });

  function switchDashTab(tab){
    closeNewProjectMenu();
    dashboardTab = tab;

    document.querySelectorAll('#dashTabBar .dash-tab-btn').forEach(b => {
      const active = b.dataset.dtab === tab;
      b.classList.toggle('active', active);
      b.setAttribute('aria-selected', active ? 'true' : 'false');
    });

    if(tab === 'all'){
      renderAllProjectsTab();
    }else if(tab === 'lesuccess'){
      renderLeSuccessTab();
    }else if(tab === 'vendor'){
      renderVendorTab();
    }else if(tab === 'freelance'){
      renderFreelanceTab();
    }
  }

  // ---------- ALL PROJECTS TAB ----------
  // Combined dashboard: LeSuccess + Vendor + Freelancer
  function renderAllProjectsTab(){
    const area = document.getElementById('dashTabContent');

    area.innerHTML = `
      <div class="subsection-label">Project Status</div>
      <div class="summary-grid" id="allProjectStatusCards"></div>

      <div class="subsection-label">Trainers</div>
      <div class="summary-grid"
           id="allProjectTrainerCards"
           style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));max-width:600px;"></div>

      <div class="dashboard-column" style="padding:18px;margin-top:22px;"><h3>Cross-Project Training Progress</h3><div id="crossProjectProgress" class="table-wrap">Loading approved progress…</div></div>
      <div class="dashboard-split-columns" style="margin-top:26px;">
        <section class="dashboard-column">
          <div class="dashboard-column-header">
            <h3>All Projects</h3>
          </div>

          <div id="allProjectsLeftArea" class="dashboard-column-scroll">
            <div class="empty-state">Loading projects…</div>
          </div>
        </section>

        <section class="dashboard-column">
          <div class="dashboard-column-header">
            <h3>Trainer Roster</h3>
          </div>

          <div id="allProjectsTrainerArea" class="dashboard-column-scroll">
            <div class="empty-state">Loading trainers…</div>
          </div>
        </section>
      </div>
    `;

    showLoading(true);

    Promise.all([
      callServer('getDashboardData'),
      callServer('getVendorProjects'),
      callServer('getFreelanceProjects')
    ]).then(([dashboard, vendorRows, freelanceRows]) => {
      showLoading(false);

      dashboard = dashboard || {};

      const colleges = Array.isArray(dashboard.colleges)
        ? dashboard.colleges
        : [];

      const roster = Array.isArray(dashboard.roster)
        ? dashboard.roster
        : [];

      vendorRows = Array.isArray(vendorRows) ? vendorRows : [];
      freelanceRows = Array.isArray(freelanceRows) ? freelanceRows : [];

      collegesCache = colleges;
      vendorRowsCache = vendorRows;
      freelanceRowsCache = freelanceRows;
      window._trainerRoster = roster;

      const summary = combinedProjectSummary_(
        colleges,
        vendorRows,
        freelanceRows,
        roster
      );

      document.getElementById('allProjectStatusCards').innerHTML =
        combinedStatusCardsHtml(summary, 'all');

      document.getElementById('allProjectTrainerCards').innerHTML =
        combinedTrainerCardsHtml(summary, 'all');

      document.getElementById('allProjectsLeftArea').innerHTML =
        combinedProjectsHtml(colleges, vendorRows, freelanceRows);

      document.getElementById('allProjectsTrainerArea').innerHTML =
        combinedTrainerRosterHtml(roster, vendorRows, freelanceRows);
      callServer('getProjectProgress').then(progress => {
        const el = document.getElementById('crossProjectProgress');
        if(!el || dashboardTab !== 'all') return;
        const data = Array.isArray(progress) ? progress : [];
        el.innerHTML = `<table><thead><tr><th>Type</th><th>Project</th><th>Approved Days</th><th>Planned Days</th><th>Progress</th><th>Pending</th></tr></thead><tbody>${data.map(r=>`<tr><td>${escapeHtml(r.projectType)}</td><td>${escapeHtml(r.projectName)}</td><td>${Number(r.completedDays)||0}</td><td>${Number(r.plannedDays)||0}</td><td>${Number(r.progressPercent)||0}%</td><td>${Number(r.pendingUpdates)||0}</td></tr>`).join('') || '<tr><td colspan="6">No projects</td></tr>'}</tbody></table>`;
      }).catch(err => { const el=document.getElementById('crossProjectProgress'); if(el) el.textContent='Unable to load training progress.'; });

    }).catch(err => {
      showLoading(false);
      handleError(err);

      const msg = escapeHtml(
        err && err.message ? err.message : String(err)
      );

      ['allProjectsLeftArea','allProjectsTrainerArea'].forEach(id => {
        const el = document.getElementById(id);
        if(el){
          el.innerHTML =
            `<div class="empty-state">Unable to load data.<br><small>${msg}</small></div>`;
        }
      });
    });
  }

  // ---------- COMBINED PROJECT SUMMARY ----------
  function combinedProjectSummary_(colleges, vendorRows, freelanceRows, roster){
    colleges = Array.isArray(colleges) ? colleges : [];
    vendorRows = Array.isArray(vendorRows) ? vendorRows : [];
    freelanceRows = Array.isArray(freelanceRows) ? freelanceRows : [];
    roster = Array.isArray(roster) ? roster : [];

    const collegeStatuses = colleges.map(c =>
      String(c.status || '').trim()
    );

    const vendorStatuses = vendorRows.map(externalProjectStatus_);
    const freelanceStatuses = freelanceRows.map(externalProjectStatus_);

    const statuses = [
      ...collegeStatuses,
      ...vendorStatuses,
      ...freelanceStatuses
    ];

    const countStatus = status =>
      statuses.filter(s =>
        String(s).toLowerCase() === String(status).toLowerCase()
      ).length;

    /*
     * LeSuccess trainer roster comes from DashboardData.
     * Vendor/Freelancer trainers are collected from their project rows.
     */
    const people = new Set();

    roster.forEach(t => {
      const name = String(
        t.fullName || t.username || ''
      ).trim();

      if(name) people.add(name.toLowerCase());
    });

    vendorRows.forEach(r => {
      const name = String(r.trainerName || '').trim();
      if(name) people.add(name.toLowerCase());
    });

    freelanceRows.forEach(r => {
      const name = String(r.freelancerName || '').trim();
      if(name) people.add(name.toLowerCase());
    });

    /*
     * Active = currently assigned to Running / Upcoming / On Hold.
     */
    const activePeople = new Set();

    roster.forEach(t => {
      if(t.active){
        const name = String(
          t.fullName || t.username || ''
        ).trim().toLowerCase();

        if(name) activePeople.add(name);
      }
    });

    vendorRows.forEach(r => {
      const name = String(r.trainerName || '').trim().toLowerCase();

      if(name){
        const s = externalProjectStatus_(r);

        if(
          s === 'Running' ||
          s === 'Upcoming' ||
          s === 'On Hold'
        ){
          activePeople.add(name);
        }
      }
    });

    freelanceRows.forEach(r => {
      const name = String(r.freelancerName || '').trim().toLowerCase();

      if(name){
        const s = externalProjectStatus_(r);

        if(
          s === 'Running' ||
          s === 'Upcoming' ||
          s === 'On Hold'
        ){
          activePeople.add(name);
        }
      }
    });

    return {
      totalProjects: statuses.length,
      totalColleges: colleges.length,

      running: countStatus('Running'),
      upcoming: countStatus('Upcoming'),
      onHold: countStatus('On Hold'),
      completed: countStatus('Completed'),

      totalTrainers: people.size,
      activeTrainers: activePeople.size,
      nonActiveTrainers: Math.max(
        0,
        people.size - activePeople.size
      )
    };
  }

  function combinedStatusCardsHtml(summary, mode){
    const clickPrefix = mode === 'all'
      ? 'openAllProjectMetric'
      : 'openAllProjectMetric';

    return `
      <div class="summary-card dashboard-clickable"
           onclick="${clickPrefix}('total')">
        <div class="num">${Number(summary.totalProjects) || 0}</div>
        <div class="lbl">Total Projects</div>
      </div>

      <div class="summary-card green-side dashboard-clickable"
           onclick="${clickPrefix}('Running')">
        <div class="num">${Number(summary.running) || 0}</div>
        <div class="lbl">Running</div>
      </div>

      <div class="summary-card blue-side dashboard-clickable"
           onclick="${clickPrefix}('Upcoming')">
        <div class="num">${Number(summary.upcoming) || 0}</div>
        <div class="lbl">Upcoming</div>
      </div>

      <div class="summary-card amber-side dashboard-clickable"
           onclick="${clickPrefix}('On Hold')">
        <div class="num">${Number(summary.onHold) || 0}</div>
        <div class="lbl">On Hold</div>
      </div>

      <div class="summary-card gray-side dashboard-clickable"
           onclick="${clickPrefix}('Completed')">
        <div class="num">${Number(summary.completed) || 0}</div>
        <div class="lbl">Completed</div>
      </div>
    `;
  }

  function combinedTrainerCardsHtml(summary, mode){
    return `
      <div class="summary-card dashboard-clickable"
           onclick="openAllTrainerMetric('total')">
        <div class="num">${Number(summary.totalTrainers) || 0}</div>
        <div class="lbl">Total Trainers</div>
      </div>

      <div class="summary-card green-side dashboard-clickable"
           onclick="openAllTrainerMetric('active')">
        <div class="num">${Number(summary.activeTrainers) || 0}</div>
        <div class="lbl">Active Trainers</div>
      </div>

      <div class="summary-card red-side dashboard-clickable"
           onclick="openAllTrainerMetric('inactive')">
        <div class="num">${Number(summary.nonActiveTrainers) || 0}</div>
        <div class="lbl">Non-Active Trainers</div>
      </div>
    `;
  }

  function combinedProjectsHtml(colleges, vendorRows, freelanceRows){
    return `
      <div class="all-projects-section" style="margin-bottom:18px;">
        <div class="section-header">
          <h3>LeSuccess Projects</h3>
        </div>

        ${collegeCardsHtml(colleges, true)}
      </div>

      <div class="all-projects-section" style="margin-bottom:18px;">
        <div class="section-header">
          <h3>Vendor Projects</h3>
        </div>

        ${externalProjectCardsHtml(vendorRows, 'vendor')}
      </div>

      <div class="all-projects-section">
        <div class="section-header">
          <h3>Freelancer Projects</h3>
        </div>

        ${externalProjectCardsHtml(freelanceRows, 'freelance')}
      </div>
    `;
  }

  function combinedTrainerRosterHtml(roster, vendorRows, freelanceRows){
    const map = {};

    // LeSuccess trainers
    (Array.isArray(roster) ? roster : []).forEach(t => {
      const name = String(
        t.fullName || t.username || ''
      ).trim();

      if(!name) return;

      const key = name.toLowerCase();

      if(!map[key]){
        map[key] = {
          name,
          college: t.collegeName || '—',
          status: !!t.active
        };
      }
    });

    // Vendor trainers
    (Array.isArray(vendorRows) ? vendorRows : []).forEach(r => {
      const name = String(r.trainerName || '').trim();
      if(!name) return;

      const key = name.toLowerCase();
      const status = externalProjectStatus_(r);

      if(!map[key]){
        map[key] = {
          name,
          college: r.collegeName || '—',
          status:
            status === 'Running' ||
            status === 'Upcoming' ||
            status === 'On Hold'
        };
      }else if(
        status === 'Running' ||
        status === 'Upcoming' ||
        status === 'On Hold'
      ){
        map[key].status = true;
      }
    });

    // Freelancer projects
    (Array.isArray(freelanceRows) ? freelanceRows : []).forEach(r => {
      const name = String(r.freelancerName || '').trim();
      if(!name) return;

      const key = name.toLowerCase();
      const status = externalProjectStatus_(r);

      if(!map[key]){
        map[key] = {
          name,
          college: r.collegeName || '—',
          status:
            status === 'Running' ||
            status === 'Upcoming' ||
            status === 'On Hold'
        };
      }else if(
        status === 'Running' ||
        status === 'Upcoming' ||
        status === 'On Hold'
      ){
        map[key].status = true;
      }
    });

    const trainers = Object.values(map);

    if(!trainers.length){
      return '<div class="empty-state">No trainers yet.</div>';
    }

    return `
      <table>
        <thead>
          <tr>
            <th>Trainer Name</th>
            <th>Project / College</th>
            <th>Status</th>
          </tr>
        </thead>

        <tbody>
          ${trainers.map(t => `
            <tr>
              <td>${escapeHtml(t.name)}</td>
              <td>${escapeHtml(t.college || '—')}</td>
              <td>
                <span class="status-pill ${
                  t.status
                    ? 'status-Running'
                    : 'status-Cancelled'
                }">
                  ${t.status ? 'Active' : 'Not Active'}
                </span>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  function openAllProjectMetric(filter){
    const dashboardPromise = callServer('getDashboardData');
    const vendorPromise = callServer('getVendorProjects');
    const freelancePromise = callServer('getFreelanceProjects');

    showLoading(true);

    Promise.all([
      dashboardPromise,
      vendorPromise,
      freelancePromise
    ]).then(([dashboard, vendorRows, freelanceRows]) => {
      showLoading(false);

      dashboard = dashboard || {};
      const colleges = Array.isArray(dashboard.colleges)
        ? dashboard.colleges
        : [];

      vendorRows = Array.isArray(vendorRows) ? vendorRows : [];
      freelanceRows = Array.isArray(freelanceRows) ? freelanceRows : [];

      let rows = [];

      if(filter === 'total' || filter === 'Running' ||
         filter === 'Upcoming' || filter === 'On Hold' ||
         filter === 'Completed'){

        const collegeItems = colleges
          .filter(c =>
            filter === 'total' ||
            String(c.status || '').trim() === filter
          )
          .map(c => ({
            type: 'LeSuccess',
            name: c.collegeName || 'Unnamed College',
            code: c.collegeCode || '',
            status: c.status || '',
            person: Array.isArray(c.trainerNames)
              ? c.trainerNames.join(', ')
              : 'Not Assigned'
          }));

        const vendorItems = vendorRows
          .filter(r =>
            filter === 'total' ||
            externalProjectStatus_(r) === filter
          )
          .map(r => ({
            type: 'Vendor',
            name: r.collegeName || 'Unnamed Project',
            code: r.projectID || '',
            status: externalProjectStatus_(r),
            person: r.trainerName || 'Not Assigned'
          }));

        const freelanceItems = freelanceRows
          .filter(r =>
            filter === 'total' ||
            externalProjectStatus_(r) === filter
          )
          .map(r => ({
            type: 'Freelancer',
            name: r.collegeName || 'Unnamed Project',
            code: r.projectID || '',
            status: externalProjectStatus_(r),
            person: r.freelancerName || 'Not Assigned'
          }));

        rows = [
          ...collegeItems,
          ...vendorItems,
          ...freelanceItems
        ];
      }

      document.getElementById('modalTitle').textContent =
        `All Projects — ${
          filter === 'total' ? 'Total Projects' : filter
        } (${rows.length})`;

      document.getElementById('modalFooter').innerHTML =
        '<button class="btn btn-outline" onclick="closeModal()">Close</button>';

      document.getElementById('modalBody').innerHTML = rows.length
        ? `
          <div style="overflow-x:auto;">
            <table class="drilldown-table">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Project / College</th>
                  <th>Status</th>
                  <th>Trainer / Freelancer</th>
                </tr>
              </thead>
              <tbody>
                ${rows.map(r => `
                  <tr>
                    <td><b>${escapeHtml(r.type)}</b></td>
                    <td>
                      ${escapeHtml(r.name)}
                      ${r.code
                        ? `<small style="display:block;color:var(--gray-500);">
                             ${escapeHtml(r.code)}
                           </small>`
                        : ''}
                    </td>
                    <td>
                      <span class="status-pill status-${statusClass(r.status)}">
                        ${escapeHtml(r.status)}
                      </span>
                    </td>
                    <td>${escapeHtml(r.person)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `
        : '<div class="drilldown-empty">No projects found in this category.</div>';

      document.getElementById('modalOverlay').classList.add('active');

    }).catch(err => {
      showLoading(false);
      handleError(err);
    });
  }

  function openAllTrainerMetric(filter){
    showLoading(true);

    Promise.all([
      callServer('getDashboardData'),
      callServer('getVendorProjects'),
      callServer('getFreelanceProjects')
    ]).then(([dashboard, vendorRows, freelanceRows]) => {
      showLoading(false);

      dashboard = dashboard || {};

      const roster = Array.isArray(dashboard.roster)
        ? dashboard.roster
        : [];

      vendorRows = Array.isArray(vendorRows) ? vendorRows : [];
      freelanceRows = Array.isArray(freelanceRows) ? freelanceRows : [];

      const map = {};

      roster.forEach(t => {
        const name = String(
          t.fullName || t.username || ''
        ).trim();

        if(!name) return;

        map[name.toLowerCase()] = {
          name,
          project: t.collegeName || '—',
          active: !!t.active
        };
      });

      [...vendorRows, ...freelanceRows].forEach(r => {
        const isVendor = vendorRows.includes(r);
        const name = String(
          isVendor ? r.trainerName : r.freelancerName
        ).trim();

        if(!name) return;

        const key = name.toLowerCase();
        const s = externalProjectStatus_(r);
        const active =
          s === 'Running' ||
          s === 'Upcoming' ||
          s === 'On Hold';

        if(!map[key]){
          map[key] = {
            name,
            project: r.collegeName || '—',
            active
          };
        }else if(active){
          map[key].active = true;
        }
      });

      let trainers = Object.values(map);

      if(filter === 'active'){
        trainers = trainers.filter(t => t.active);
      }else if(filter === 'inactive'){
        trainers = trainers.filter(t => !t.active);
      }

      document.getElementById('modalTitle').textContent =
        `All Projects — ${
          filter === 'total'
            ? 'Total Trainers'
            : filter === 'active'
            ? 'Active Trainers'
            : 'Non-Active Trainers'
        } (${trainers.length})`;

      document.getElementById('modalFooter').innerHTML =
        '<button class="btn btn-outline" onclick="closeModal()">Close</button>';

      document.getElementById('modalBody').innerHTML = trainers.length
        ? `
          <div style="overflow-x:auto;">
            <table class="drilldown-table">
              <thead>
                <tr>
                  <th>Trainer / Freelancer</th>
                  <th>Project / College</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                ${trainers.map(t => `
                  <tr>
                    <td><b>${escapeHtml(t.name)}</b></td>
                    <td>${escapeHtml(t.project)}</td>
                    <td>
                      <span class="status-pill ${
                        t.active
                          ? 'status-Running'
                          : 'status-Cancelled'
                      }">
                        ${t.active ? 'Active' : 'Not Active'}
                      </span>
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `
        : '<div class="drilldown-empty">No trainers found.</div>';

      document.getElementById('modalOverlay').classList.add('active');

    }).catch(err => {
      showLoading(false);
      handleError(err);
    });
  }

  // ---------- LESUCCESS PROJECTS TAB ----------
  function renderLeSuccessTab(){
    const area = document.getElementById('dashTabContent');
    area.innerHTML = '<div class="empty-state">Loading…</div>';
    showLoading(true);

    callServer('getDashboardData').then(data => {
      showLoading(false);

      data = data || {};
      const summary = data.summary || {};
      const colleges = Array.isArray(data.colleges) ? data.colleges : [];
      const roster = Array.isArray(data.roster) ? data.roster : [];

      collegesCache = colleges;
      window._trainerRoster = roster;

      area.innerHTML = `
        <div class="subsection-label">Project Status</div>
        <div class="summary-grid" id="statusCardsArea"></div>

        <div class="subsection-label">Trainers</div>
        <div class="summary-grid" id="trainerCardsArea"
             style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));max-width:600px;"></div>

        <div class="dashboard-split-columns">
          <section class="dashboard-column dashboard-colleges-column">
            <div class="dashboard-column-header">
              <h3>Colleges</h3>
            </div>
            <div id="collegeTableArea" class="dashboard-column-scroll"></div>
          </section>

          <section class="dashboard-column dashboard-trainers-column">
            <div class="dashboard-column-header">
              <h3>Trainer Roster</h3>
            </div>
            <div id="trainerTableArea" class="dashboard-column-scroll"></div>
          </section>
        </div>
      `;

      document.getElementById('statusCardsArea').innerHTML = `
        <div class="summary-card dashboard-clickable"
             onclick="openDashboardCollegeMetric('total','Total Colleges')">
          <div class="num">${Number(summary.totalColleges) || 0}</div>
          <div class="lbl">Total Colleges</div>
        </div>

        <div class="summary-card green-side dashboard-clickable"
             onclick="openDashboardCollegeMetric('Running','Running Colleges')">
          <div class="num">${Number(summary.running) || 0}</div>
          <div class="lbl">Running</div>
        </div>

        <div class="summary-card blue-side dashboard-clickable"
             onclick="openDashboardCollegeMetric('Upcoming','Upcoming Colleges')">
          <div class="num">${Number(summary.upcoming) || 0}</div>
          <div class="lbl">Upcoming</div>
        </div>

        <div class="summary-card amber-side dashboard-clickable"
             onclick="openDashboardCollegeMetric('On Hold','On Hold Colleges')">
          <div class="num">${Number(summary.onHold) || 0}</div>
          <div class="lbl">On Hold</div>
        </div>

        <div class="summary-card gray-side dashboard-clickable"
             onclick="openDashboardCollegeMetric('Completed','Completed Colleges')">
          <div class="num">${Number(summary.completed) || 0}</div>
          <div class="lbl">Completed</div>
        </div>
      `;

      document.getElementById('trainerCardsArea').innerHTML = `
        <div class="summary-card dashboard-clickable"
             onclick="openDashboardTrainerMetric('total','Total Trainers')">
          <div class="num">${Number(summary.totalTrainers) || 0}</div>
          <div class="lbl">Total Trainers</div>
        </div>

        <div class="summary-card green-side dashboard-clickable"
             onclick="openDashboardTrainerMetric('active','Active Trainers')">
          <div class="num">${Number(summary.activeTrainers) || 0}</div>
          <div class="lbl">Active Trainers</div>
        </div>

        <div class="summary-card red-side dashboard-clickable"
             onclick="openDashboardTrainerMetric('inactive','Non-Active Trainers')">
          <div class="num">${Number(summary.nonActiveTrainers) || 0}</div>
          <div class="lbl">Non-Active Trainers</div>
        </div>
        <div class="summary-card amber-side dashboard-clickable"
             onclick="openLeaveDashboardCard()">
          <div class="num" id="adminLeaveCardCount">0</div>
          <div class="lbl">Approved Leave Days</div>
        </div>
        ${isAdminUser() ? `<div class="summary-card red-side dashboard-clickable"
             onclick="navigate('leave')">
          <div class="num" id="adminPendingLeaveCount">0</div>
          <div class="lbl">Pending Leave Requests</div>
        </div>` : ''}
      `;

      if(isAdminUser() || isTeamLeaderUser() || isReportingManagerUser()) loadAdminLeaveCard();
      if(isAdminUser()) loadAdminPendingLeaveCount();

      document.getElementById('collegeTableArea').innerHTML =
        collegeCardsHtml(colleges, true);

      document.getElementById('trainerTableArea').innerHTML =
        trainerTableHtml(roster);

    }).catch(err => {
      showLoading(false);
      handleError(err);
      if(area){
        area.innerHTML =
          '<div class="empty-state">Could not load dashboard data. Please refresh and try again.</div>';
      }
    });
  }

  function openDashboardCollegeMetric(filter, title){
    const all = Array.isArray(collegesCache) ? collegesCache : [];
    const wanted = String(filter || '').trim().toLowerCase();

    const colleges = wanted === 'total'
      ? all.slice()
      : all.filter(c => String(c.status || '').trim().toLowerCase() === wanted);

    document.getElementById('modalTitle').textContent =
      `${title} (${colleges.length})`;

    document.getElementById('modalFooter').innerHTML =
      '<button class="btn btn-outline" onclick="closeModal()">Close</button>';

    document.getElementById('modalOverlay').classList.add('active');

    if(!colleges.length){
      document.getElementById('modalBody').innerHTML =
        '<div class="drilldown-empty">No colleges found in this category.</div>';
      return;
    }

    document.getElementById('modalBody').innerHTML = `
      <div class="modal-college-list">
        ${colleges.map(c => {
          const progress = Math.max(0, Math.min(100, Number(c.progressPercent) || 0));
          const trainers = Array.isArray(c.trainerNames) && c.trainerNames.length
            ? c.trainerNames.map(escapeHtml).join(', ')
            : 'Not Assigned';

          return `
            <div class="modal-college-card">
              <div class="modal-college-head">
                <div>
                  <div class="modal-college-code">${escapeHtml(c.collegeCode || '')}</div>
                  <div class="modal-college-name">${escapeHtml(c.collegeName || 'Unnamed College')}</div>
                </div>
                <span class="status-pill status-${statusClass(c.status)}">
                  ${escapeHtml(c.status || 'Unknown')}
                </span>
              </div>

              <div class="modal-detail-grid">
                <div><span>Students</span><b>${Number(c.studentStrength) || 0}</b></div>
                <div><span>Program Days</span><b>${Number(c.totalPlannedDays) || 0}</b></div>
                <div><span>Completed</span><b>${Number(c.completedDays) || 0}</b></div>
                <div><span>Remaining</span><b>${Number(c.remainingDays) || 0}</b></div>
                <div><span>Attendance</span><b>${Number(c.avgAttendance) || 0}%</b></div>
                <div><span>Start Date</span><b>${fmtDate(c.startDate)}</b></div>
                <div><span>End Date</span><b>${fmtDate(c.endDate)}</b></div>
                <div><span>Trainers</span><b>${Number(c.trainerCount) || 0}</b></div>
              </div>

              <div class="modal-progress">
                <div class="modal-progress-label">
                  <span>Training Progress</span><b>${progress}%</b>
                </div>
                <div class="progress-track">
                  <div class="progress-fill" style="width:${progress}%;"></div>
                </div>
              </div>

              <div class="modal-info-row">
                <strong>Assigned Trainers:</strong>
                <span>${trainers}</span>
              </div>

              ${c.notes ? `
                <div class="modal-info-row">
                  <strong>Notes:</strong>
                  <span>${escapeHtml(c.notes)}</span>
                </div>` : ''}

              <button class="btn btn-primary btn-sm"
                      style="margin-top:12px;"
                      onclick="closeModal(); navigate('collegeProfile','${escapeHtml(c.collegeCode || '')}')">
                View Full College Profile
              </button>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  function openDashboardTrainerMetric(filter, title){
    const roster = Array.isArray(window._trainerRoster) ? window._trainerRoster : [];
    let trainers = roster.slice();

    if(filter === 'active') trainers = trainers.filter(t => t.active);
    if(filter === 'inactive') trainers = trainers.filter(t => !t.active);

    document.getElementById('modalTitle').textContent = title + ' (' + trainers.length + ')';
    document.getElementById('modalFooter').innerHTML =
      '<button class="btn btn-outline" onclick="closeModal()">Close</button>';
    document.getElementById('modalOverlay').classList.add('active');

    if(trainers.length === 0){
      document.getElementById('modalBody').innerHTML =
        '<div class="drilldown-empty">No trainers found in this category.</div>';
      return;
    }

    const rows = trainers.map(t => `
      <tr>
        <td><b>${escapeHtml(t.fullName || t.username || 'Unnamed')}</b></td>
        <td>${t.active ? escapeHtml(t.collegeName || '—') : 'Not Assigned'}</td>
        <td>${t.active ? (Number(t.totalDays) || 0) + ' days' : '—'}</td>
        <td>${t.active ? fmtDate(t.fromDate) + ' – ' + fmtDate(t.toDate) : '—'}</td>
      </tr>
    `).join('');

    document.getElementById('modalBody').innerHTML = `
      <div style="overflow-x:auto;">
        <table class="drilldown-table">
          <thead>
            <tr>
              <th>Trainer Name</th>
              <th>College</th>
              <th>Program Days</th>
              <th>Assignment Period</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  // Plain, always-visible Colleges table: College, Status, Total Program
  // Days, Completed, Trainers. Built fresh from the server every time this
  // tab renders — including right after a new college project is created —
  // so there's no separate cache/modal step that can go stale or get stuck.
  function collegeTableHtml(colleges){
    return collegeCardsHtml(colleges, true);
  }

  function trainerTableHtml(roster){
    if(!Array.isArray(roster) || roster.length === 0) return '<div class="empty-state">No trainers yet. Add them from User Management.</div>';
    return `<table><thead><tr><th>Trainer Name</th><th>College</th><th>Status</th></tr></thead>
      <tbody>${roster.map(t => `<tr>
        <td>${escapeHtml(t.fullName || t.username || 'Unnamed')}</td>
        <td>${t.active ? escapeHtml(t.collegeName || '') : 'Not Assigned'}</td>
        <td><span class="status-pill ${t.active ? 'status-Running' : 'status-Cancelled'}">${t.active ? 'Active' : 'Not Active'}</span></td>
      </tr>`).join('')}</tbody></table>`;
  }

  function collegeCardsHtml(colleges){
    if(!Array.isArray(colleges) || colleges.length === 0){
      return '<div class="empty-state">No colleges yet. Create your first project to get started.</div>';
    }

    return colleges.map(c => `
      <div class="college-card" onclick="navigate('collegeProfile','${escapeHtml(c.collegeCode || '')}')">
        <div class="cc-head">
          ${c.logoURL ? `<img src="${escapeHtml(c.logoURL)}" alt="College Logo" onerror="this.style.display='none';">` : ''}

          <div class="cc-college-info">
            <div class="cc-code">${escapeHtml(c.collegeCode || '')}</div>
            <div class="cc-name">${escapeHtml(c.collegeName || '')}</div>

            <div style="margin-top:7px;">
              <span class="status-pill status-${statusClass(c.status)}">
                ${escapeHtml(c.status || '')}
              </span>
            </div>

            <div>
              <span class="cc-total-days">
                Total Program Days: ${Number(c.totalPlannedDays) || 0}
              </span>
            </div>
          </div>

          <div class="cc-trainer-count">
            <b>${Number(c.trainerCount) || 0}</b>
            <span>Trainer(s)</span>
          </div>
        </div>
      </div>
    `).join('');
  }

  // ---------- VENDOR PROJECTS TAB ----------
  let vendorRowsCache = [];
  function externalProjectStatus_(row){
    const raw = String(row.status || row.projectStatus || '').trim().toLowerCase();

    if(raw === 'running' || raw === 'upcoming' || raw === 'on hold' ||
       raw === 'completed' || raw === 'cancelled'){
      return raw === 'on hold' ? 'On Hold' : raw.charAt(0).toUpperCase() + raw.slice(1);
    }

    // Existing Vendor/Freelance rows do not necessarily have a Status column.
    // Treat a project with planned days as Running until a status is explicitly stored.
    return Number(row.days) > 0 ? 'Running' : 'Completed';
  }

  function externalProjectSummary_(rows, peopleKey){
    rows = Array.isArray(rows) ? rows : [];

    const statuses = rows.map(externalProjectStatus_);
    const people = [...new Set(
      rows.map(r => String(r[peopleKey] || '').trim()).filter(Boolean)
    )];

    const running = statuses.filter(s => s === 'Running').length;
    const upcoming = statuses.filter(s => s === 'Upcoming').length;
    const onHold = statuses.filter(s => s === 'On Hold').length;
    const completed = statuses.filter(s => s === 'Completed').length;

    // For these flat trackers, "active trainer" means a person currently
    // attached to at least one project. Non-active means no current assignment.
    const activePeople = people.length;
    const nonActivePeople = 0;

    return {
      totalProjects: rows.length,
      running,
      upcoming,
      onHold,
      completed,
      totalPeople: people.length,
      activePeople,
      nonActivePeople
    };
  }

  function externalProjectCardsHtml(rows, type){
    rows = Array.isArray(rows) ? rows : [];

    if(!rows.length){
      return '<div class="empty-state">No projects yet. Create your first project to get started.</div>';
    }

    const isVendor = type === 'vendor';
    const personKey = isVendor ? 'trainerName' : 'freelancerName';
    const personLabel = isVendor ? 'Trainer' : 'Freelancer';

    return `
      <div class="external-project-grid">
        ${rows.map(r => {
          const status = externalProjectStatus_(r);
          const logo = r.collegeLogo
            ? `<img class="external-project-logo"
                    src="${escapeHtml(r.collegeLogo)}"
                    alt="College logo"
                    onerror="this.style.display='none';">`
            : `<div class="external-project-logo-placeholder">🏫</div>`;

          return `
            <div class="external-project-card ${isApproverUser() ? '' : 'view-only-card'}"
                 ${isApproverUser()
                   ? `onclick="${isAdminUser()
                       ? (isVendor ? `openEditVendorProject('${escapeHtml(r.projectID || '')}')` : `openEditFreelanceProject('${escapeHtml(r.projectID || '')}')`)
                       : `openReassignExternalProject('${type}','${escapeHtml(r.projectID || '')}')`}"`
                   : ''}>
              <div class="external-project-head">
                <div class="external-project-title">
                  ${logo}
                  <div style="min-width:0;">
                    <div class="external-project-name">
                      ${escapeHtml(r.collegeName || 'Unnamed College')}
                    </div>
                    <div class="external-project-meta">
                      ${escapeHtml(isVendor ? (r.vendor || 'Vendor Project') : (r.vendor || 'Freelance Project'))}
                    </div>
                  </div>
                </div>
                <span class="status-pill status-${statusClass(status)}">
                  ${escapeHtml(status)}
                </span>
              </div>

              <div class="external-project-details">
                <div class="external-project-detail">
                  <span>${personLabel}</span>
                  <b>${escapeHtml(r[personKey] || 'Not Assigned')}</b>
                </div>
                <div class="external-project-detail">
                  <span>Program Days</span>
                  <b>${Number(r.days) || 0}</b>
                </div>
                <div class="external-project-detail">
                  <span>Category</span>
                  <b>${escapeHtml(r.category || '—')}</b>
                </div>
                <div class="external-project-detail">
                  <span>Location</span>
                  <b>${escapeHtml(r.location || '—')}</b>
                </div>
              </div>

              <div class="external-project-footer" style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;">
                <span>Approved training days</span>
                <b>${Number(r.completedDays) || 0} / ${Number(r.plannedDays) || Number(r.days) || 0} (${Number(r.progressPercent) || 0}%)</b>
                <small>${Number(r.pendingUpdates) || 0} pending approval(s)</small>
              </div>
              ${r.comments ? `
                <div class="external-project-footer">
                  <span>Remarks</span>
                  <b>${escapeHtml(r.comments)}</b>
                </div>
              ` : ''}
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  // ---------- VENDOR PROJECTS TAB ----------
  function renderVendorTab(){
    renderExternalProjectTab('vendor');
  }

  function renderFreelanceTab(){
    renderExternalProjectTab('freelance');
  }

  function renderExternalProjectTab(type){
    const area = document.getElementById('dashTabContent');
    const isVendor = type === 'vendor';
    const title = isVendor ? 'Vendor Projects' : 'Freelancer Projects';
    const addAction = isVendor
      ? 'openAddVendorProject()'
      : 'openAddFreelanceProject()';
    const endpoint = isVendor
      ? 'getVendorProjects'
      : 'getFreelanceProjects';

    const peopleKey = isVendor
      ? 'trainerName'
      : 'freelancerName';

    area.innerHTML = `
      <div class="subsection-label">Project Status</div>
      <div class="summary-grid" id="externalStatusCards">
        ${externalSummaryCardsHtml({
          totalProjects: 0,
          running: 0,
          upcoming: 0,
          onHold: 0,
          completed: 0
        })}
      </div>

      <div class="subsection-label" style="margin-top:24px;">
        Trainers
      </div>

      <div class="summary-grid"
           id="externalTrainerCards"
           style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));max-width:600px;">
        ${externalTrainerCardsHtml({
          totalPeople: 0,
          activePeople: 0,
          nonActivePeople: 0
        })}
      </div>

      <div class="dashboard-split-columns" style="margin-top:26px;">

        <section class="dashboard-column">
          <div class="dashboard-column-header">
            <h3>${title}</h3>
          </div>

          <div id="externalProjectCardsArea"
               class="dashboard-column-scroll">
            <div class="empty-state">Loading projects…</div>
          </div>
        </section>

        <section class="dashboard-column">
          <div class="dashboard-column-header">
            <h3>Trainer Roster</h3>
          </div>

          <div id="externalTrainerRosterArea"
               class="dashboard-column-scroll">
            <div class="empty-state">Loading trainers…</div>
          </div>
        </section>

      </div>
    `;

    showLoading(true);

    callServer(endpoint).then(rows => {
      showLoading(false);

      rows = Array.isArray(rows) ? rows : [];

      if(isVendor){
        vendorRowsCache = rows;
      }else{
        freelanceRowsCache = rows;
      }

      const summary = externalProjectSummary_(rows, peopleKey);

      const statusEl =
        document.getElementById('externalStatusCards');

      const trainerEl =
        document.getElementById('externalTrainerCards');

      const cardsEl =
        document.getElementById('externalProjectCardsArea');

      const rosterEl =
        document.getElementById('externalTrainerRosterArea');

      if(statusEl){
        statusEl.innerHTML =
          externalSummaryCardsHtml(summary);
      }

      if(trainerEl){
        trainerEl.innerHTML =
          externalTrainerCardsHtml(summary);
      }

      if(cardsEl){
        cardsEl.innerHTML =
          externalProjectCardsHtml(rows, type);
      }

      if(rosterEl){
        rosterEl.innerHTML =
          externalTrainerRosterHtml(rows, peopleKey, isVendor);
      }

    }).catch(err => {
      showLoading(false);
      console.error('External project load error:', err);

      const msg = escapeHtml(
        err && err.message
          ? err.message
          : String(err)
      );

      const cardsEl =
        document.getElementById('externalProjectCardsArea');

      const rosterEl =
        document.getElementById('externalTrainerRosterArea');

      if(cardsEl){
        cardsEl.innerHTML = `
          <div class="empty-state">
            Unable to load ${escapeHtml(title)}.
            <br><small>${msg}</small>
          </div>
        `;
      }

      if(rosterEl){
        rosterEl.innerHTML = `
          <div class="empty-state">
            Unable to load Trainer Roster.
            <br><small>${msg}</small>
          </div>
        `;
      }
    });
  }

  function externalTrainerRosterHtml(rows, peopleKey, isVendor){
    rows = Array.isArray(rows) ? rows : [];

    const map = {};

    rows.forEach(r => {
      const name = String(r[peopleKey] || '').trim();

      if(!name) return;

      const key = name.toLowerCase();
      const status = externalProjectStatus_(r);

      if(!map[key]){
        map[key] = {
          name,
          project: r.collegeName || '—',
          active:
            status === 'Running' ||
            status === 'Upcoming' ||
            status === 'On Hold'
        };
      }else if(
        status === 'Running' ||
        status === 'Upcoming' ||
        status === 'On Hold'
      ){
        map[key].active = true;
      }
    });

    const people = Object.values(map);

    if(!people.length){
      return `
        <div class="empty-state">
          No ${isVendor ? 'trainers' : 'freelancers'} assigned yet.
        </div>
      `;
    }

    const personLabel = isVendor
      ? 'Trainer Name'
      : 'Freelancer Name';

    return `
      <table>
        <thead>
          <tr>
            <th>${personLabel}</th>
            <th>Project / College</th>
            <th>Status</th>
          </tr>
        </thead>

        <tbody>
          ${people.map(p => `
            <tr>
              <td>${escapeHtml(p.name)}</td>
              <td>${escapeHtml(p.project)}</td>
              <td>
                <span class="status-pill ${
                  p.active
                    ? 'status-Running'
                    : 'status-Cancelled'
                }">
                  ${p.active ? 'Active' : 'Not Active'}
                </span>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  function externalSummaryCardsHtml(summary){
    return `
      <div class="summary-card dashboard-clickable"
           onclick="externalMetricClick('total')">
        <div class="num">${Number(summary.totalProjects) || 0}</div>
        <div class="lbl">Total Projects</div>
      </div>

      <div class="summary-card green-side dashboard-clickable"
           onclick="externalMetricClick('Running')">
        <div class="num">${Number(summary.running) || 0}</div>
        <div class="lbl">Running</div>
      </div>

      <div class="summary-card blue-side dashboard-clickable"
           onclick="externalMetricClick('Upcoming')">
        <div class="num">${Number(summary.upcoming) || 0}</div>
        <div class="lbl">Upcoming</div>
      </div>

      <div class="summary-card amber-side dashboard-clickable"
           onclick="externalMetricClick('On Hold')">
        <div class="num">${Number(summary.onHold) || 0}</div>
        <div class="lbl">On Hold</div>
      </div>

      <div class="summary-card gray-side dashboard-clickable"
           onclick="externalMetricClick('Completed')">
        <div class="num">${Number(summary.completed) || 0}</div>
        <div class="lbl">Completed</div>
      </div>
    `;
  }

  function externalTrainerCardsHtml(summary){
    return `
      <div class="summary-card dashboard-clickable"
           onclick="externalPeopleMetricClick('totalPeople')">
        <div class="num">${Number(summary.totalPeople) || 0}</div>
        <div class="lbl">Total Trainers</div>
      </div>

      <div class="summary-card green-side dashboard-clickable"
           onclick="externalPeopleMetricClick('activePeople')">
        <div class="num">${Number(summary.activePeople) || 0}</div>
        <div class="lbl">Active Trainers</div>
      </div>

      <div class="summary-card red-side dashboard-clickable"
           onclick="externalPeopleMetricClick('nonActivePeople')">
        <div class="num">${Number(summary.nonActivePeople) || 0}</div>
        <div class="lbl">Non-Active Trainers</div>
      </div>
    `;
  }

  function externalMetricClick(status){
    const isVendor = dashboardTab === 'vendor';
    const rows = isVendor
      ? (Array.isArray(vendorRowsCache) ? vendorRowsCache : [])
      : (Array.isArray(freelanceRowsCache) ? freelanceRowsCache : []);

    const filtered = status === 'total'
      ? rows
      : rows.filter(r => externalProjectStatus_(r) === status);

    const title = isVendor ? 'Vendor Projects' : 'Freelancer Projects';

    document.getElementById('modalTitle').textContent =
      title + ' — ' + (status === 'total' ? 'All Projects' : status);

    document.getElementById('modalBody').innerHTML =
      filtered.length
        ? externalProjectCardsHtml(filtered, isVendor ? 'vendor' : 'freelance')
        : '<div class="drilldown-empty">No projects found in this category.</div>';

    document.getElementById('modalFooter').innerHTML =
      '<button class="btn btn-outline" onclick="closeModal()">Close</button>';

    document.getElementById('modalOverlay').classList.add('active');
  }

  function externalPeopleMetricClick(metric){
    const isVendor = dashboardTab === 'vendor';
    const rows = isVendor
      ? (Array.isArray(vendorRowsCache) ? vendorRowsCache : [])
      : (Array.isArray(freelanceRowsCache) ? freelanceRowsCache : []);

    const personKey = isVendor ? 'trainerName' : 'freelancerName';
    const personLabel = isVendor ? 'Trainer' : 'Freelancer';

    const peopleMap = {};
    rows.forEach(row => {
      const name = String(row[personKey] || '').trim();
      if(!name) return;

      if(!peopleMap[name]){
        peopleMap[name] = {
          name,
          projects: []
        };
      }

      peopleMap[name].projects.push(row);
    });

    const people = Object.values(peopleMap);

    let selected = people;

    if(metric === 'activePeople'){
      selected = people.filter(p =>
        p.projects.some(r => {
          const s = externalProjectStatus_(r);
          return s === 'Running' || s === 'Upcoming' || s === 'On Hold';
        })
      );
    }else if(metric === 'nonActivePeople'){
      selected = people.filter(p =>
        !p.projects.some(r => {
          const s = externalProjectStatus_(r);
          return s === 'Running' || s === 'Upcoming' || s === 'On Hold';
        })
      );
    }

    const titleMap = {
      totalPeople: `Total ${personLabel}s`,
      activePeople: `Active ${personLabel}s`,
      nonActivePeople: `Non-Active ${personLabel}s`
    };

    document.getElementById('modalTitle').textContent =
      `${isVendor ? 'Vendor' : 'Freelancer'} Projects — ${titleMap[metric] || personLabel + 's'}`;

    if(!selected.length){
      document.getElementById('modalBody').innerHTML =
        '<div class="drilldown-empty">No trainers found in this category.</div>';
    }else{
      document.getElementById('modalBody').innerHTML = `
        <div class="external-people-popup">
          ${selected.map(person => `
            <div class="external-person-popup-card">
              <div class="external-person-popup-head">
                <div>
                  <div class="external-person-popup-name">
                    ${escapeHtml(person.name)}
                  </div>
                  <div class="external-person-popup-role">
                    ${escapeHtml(personLabel)}
                  </div>
                </div>
                <span class="status-pill status-Running">
                  ${person.projects.length} Project${person.projects.length === 1 ? '' : 's'}
                </span>
              </div>

              <div class="external-person-projects">
                ${person.projects.map(project => {
                  const status = externalProjectStatus_(project);
                  const logo = project.collegeLogo
                    ? `<img src="${escapeHtml(project.collegeLogo)}"
                            alt="College logo"
                            onerror="this.style.display='none';">`
                    : '';

                  return `
                    <div class="external-person-project-row">
                      ${logo ? `<div class="external-person-logo">${logo}</div>` : ''}
                      <div class="external-person-project-main">
                        <b>${escapeHtml(project.collegeName || 'Unnamed College')}</b>
                        <span>
                          ${escapeHtml(project.category || '—')}
                          · ${Number(project.days) || 0} days
                        </span>
                      </div>
                      <span class="status-pill status-${statusClass(status)}">
                        ${escapeHtml(status)}
                      </span>
                    </div>
                  `;
                }).join('')}
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }

    document.getElementById('modalFooter').innerHTML =
      '<button class="btn btn-outline" onclick="closeModal()">Close</button>';

    document.getElementById('modalOverlay').classList.add('active');
  }

  function vendorTrainerOptionsHtml(selectedName){
    const list = window._vendorTrainerOptions || [];
    return `<option value="">Select trainer…</option>` + list.map(t =>
      `<option value="${escapeHtml(t.username)}" ${t.username === selectedName || t.fullName === selectedName ? 'selected' : ''}>${escapeHtml(t.fullName)}</option>`).join('')
      + `<option value="__other__" ${selectedName && !list.some(t => t.fullName === selectedName) ? 'selected' : ''}>Other / Type manually…</option>`;
  }
  function loadVendorTrainerOptionsThen(cb){
    if(window._vendorTrainerOptions){ cb(); return; }
    callServer('getAllTrainerUsersForDropdown').then(list => { window._vendorTrainerOptions = list; cb(); });
  }
  function onVendorTrainerSelectChange(sel){
    const manual = document.getElementById('vpTrainerManual');
    if(sel.value === '__other__'){ manual.classList.remove('hidden'); manual.focus(); }
    else { manual.classList.add('hidden'); }
  }
  function openAddVendorProject(){
    if(!isAdminUser()){ showToast('Only Admin can modify projects.', true); return; }
    document.getElementById('modalTitle').textContent = 'Add Vendor Project';
    document.getElementById('modalBody').innerHTML = `
      <div class="form-row">
        <div class="field"><label>Vendor</label><input id="vpVendor"></div>
        <div class="field">
          <label>College Name</label>
          <input id="vpCollege" oninput="previewCollegeLogoByName(this.value,'vpLogoPreview')">
          <div id="vpLogoPreview" class="logo-preview-inline"></div>
        </div>
        <div class="field">
          <label>Project Logo URL</label>
          <input id="vpLogoURL" placeholder="https://example.com/logo.png"
                 oninput="previewImageUrl(this.value,'vpManualLogoPreview')">
          <div id="vpManualLogoPreview" class="logo-preview-inline"></div>
        </div>
      </div>
      <div class="form-row">
        <div class="field"><label>Trainer</label>
          <select id="vpTrainerSelect" onchange="onVendorTrainerSelectChange(this)">Loading…</select>
          <input id="vpTrainerManual" class="hidden" placeholder="Type trainer name" style="margin-top:8px;">
        </div>
        <div class="field"><label>Days of Program</label><input id="vpDays" type="number"></div>
        <div class="field"><label>Start Date</label><input id="vpStartDate" type="date"></div>
        <div class="field"><label>End Date</label><input id="vpEndDate" type="date"></div>
        <div class="field"><label>Start Time (optional)</label><input id="vpStartTime" type="time" ></div>
        <div class="field"><label>End Time (optional)</label><input id="vpEndTime" type="time" ></div>
        <div class="field"><label>Batch / Slot</label><input id="vpBatch"  placeholder="e.g. Batch A"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>Category</label><input id="vpCategory"></div>
        <div class="field">
          <label>Project Status</label>
          <select id="vpStatus">
            <option value="Running">Running</option>
            <option value="Upcoming">Upcoming</option>
            <option value="On Hold">On Hold</option>
            <option value="Completed">Completed</option>
            <option value="Cancelled">Cancelled</option>
          </select>
        </div>
      </div>
      <div class="field"><label>Location</label><input id="vpLocation" placeholder="e.g. Chennai"></div>
      <div class="field"><label>Comments/Remarks</label><textarea id="vpComments" rows="2"></textarea></div>
    `;
    document.getElementById('modalFooter').innerHTML = `
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-red" onclick="submitVendorProject()">Add</button>
    `;
    document.getElementById('modalOverlay').classList.add('active');
    loadVendorTrainerOptionsThen(() => {
      document.getElementById('vpTrainerSelect').innerHTML = vendorTrainerOptionsHtml('');
      setupExternalBookingPreview('vp','vendor','');
    });
  }
  function readVendorTrainerName(){
    const sel = document.getElementById('vpTrainerSelect');
    if(sel.value === '__other__') return document.getElementById('vpTrainerManual').value.trim();
    return (window._vendorTrainerOptions || []).find(x => x.username === sel.value)?.fullName || sel.value;
  }
  function submitVendorProject(){
    const payload = {
      vendor: document.getElementById('vpVendor').value.trim(),
      collegeName: document.getElementById('vpCollege').value.trim(),
      logoURL: document.getElementById('vpLogoURL').value.trim(),
      trainerUsername: ['__other__'].includes(document.getElementById('vpTrainerSelect').value) ? '' : (document.getElementById('vpTrainerSelect').value || ''),
      trainerName: readVendorTrainerName(),
      days: Number(document.getElementById('vpDays').value) || 0,
      startDate: document.getElementById('vpStartDate').value,
      endDate: document.getElementById('vpEndDate').value,
      startTime: document.getElementById('vpStartTime').value,
      endTime: document.getElementById('vpEndTime').value,
      batch: document.getElementById('vpBatch').value.trim(),
      category: document.getElementById('vpCategory').value.trim(),
      status: document.getElementById('vpStatus').value,
      location: document.getElementById('vpLocation').value.trim(),
      comments: document.getElementById('vpComments').value.trim(),
      createdBy: currentUser.username
    };
    if(!isAdminUser()){ showToast('Only Admin can create projects.', true); return; }
    if(!payload.vendor || !payload.collegeName){ showToast('Vendor and College Name are required.', true); return; }
    assignmentWriteWithSchedule('createVendorProject', {...payload, projectType:'vendor', projectId:payload.projectID || ''}, () => {
      showToast('Vendor project added.'); closeModal(); renderVendorTab();
    });
  }
  function openEditVendorProject(id){
    if(!isAdminUser()){ showToast('Only Admin can modify projects.', true); return; }
    const r = vendorRowsCache.find(x => x.projectID === id);
    if(!r) return;
    document.getElementById('modalTitle').textContent = 'Edit Vendor Project';
    document.getElementById('modalBody').innerHTML = `
      <div class="form-row">
        <div class="field"><label>Vendor</label><input id="vpVendor" value="${escapeHtml(r.vendor)}"></div>
        <div class="field">
          <label>College Name</label>
          <input id="vpCollege" value="${escapeHtml(r.collegeName)}"
                 oninput="previewCollegeLogoByName(this.value,'vpLogoPreview')">
          <div id="vpLogoPreview" class="logo-preview-inline"></div>
        </div>
        <div class="field">
          <label>Project Logo URL</label>
          <input id="vpLogoURL" value="${escapeHtml(r.logoURL || '')}"
                 placeholder="https://example.com/logo.png"
                 oninput="previewImageUrl(this.value,'vpManualLogoPreview')">
          <div id="vpManualLogoPreview" class="logo-preview-inline"></div>
        </div>
      </div>
      <div class="form-row">
        <div class="field"><label>Trainer</label>
          <select id="vpTrainerSelect" onchange="onVendorTrainerSelectChange(this)">Loading…</select>
          <input id="vpTrainerManual" class="hidden" placeholder="Type trainer name" value="${escapeHtml(r.trainerName)}" style="margin-top:8px;">
        </div>
        <div class="field"><label>Days of Program</label><input id="vpDays" type="number" value="${escapeHtml(r.days)}"></div>
        <div class="field"><label>Start Date</label><input id="vpStartDate" type="date" value="${escapeHtml(r.startDate || '')}"></div>
        <div class="field"><label>End Date</label><input id="vpEndDate" type="date" value="${escapeHtml(r.endDate || '')}"></div>
        <div class="field"><label>Start Time (optional)</label><input id="vpStartTime" type="time" value="${escapeHtml(r.startTime || '')}"></div>
        <div class="field"><label>End Time (optional)</label><input id="vpEndTime" type="time" value="${escapeHtml(r.endTime || '')}"></div>
        <div class="field"><label>Batch / Slot</label><input id="vpBatch" value="${escapeHtml(r.batch || '')}" placeholder="e.g. Batch A"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>Category</label><input id="vpCategory" value="${escapeHtml(r.category)}"></div>
        <div class="field">
          <label>Project Status</label>
          <select id="vpStatus">
            ${['Running','Upcoming','On Hold','Completed','Cancelled'].map(s =>
              `<option value="${s}" ${String(r.status || 'Running') === s ? 'selected' : ''}>${s}</option>`
            ).join('')}
          </select>
        </div>
      </div>
      <div class="field"><label>Location</label><input id="vpLocation" value="${escapeHtml(r.location || '')}"></div>
      <div class="field"><label>Comments/Remarks</label><textarea id="vpComments" rows="2">${escapeHtml(r.comments || '')}</textarea></div>
    `;
    document.getElementById('modalFooter').innerHTML = `
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-red" onclick="submitEditVendorProject('${id}')">Save Changes</button>
    `;
    document.getElementById('modalOverlay').classList.add('active');
    loadVendorTrainerOptionsThen(() => {
      const sel = document.getElementById('vpTrainerSelect');
      sel.innerHTML = vendorTrainerOptionsHtml(r.trainerUsername || r.trainerName);
      onVendorTrainerSelectChange(sel);
      setupExternalBookingPreview('vp','vendor',id);
    });
  }
  function submitEditVendorProject(id){
    const payload = {
      projectID: id,
      vendor: document.getElementById('vpVendor').value.trim(),
      collegeName: document.getElementById('vpCollege').value.trim(),
      logoURL: document.getElementById('vpLogoURL').value.trim(),
      trainerUsername: ['__other__'].includes(document.getElementById('vpTrainerSelect').value) ? '' : (document.getElementById('vpTrainerSelect').value || ''),
      trainerName: readVendorTrainerName(),
      days: Number(document.getElementById('vpDays').value) || 0,
      startDate: document.getElementById('vpStartDate').value,
      endDate: document.getElementById('vpEndDate').value,
      startTime: document.getElementById('vpStartTime').value,
      endTime: document.getElementById('vpEndTime').value,
      batch: document.getElementById('vpBatch').value.trim(),
      category: document.getElementById('vpCategory').value.trim(),
      status: document.getElementById('vpStatus').value,
      location: document.getElementById('vpLocation').value.trim(),
      comments: document.getElementById('vpComments').value.trim(),
      updatedBy: currentUser.username
    };
    if(!isAdminUser()){ showToast('Only Admin can edit projects.', true); return; }
    assignmentWriteWithSchedule('updateVendorProject', {...payload, projectType:'vendor', projectId:payload.projectID || ''}, () => {
      showToast('Vendor project updated.'); closeModal(); renderVendorTab();
    });
  }
  function deleteVendorRow(id){
    if(!isAdminUser()){ showToast('Only Admin can delete projects.', true); return; }
    showLoading(true);
    callServer('deleteVendorProject', id, currentUser.username).then(() => { showLoading(false); renderVendorTab(); }).catch(err => { showLoading(false); handleError(err); });
  }

  // Managers have ownership-only controls; Trainer never receives this action.
  function openReassignExternalProject(kind,id){
    if(!isApproverUser())return;
    const record=(kind==='vendor' ? vendorRowsCache : freelanceRowsCache).find(x=>x.projectID===id);
    if(!record)return;
    document.getElementById('modalTitle').textContent='Reassign '+(kind==='vendor'?'Vendor':'Freelancer')+' Project';
    document.getElementById('modalBody').innerHTML=`
      <div class="field"><label>Project</label><strong>${escapeHtml(record.collegeName)}</strong></div>
      <div class="field"><label>Assign Employee ID</label><select id="reassignTrainer"><option value="">Loading trainers…</option></select></div>
      <div class="form-row"><div class="field"><label>Start Date</label><input id="reassignFrom" type="date" value="${escapeHtml(record.startDate||'')}"></div>
      <div class="field"><label>End Date</label><input id="reassignTo" type="date" value="${escapeHtml(record.endDate||'')}"></div></div>
      <div class="form-row"><div class="field"><label>Start Time</label><input id="reassignStart" type="time" value="${escapeHtml(record.startTime||'')}"></div>
      <div class="field"><label>End Time</label><input id="reassignEnd" type="time" value="${escapeHtml(record.endTime||'')}"></div></div>
      <div class="field"><label>Batch</label><input id="reassignBatch" value="${escapeHtml(record.batch||'')}"></div>`;
    document.getElementById('modalFooter').innerHTML=`<button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-red" onclick="submitManagerReassignment('${kind}','${escapeHtml(id)}')">Save Assignment</button>`;
    document.getElementById('modalOverlay').classList.add('active');
    callServer('getTrainerUsers').then(users=>{
      const sel=document.getElementById('reassignTrainer');if(!sel)return;
      sel.innerHTML='<option value="">Select Trainer…</option>'+users.map(t=>
        `<option value="${escapeHtml(t.username)}" ${t.username===record.trainerUsername?'selected':''}>${escapeHtml(t.fullName)} (${escapeHtml(t.username)})</option>`).join('');
    }).catch(handleError);
  }
  function submitManagerReassignment(kind,id){
    if(!isApproverUser())return;
    const data={projectType:kind,projectId:id,trainerUsername:document.getElementById('reassignTrainer').value,
      startDate:document.getElementById('reassignFrom').value,endDate:document.getElementById('reassignTo').value,
      startTime:document.getElementById('reassignStart').value,endTime:document.getElementById('reassignEnd').value,
      batch:document.getElementById('reassignBatch').value.trim()};
    if(!data.trainerUsername){showToast('Choose a Trainer Employee ID.',true);return;}
    assignmentWriteWithSchedule('reassignJob',data,()=>{
      showToast('Trainer reassigned.');closeModal();
      kind==='vendor'?renderVendorTab():renderFreelanceTab();
    });
  }

  // ---------- FREELANCE PROJECTS TAB ----------
  let freelanceRowsCache = [];

  function openAddFreelanceProject(){
    if(!isAdminUser()){ showToast('Only Admin can modify projects.', true); return; }
    document.getElementById('modalTitle').textContent = 'Add Freelance Project';
    document.getElementById('modalBody').innerHTML = `
      <div class="form-row">
        <div class="field"><label>Vendor</label><input id="fpVendor"></div>
        <div class="field">
          <label>College Name</label>
          <input id="fpCollege" oninput="previewCollegeLogoByName(this.value,'fpLogoPreview')">
          <div id="fpLogoPreview" class="logo-preview-inline"></div>
        </div>
        <div class="field">
          <label>Project Logo URL</label>
          <input id="fpLogoURL" placeholder="https://example.com/logo.png"
                 oninput="previewImageUrl(this.value,'fpManualLogoPreview')">
          <div id="fpManualLogoPreview" class="logo-preview-inline"></div>
        </div>
      </div>
      <div class="form-row">
        <div class="field"><label>Assigned Trainer</label><select id="fpTrainerSelect">Loading…</select></div>
        <div class="field"><label>Freelancer Name</label><input id="fpFreelancer" placeholder="External freelancer name"></div>
        <div class="field"><label>Days of Program</label><input id="fpDays" type="number"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>Start Date</label><input id="fpStartDate" type="date"></div>
        <div class="field"><label>End Date</label><input id="fpEndDate" type="date"></div>
        <div class="field"><label>Start Time (optional)</label><input id="fpStartTime" type="time" ></div>
        <div class="field"><label>End Time (optional)</label><input id="fpEndTime" type="time" ></div>
        <div class="field"><label>Batch / Slot</label><input id="fpBatch"  placeholder="e.g. Batch A"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>Category</label><input id="fpCategory"></div>
        <div class="field">
          <label>Project Status</label>
          <select id="fpStatus">
            <option value="Running">Running</option>
            <option value="Upcoming">Upcoming</option>
            <option value="On Hold">On Hold</option>
            <option value="Completed">Completed</option>
            <option value="Cancelled">Cancelled</option>
          </select>
        </div>
      </div>
      <div class="field"><label>Location</label><input id="fpLocation" placeholder="e.g. Chennai"></div>
      <div class="field"><label>Comments/Remarks</label><textarea id="fpComments" rows="2"></textarea></div>
    `;
    document.getElementById('modalFooter').innerHTML = `
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-red" onclick="submitFreelanceProject()">Add</button>
    `;
    document.getElementById('modalOverlay').classList.add('active');
    callServer('getAllTrainerUsersForDropdown').then(users=>{ const sel=document.getElementById('fpTrainerSelect'); if(sel) sel.innerHTML='<option value="">Select trainer</option>'+users.map(t=>`<option value="${escapeHtml(t.username)}">${escapeHtml(t.fullName)} (${escapeHtml(t.username)})</option>`).join(''); setupExternalBookingPreview('fp','freelance',''); });
  }
  function submitFreelanceProject(){
    const payload = {
      vendor: document.getElementById('fpVendor').value.trim(),
      collegeName: document.getElementById('fpCollege').value.trim(),
      logoURL: document.getElementById('fpLogoURL').value.trim(),
      trainerUsername: document.getElementById('fpTrainerSelect').value || '',
      freelancerName: document.getElementById('fpFreelancer').value.trim(),
      days: Number(document.getElementById('fpDays').value) || 0,
      startDate: document.getElementById('fpStartDate').value,
      endDate: document.getElementById('fpEndDate').value,
      startTime: document.getElementById('fpStartTime').value,
      endTime: document.getElementById('fpEndTime').value,
      batch: document.getElementById('fpBatch').value.trim(),
      category: document.getElementById('fpCategory').value.trim(),
      status: document.getElementById('fpStatus').value,
      location: document.getElementById('fpLocation').value.trim(),
      comments: document.getElementById('fpComments').value.trim(),
      createdBy: currentUser.username
    };
    if(!isAdminUser()){ showToast('Only Admin can create projects.', true); return; }
    if(!payload.vendor || !payload.collegeName){ showToast('Vendor and College Name are required.', true); return; }
    assignmentWriteWithSchedule('createFreelanceProject', {...payload, projectType:'freelance', projectId:payload.projectID || ''}, () => {
      showToast('Freelance project added.'); closeModal(); renderFreelanceTab();
    });
  }
  function openEditFreelanceProject(id){
    if(!isAdminUser()){ showToast('Only Admin can modify projects.', true); return; }
    const r = freelanceRowsCache.find(x => x.projectID === id);
    if(!r) return;
    document.getElementById('modalTitle').textContent = 'Edit Freelance Project';
    document.getElementById('modalBody').innerHTML = `
      <div class="form-row">
        <div class="field"><label>Vendor</label><input id="fpVendor" value="${escapeHtml(r.vendor)}"></div>
        <div class="field">
          <label>College Name</label>
          <input id="fpCollege" value="${escapeHtml(r.collegeName)}"
                 oninput="previewCollegeLogoByName(this.value,'fpLogoPreview')">
          <div id="fpLogoPreview" class="logo-preview-inline"></div>
        </div>
        <div class="field">
          <label>Project Logo URL</label>
          <input id="fpLogoURL" value="${escapeHtml(r.logoURL || '')}"
                 placeholder="https://example.com/logo.png"
                 oninput="previewImageUrl(this.value,'fpManualLogoPreview')">
          <div id="fpManualLogoPreview" class="logo-preview-inline"></div>
        </div>
      </div>
      <div class="form-row">
        <div class="field"><label>Assigned Trainer</label><select id="fpTrainerSelect">Loading…</select></div>
        <div class="field"><label>Freelancer Name</label><input id="fpFreelancer" value="${escapeHtml(r.freelancerName)}"></div>
        <div class="field"><label>Days of Program</label><input id="fpDays" type="number" value="${escapeHtml(r.days)}"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>Start Date</label><input id="fpStartDate" type="date" value="${escapeHtml(r.startDate || '')}"></div>
        <div class="field"><label>End Date</label><input id="fpEndDate" type="date" value="${escapeHtml(r.endDate || '')}"></div>
        <div class="field"><label>Start Time (optional)</label><input id="fpStartTime" type="time" value="${escapeHtml(r.startTime || '')}"></div>
        <div class="field"><label>End Time (optional)</label><input id="fpEndTime" type="time" value="${escapeHtml(r.endTime || '')}"></div>
        <div class="field"><label>Batch / Slot</label><input id="fpBatch" value="${escapeHtml(r.batch || '')}" placeholder="e.g. Batch A"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>Category</label><input id="fpCategory" value="${escapeHtml(r.category)}"></div>
        <div class="field">
          <label>Project Status</label>
          <select id="fpStatus">
            ${['Running','Upcoming','On Hold','Completed','Cancelled'].map(s =>
              `<option value="${s}" ${String(r.status || 'Running') === s ? 'selected' : ''}>${s}</option>`
            ).join('')}
          </select>
        </div>
      </div>
      <div class="field"><label>Location</label><input id="fpLocation" value="${escapeHtml(r.location || '')}"></div>
      <div class="field"><label>Comments/Remarks</label><textarea id="fpComments" rows="2">${escapeHtml(r.comments || '')}</textarea></div>
    `;
    document.getElementById('modalFooter').innerHTML = `
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-red" onclick="submitEditFreelanceProject('${id}')">Save Changes</button>
    `;
    document.getElementById('modalOverlay').classList.add('active');
    callServer('getAllTrainerUsersForDropdown').then(users=>{ const sel=document.getElementById('fpTrainerSelect'); if(sel) sel.innerHTML='<option value="">Select trainer</option>'+users.map(t=>`<option value="${escapeHtml(t.username)}" ${t.username===r.trainerUsername?'selected':''}>${escapeHtml(t.fullName)} (${escapeHtml(t.username)})</option>`).join(''); setupExternalBookingPreview('fp','freelance',id); });
  }
  function submitEditFreelanceProject(id){
    const payload = {
      projectID: id,
      vendor: document.getElementById('fpVendor').value.trim(),
      collegeName: document.getElementById('fpCollege').value.trim(),
      logoURL: document.getElementById('fpLogoURL').value.trim(),
      trainerUsername: document.getElementById('fpTrainerSelect').value || '',
      freelancerName: document.getElementById('fpFreelancer').value.trim(),
      days: Number(document.getElementById('fpDays').value) || 0,
      startDate: document.getElementById('fpStartDate').value,
      endDate: document.getElementById('fpEndDate').value,
      startTime: document.getElementById('fpStartTime').value,
      endTime: document.getElementById('fpEndTime').value,
      batch: document.getElementById('fpBatch').value.trim(),
      category: document.getElementById('fpCategory').value.trim(),
      status: document.getElementById('fpStatus').value,
      location: document.getElementById('fpLocation').value.trim(),
      comments: document.getElementById('fpComments').value.trim(),
      updatedBy: currentUser.username
    };
    if(!isAdminUser()){ showToast('Only Admin can edit projects.', true); return; }
    assignmentWriteWithSchedule('updateFreelanceProject', {...payload, projectType:'freelance', projectId:payload.projectID || ''}, () => {
      showToast('Freelance project updated.'); closeModal(); renderFreelanceTab();
    });
  }
  function deleteFreelanceRow(id){
    if(!isAdminUser()){ showToast('Only Admin can delete projects.', true); return; }
    showLoading(true);
    callServer('deleteFreelanceProject', id, currentUser.username).then(() => { showLoading(false); renderFreelanceTab(); }).catch(err => { showLoading(false); handleError(err); });
  }

  // ---------- COLLEGE LOGO HELPERS ----------
  function previewImageUrl(url, targetId){
    const el = document.getElementById(targetId);
    if(!el) return;

    const value = String(url || '').trim();
    if(!value){
      el.innerHTML = '<span>No logo selected</span>';
      return;
    }

    el.innerHTML = `
      <img src="${escapeHtml(value)}"
           alt="College logo preview"
           onerror="this.parentElement.innerHTML='<span>Logo URL could not be loaded</span>';">
    `;
  }

  function previewCollegeLogoByName(collegeName, targetId){
    const name = String(collegeName || '').trim();
    const target = document.getElementById(targetId);
    if(!target) return;

    if(!name){
      target.innerHTML = '';
      return;
    }

    const findLocal = () => {
      const list = Array.isArray(collegesCache) ? collegesCache : [];
      const key = name.toLowerCase();
      const college = list.find(c =>
        String(c.collegeName || '').trim().toLowerCase() === key
      );

      if(college && college.logoURL){
        previewImageUrl(college.logoURL, targetId);
      }else{
        target.innerHTML = '<span class="logo-hint">No logo found for this college</span>';
      }
    };

    if(Array.isArray(collegesCache) && collegesCache.length){
      findLocal();
      return;
    }

    callServer('getColleges').then(list => {
      collegesCache = Array.isArray(list) ? list : [];
      findLocal();
    }).catch(() => {
      target.innerHTML = '<span class="logo-hint">Could not load college logo</span>';
    });
  }

  // ---------- CREATE COLLEGE MODAL ----------
  let categoryRows = [{category:'', plannedDays:''}];
  let trainerRows = [{trainerUsername:'', category:'', fromDate:'', toDate:''}];

  function openCreateCollege(){
    categoryRows = [{category:'', plannedDays:''}];
    trainerRows = [{trainerUsername:'', category:'', fromDate:'', toDate:''}];
    document.getElementById('modalTitle').textContent = 'Create New College Project';
    document.getElementById('modalBody').innerHTML = `
      <div class="form-row">
        <div class="field"><label>College Name *</label><input id="ncName" placeholder="e.g. Bishop Heber College"></div>
        <div class="field"><label>Student Strength</label><input id="ncStrength" type="number" placeholder="e.g. 150"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>Status</label>
          <select id="ncStatus">
            <option>Upcoming</option><option>Running</option><option>On Hold</option><option>Completed</option><option>Cancelled</option>
          </select>
        </div>
        <div class="field"><label>Start Date</label><input id="ncStart" type="date"></div>
      </div>

      <div class="field">
        <label>College Logo URL</label>
        <input id="ncLogoURL" placeholder="https://.../college-logo.png"
               oninput="previewImageUrl(this.value,'ncLogoPreview')">
        <div id="ncLogoPreview" class="logo-preview-box">
          <span>No logo selected</span>
        </div>
        <div class="field-hint">Paste a public image URL. This logo will also appear in Vendor Projects and Freelancer Projects when the college name matches.</div>
      </div>

      <div class="field"><label>Attendance Sheet Link (optional — paste if you already have one)</label><input id="ncAttendanceLink" placeholder="https://docs.google.com/spreadsheets/..."></div>
      <div class="field"><label>Notes</label><textarea id="ncNotes" rows="2"></textarea></div>

      <div class="field">
        <label>Training Categories &amp; Planned Days</label>
        <div class="repeatable-label-row"><span>Category</span><span>Planned Days</span><span></span></div>
        <div id="categoryRowsArea"></div>
        <button type="button" class="add-row-btn" onclick="addCategoryRow()">+ Add Category</button>
      </div>

      <div class="field">
        <label>Total Days of the Program</label>
        <div id="ncTotalDays" class="total-days-display">0 days</div>
        <div class="field-hint">Adds up automatically from the category days above — the same total shown on the college's card and reports.</div>
      </div>

      <div class="field">
        <label>Assign Trainers</label>
        <div class="repeatable-label-row trainer-row"><span>Trainer</span><span>Category</span><span>From</span><span>To</span><span></span></div>
        <div id="trainerRowsArea">Loading trainer list…</div>
        <div id="newCollegeAvailability" class="field-hint"></div>
        <button type="button" class="add-row-btn" onclick="addTrainerRow()">+ Add Trainer</button>
      </div>
    `;
    document.getElementById('modalFooter').innerHTML = `
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-red" onclick="submitCreateCollege()">Create Project</button>
    `;
    renderCategoryRows();
    callServer('getTrainerUsers').then(users => { trainerUsersCache = users; renderTrainerRows(); });
    document.getElementById('modalOverlay').classList.add('active');
  }

  function renderCategoryRows(){
    document.getElementById('categoryRowsArea').innerHTML = categoryRows.map((r, i) => `
      <div class="repeatable-row">
        <input placeholder="Category (e.g. Java)" value="${escapeHtml(r.category)}" oninput="categoryRows[${i}].category=this.value">
        <input type="number" placeholder="Planned Days" value="${escapeHtml(r.plannedDays)}" oninput="categoryRows[${i}].plannedDays=this.value; updateTotalDaysDisplay();">
        <button type="button" class="remove-row-btn" onclick="removeCategoryRow(${i})">&times;</button>
      </div>`).join('');
    updateTotalDaysDisplay();
  }
  function updateTotalDaysDisplay(){
    const el = document.getElementById('ncTotalDays');
    if(!el) return;
    const total = categoryRows.reduce((sum, r) => sum + (Number(r.plannedDays) || 0), 0);
    el.textContent = total + (total === 1 ? ' day' : ' days');
  }
  function addCategoryRow(){ categoryRows.push({category:'', plannedDays:''}); renderCategoryRows(); }
  function removeCategoryRow(i){ categoryRows.splice(i,1); renderCategoryRows(); }

  function trainerOptionsHtml(selected){
    if(trainerUsersCache.length === 0) return `<option value="">No active trainer accounts yet</option>`;
    return `<option value="">Select trainer…</option>` + trainerUsersCache.map(t =>
      `<option value="${escapeHtml(t.username)}" ${t.username === selected ? 'selected' : ''}>${escapeHtml(t.fullName)} (${escapeHtml(t.username)})</option>`).join('');
  }
  function renderTrainerRows(){
    document.getElementById('trainerRowsArea').innerHTML = trainerRows.map((r, i) => `
      <div class="repeatable-row trainer-row">
        <select onchange="trainerRows[${i}].trainerUsername=this.value; checkCreateCollegeBooking()">${trainerOptionsHtml(r.trainerUsername)}</select>
        <input placeholder="Category" value="${escapeHtml(r.category)}" oninput="trainerRows[${i}].category=this.value">
        <input type="date" value="${escapeHtml(r.fromDate)}" oninput="trainerRows[${i}].fromDate=this.value; checkCreateCollegeBooking()">
        <input type="date" value="${escapeHtml(r.toDate||'')}" oninput="trainerRows[${i}].toDate=this.value; checkCreateCollegeBooking()">
        <select onchange="trainerRows[${i}].assignmentStatus=this.value"><option ${r.assignmentStatus==='Upcoming'?'selected':''}>Upcoming</option><option ${r.assignmentStatus==='Running'?'selected':''}>Running</option><option ${r.assignmentStatus==='On Hold'?'selected':''}>On Hold</option><option ${r.assignmentStatus==='Completed'?'selected':''}>Completed</option><option ${r.assignmentStatus==='Not Active'?'selected':''}>Not Active</option></select>
        <button type="button" class="remove-row-btn" onclick="removeTrainerRow(${i})">&times;</button>
      </div>`).join('');
  }
  let newCollegeBookingGeneration=0;
  function checkCreateCollegeBooking(){
    const generation=++newCollegeBookingGeneration;
    const hint=document.getElementById('newCollegeAvailability');
    if(!hint)return;
    const candidates=trainerRows.filter(r=>r.trainerUsername&&r.fromDate&&r.toDate);
    if(!candidates.length){hint.textContent='Choose a trainer and assignment dates to check for schedule conflicts.';return;}
    hint.textContent='Checking trainer booking…';
    Promise.all(candidates.map(r=>window.ltmpApi.call('checkTrainerSchedule',{
      trainerUsername:r.trainerUsername,startDate:r.fromDate,endDate:r.toDate
    }))).then(checks=>{
      if(generation!==newCollegeBookingGeneration||!hint.isConnected)return;
      const conflictCount=checks.reduce((sum,r)=>sum+r.conflicts.length,0);
      hint.innerHTML=conflictCount
        ? `<span style="color:var(--red)">⚠ Trainer is already occupied. ${conflictCount} booking conflict(s) found. Admin must acknowledge before creating this college.</span>`
        : '<span style="color:var(--green)">No existing trainer bookings overlap the selected dates.</span>';
    }).catch(err=>{if(generation===newCollegeBookingGeneration&&hint.isConnected)hint.textContent=err.message;});
  }
  function addTrainerRow(){ trainerRows.push({trainerUsername:'', category:'', fromDate:'', toDate:'', assignmentStatus:'Upcoming'}); renderTrainerRows(); }
  function removeTrainerRow(i){ trainerRows.splice(i,1); renderTrainerRows(); }

  function submitCreateCollege(){
    const name = document.getElementById('ncName').value.trim();
    if(!name){ showToast('College name is required.', true); return; }
    if(!isAdminUser()){ showToast('Only Admin can create college projects.', true); return; }
    const payload = {
      collegeName: name,
      studentStrength: Number(document.getElementById('ncStrength').value) || 0,
      status: document.getElementById('ncStatus').value,
      startDate: document.getElementById('ncStart').value,
      logoURL: document.getElementById('ncLogoURL').value.trim(),
      attendanceSheetLink: document.getElementById('ncAttendanceLink').value.trim(),
      notes: document.getElementById('ncNotes').value.trim(),
      categories: categoryRows.filter(r => r.category),
      trainers: trainerRows.filter(r => r.trainerUsername),
      createdBy: currentUser.username
    };
    const save=(override)=>{
      showLoading(true);
      const request={...payload, trainers:payload.trainers.map(t=>({...t,acknowledgeConflict:override}))};
      callServer('createCollege',request).then(res=>{
        showLoading(false);
        if(!res.success){showToast(res.message || 'Could not create college.',true);return;}
        showToast('College project created: '+res.collegeCode);
        closeModal();switchDashTab('lesuccess');
      }).catch(err=>{
        showLoading(false);
        if(err.status===409 && err.conflicts){bookingConflictDialog(err.conflicts,()=>save(true));return;}
        handleError(err);
      });
    };
    save(false);
  }

  // ---------- COLLEGE PROFILE ----------
  function renderCollegeProfile(code){
    content('<div class="empty-state">Loading college profile…</div>');
    showLoading(true);
    callServer('getCollegeProfile', code).then(data => {
      showLoading(false);
      if(!data){ content('<div class="empty-state">College not found.</div>'); return; }
      window._profileData = data;
      const c = data.college;
      content(`
        <div class="page-heading">
          <button class="btn btn-outline btn-sm"
                  onclick="navigate(profileBackPage())">
            &larr; ${profileBackLabel()}
          </button>
        </div>
        <div class="profile-header">
          ${c.logoURL ? `<img src="${escapeHtml(c.logoURL)}">` : ''}
          <div>
            <h2>${escapeHtml(c.collegeName)} <span class="status-pill status-${statusClass(c.status)}">${escapeHtml(c.status)}</span></h2>
            <div style="color:var(--gray-700); font-size:13px;">${escapeHtml(c.collegeCode)} &middot; ${c.studentStrength || 0} Students &middot; Total Program Days: ${c.totalPlannedDays}</div>
          </div>
        </div>
        <div class="tab-bar" id="profileTabs"></div>
        <div class="tab-panel" id="profileTabPanel"></div>
      `);
      const tabs = [
        {id:'overview', label:'Overview'},
        {id:'trainers', label:'Trainers'},
        {id:'planning', label:'Training Planning'},
        {id:'dailylog', label:'Daily Log'},
        {id:'syllabus', label:'Syllabus'},
        {id:'history', label:'Hold/Resume History'}
      ];
      document.getElementById('profileTabs').innerHTML = tabs.map((t,i) =>
        `<button class="tab-btn ${i===0?'active':''}" data-tab="${t.id}" onclick="switchProfileTab('${t.id}','${code}')">${t.label}</button>`).join('');
      switchProfileTab('overview', code);
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function switchProfileTab(tab, code){
    document.querySelectorAll('#profileTabs .tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    const data = window._profileData;
    const c = data.college;
    const panel = document.getElementById('profileTabPanel');
    const isAdmin = currentUser.role === 'Admin';

    if(tab === 'overview'){
      panel.innerHTML = `
        <div class="stat-grid">
          <div class="stat-box"><div class="v">${c.totalPlannedDays}</div><div class="l">Total Program Days</div></div>
          <div class="stat-box"><div class="v">${c.completedDays}</div><div class="l">Completed Days</div></div>
          <div class="stat-box"><div class="v">${c.remainingDays}</div><div class="l">Remaining Days</div></div>
          <div class="stat-box"><div class="v">${c.progressPercent}%</div><div class="l">Overall Progress</div></div>
          <div class="stat-box"><div class="v">${c.avgAttendance}%</div><div class="l">Avg. Attendance</div></div>
          <div class="stat-box"><div class="v">${c.trainerCount}</div><div class="l">Trainers Assigned</div></div>
        </div>
        <div class="progress-track" style="height:10px; margin-bottom:20px;"><div class="progress-fill" style="width:${c.progressPercent}%;"></div></div>
        <div class="form-row">
          <div><b>Start Date:</b> ${fmtDate(c.startDate)}</div>
          <div><b>End Date:</b> ${fmtDate(c.endDate)}</div>
        </div>
        <div style="margin-top:12px;"><b>Attendance / Assessment Sheet:</b> ${c.attendanceSheetLink ? `<a href="${escapeHtml(c.attendanceSheetLink)}" target="_blank">Open Sheet &rarr;</a>` : 'Not linked yet'}</div>
        <div style="margin-top:12px;"><b>Notes:</b> ${escapeHtml(c.notes || '—')}</div>
        ${isAdmin ? `<div style="margin-top:20px;"><button class="btn btn-outline btn-sm" onclick="openEditCollege('${code}')">Edit Details</button>
          <select id="statusChanger" style="margin-left:10px; padding:8px; border-radius:9px; border:1px solid var(--gray-300);">
            <option value="">Change Status…</option>
            <option>Upcoming</option><option>Running</option><option>On Hold</option><option>Completed</option><option>Cancelled</option>
          </select>
          <button class="btn btn-primary btn-sm" onclick="changeCollegeStatus('${code}')">Update</button></div>` : ''}
      `;
    } else if(tab === 'trainers'){
      panel.innerHTML = `
        ${(isApproverUser()) ? `<button class="btn btn-outline btn-sm" style="margin-bottom:14px;" onclick="openAssignTrainer('${code}')">+ Assign Trainer</button>` : ''}
        <table><thead><tr><th>Trainer</th><th>Category</th><th>From</th><th>To</th><th>Assignment Status</th><th>Status Timeline</th><th>Action</th></tr></thead>
        <tbody>${data.trainers.map(t => `<tr><td>${escapeHtml(t.trainerName)}</td><td>${escapeHtml(t.category)}</td><td>${fmtDate(t.fromDate)}</td><td>${fmtDate(t.toDate)}</td><td><span class="status-pill status-${statusClass(t.assignmentStatus)}">${escapeHtml(t.assignmentStatus || 'Upcoming')}</span></td><td><button class="btn btn-outline btn-sm" onclick="openStatusTimeline('${escapeHtml(t.assignmentID)}','${escapeHtml(t.trainerName)}')">View Timeline</button></td><td>${isApproverUser() ? `<select id="asgStatus_${escapeHtml(t.assignmentID)}"><option ${t.assignmentStatus==='Upcoming'?'selected':''}>Upcoming</option><option ${t.assignmentStatus==='Running'?'selected':''}>Running</option><option ${t.assignmentStatus==='On Hold'?'selected':''}>On Hold</option><option ${t.assignmentStatus==='Completed'?'selected':''}>Completed</option><option ${t.assignmentStatus==='Not Active'?'selected':''}>Not Active</option></select> <button class="btn btn-outline btn-sm" onclick="saveAssignmentStatus('${escapeHtml(t.assignmentID)}','${escapeHtml(code)}')">Update</button>` : '—'}</td></tr>`).join('') || '<tr><td colspan="7" style="text-align:center; color:var(--gray-500);">No trainers assigned yet.</td></tr>'}</tbody></table>
      `;
    } else if(tab === 'planning'){
      panel.innerHTML = `
        ${isAdmin ? `<button class="btn btn-outline btn-sm" style="margin-bottom:14px;" onclick="openEditPlanning('${code}')">Edit Planning</button>` : ''}
        <table><thead><tr><th>Category</th><th>Planned Days</th><th>Completed</th><th>Progress</th></tr></thead>
        <tbody>${data.categories.map(cp => `<tr><td>${escapeHtml(cp.category)}</td><td>${cp.plannedDays}</td><td>${cp.completedDays}</td><td>${cp.progressPercent}%</td></tr>`).join('') || '<tr><td colspan="4" style="text-align:center; color:var(--gray-500);">No categories planned yet.</td></tr>'}</tbody></table>
      `;
    } else if(tab === 'dailylog'){
      panel.innerHTML = `
        <table><thead><tr><th>Date</th><th>Category</th><th>Topic Covered</th><th>Attendance</th><th>Trainer</th></tr></thead>
        <tbody>${data.dailyLog.map(d => `<tr><td>${fmtDate(d.Date)}</td><td>${escapeHtml(d.Category)}</td><td>${escapeHtml(d.TopicCovered)}</td><td>${escapeHtml(d.Attendance)}</td><td>${escapeHtml(d.TrainerName)}</td></tr>`).join('') || '<tr><td colspan="5" style="text-align:center; color:var(--gray-500);">No updates logged yet.</td></tr>'}</tbody></table>
      `;
    } else if(tab === 'syllabus'){
      panel.innerHTML = `
        <table><thead><tr><th>Category</th><th>Topic</th><th>Trainer Status</th><th>RM Status</th></tr></thead>
        <tbody>${data.syllabus.map(s => `<tr><td>${escapeHtml(s.Category)}</td><td>${escapeHtml(s.Topic)}</td><td>${escapeHtml(s.TrainerStatus)}</td><td>${escapeHtml(s.RMStatus)}</td></tr>`).join('') || '<tr><td colspan="4" style="text-align:center; color:var(--gray-500);">No syllabus entries yet.</td></tr>'}</tbody></table>
      `;
    } else if(tab === 'history'){
      panel.innerHTML = `
        <table><thead><tr><th>Activity</th><th>Date</th><th>Recorded By</th></tr></thead>
        <tbody>${data.history.map(h => `<tr><td>${escapeHtml(h.Activity)}</td><td>${fmtDate(h.Date)}</td><td>${escapeHtml(h.RecordedBy)}</td></tr>`).join('') || '<tr><td colspan="3" style="text-align:center; color:var(--gray-500);">No history yet.</td></tr>'}</tbody></table>
      `;
    }
  }

  function changeCollegeStatus(code){
    const status = document.getElementById('statusChanger').value;
    if(!status){ showToast('Select a status first.', true); return; }
    showLoading(true);
    callServer('updateCollege', {collegeCode: code, status: status, updatedBy: currentUser.username}).then(result => {
      showLoading(false);
      if(!result.success){ showToast(result.message || 'College status update failed', true); return; } showToast('Status updated.');
      renderCollegeProfile(code);
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function openEditCollege(code){
    const c = window._profileData.college;
    document.getElementById('modalTitle').textContent = 'Edit College Details';
    document.getElementById('modalBody').innerHTML = `
      <div class="form-row">
        <div class="field"><label>College Name</label><input id="ecName" value="${escapeHtml(c.collegeName)}"></div>
        <div class="field"><label>Student Strength</label><input id="ecStrength" type="number" value="${c.studentStrength || 0}"></div>
      </div>
      <div class="field"><label>Logo URL</label><input id="ecLogo" value="${escapeHtml(c.logoURL || '')}" placeholder="Paste Drive/image link"></div>
      <div class="field"><label>Attendance Sheet Link</label><input id="ecAttendance" value="${escapeHtml(c.attendanceSheetLink || '')}"></div>
      <div class="form-row">
        <div class="field"><label>Start Date</label><input id="ecStart" type="date" value="${c.startDate ? new Date(c.startDate).toISOString().substring(0,10) : ''}"></div>
        <div class="field"><label>End Date</label><input id="ecEnd" type="date" value="${c.endDate ? new Date(c.endDate).toISOString().substring(0,10) : ''}"></div>
      </div>
      <div class="field"><label>Notes</label><textarea id="ecNotes" rows="2">${escapeHtml(c.notes || '')}</textarea></div>
    `;
    document.getElementById('modalFooter').innerHTML = `
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-red" onclick="submitEditCollege('${code}')">Save Changes</button>
    `;
    document.getElementById('modalOverlay').classList.add('active');
  }
  function submitEditCollege(code){
    const payload = {
      collegeCode: code,
      collegeName: document.getElementById('ecName').value.trim(),
      studentStrength: Number(document.getElementById('ecStrength').value) || 0,
      logoURL: document.getElementById('ecLogo').value.trim(),
      attendanceSheetLink: document.getElementById('ecAttendance').value.trim(),
      startDate: document.getElementById('ecStart').value,
      endDate: document.getElementById('ecEnd').value,
      notes: document.getElementById('ecNotes').value.trim()
    };
    showLoading(true);
    payload.updatedBy = currentUser.username;
    if(!isAdminUser()){ showToast('Only Admin can edit colleges.', true); return; }
    callServer('updateCollege', payload).then(result => {
      showLoading(false);
      if(!result.success){ showToast(result.message || 'College update failed', true); return; } showToast('College details updated.');
      closeModal();
      renderCollegeProfile(code);
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function openAssignTrainer(code){
    // Select the college's planned category to avoid a mismatched assignment.
    const plannedCategories = (window._profileData?.categories || [])
      .map(x => String(x.category || '').trim()).filter(Boolean);
    const categoryField = plannedCategories.length
      ? `<select id="atCategory"><option value="">Select training category…</option>${plannedCategories.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('')}</select>`
      : '<input id="atCategory" placeholder="First configure the college Training Planning categories">';
    document.getElementById('modalTitle').textContent = 'Assign Trainer';
    document.getElementById('modalBody').innerHTML = `
      <div class="field"><label>Trainer</label><select id="atUsername">Loading…</select></div>
      <div class="field"><label>Category</label>${categoryField}</div>
      <div class="form-row">
        <div class="field"><label>From Date</label><input id="atFrom" type="date"></div>
        <div class="field"><label>To Date</label><input id="atTo" type="date"></div>
        <div class="field"><label>Assignment Status</label><select id="atStatus" onchange="updateAssignmentStatusHint()"><option>Upcoming</option><option>Running</option><option>On Hold</option><option>Completed</option><option>Not Active</option></select></div>
      </div>
      <div class="form-row">
        <div class="field"><label>Start Time (optional)</label><input id="atStartTime" type="time"></div>
        <div class="field"><label>End Time (optional)</label><input id="atEndTime" type="time"></div>
        <div class="field"><label>Batch / Slot</label><input id="atBatch" placeholder="e.g. Batch A"></div>
      </div>
      <div id="atStatusHint" class="field-hint"></div>
      <div id="atAvailability" class="field-hint"></div>
    `;
    document.getElementById('modalFooter').innerHTML = `
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-red" onclick="submitAssignTrainer('${code}')">Assign</button>
    `;
    document.getElementById('modalOverlay').classList.add('active');
    callServer('getTrainerUsers').then(users => {
      trainerUsersCache = users;
      document.getElementById('atUsername').innerHTML = trainerOptionsHtml('');
      checkTrainerAssignmentAvailability();
    });
    ['atUsername','atFrom','atTo','atStartTime','atEndTime','atCategory'].forEach(id => {
      const el = document.getElementById(id);
      if(el) el.addEventListener('change', checkTrainerAssignmentAvailability);
    });
    updateAssignmentStatusHint();
  }
  function updateAssignmentStatusHint(){
    const status = document.getElementById('atStatus')?.value;
    const el = document.getElementById('atStatusHint');
    if(!el) return;
    el.textContent = (status === 'Completed' || status === 'Not Active')
      ? 'This is a historical/inactive assignment. It will NOT appear in the Trainer Daily Update form.'
      : 'This is a current assignment. It will appear in the selected Trainer My Colleges and Daily Update pages.';
  }
  function checkTrainerAssignmentAvailability(){
    const u=document.getElementById('atUsername')?.value;
    const start=document.getElementById('atFrom')?.value;
    const end=document.getElementById('atTo')?.value;
    const el=document.getElementById('atAvailability');
    if(!u||!start||!end){if(el)el.textContent='Choose a trainer and dates to check availability.';return;}
    const data={trainerUsername:u,startDate:start,endDate:end,
      startTime:document.getElementById('atStartTime')?.value || '',
      endTime:document.getElementById('atEndTime')?.value || '',
      projectType:'lesuccess',projectId:window._profileData?.college?.collegeCode || '',
      category:document.getElementById('atCategory')?.value || ''};
    callServer('checkTrainerSchedule',data).then(r=>{
      if(!el)return;
      el.innerHTML=r.is_occupied
        ? '<span style="color:var(--red)">⚠ Trainer already occupied in '+r.conflicts.length+' overlapping session(s)/leave. An Admin override is required.</span>'
        : '<span style="color:var(--green)">Available for this date and time slot.</span>';
    }).catch(err=>{if(el)el.textContent=err.message;});
  }

  function submitAssignTrainer(code){
    const payload = {
      collegeCode: code,
      trainerUsername: document.getElementById('atUsername').value,
      category: document.getElementById('atCategory').value.trim(),
      fromDate: document.getElementById('atFrom').value,
      toDate: document.getElementById('atTo').value,
      assignmentStatus: document.getElementById('atStatus').value,
      startTime: document.getElementById('atStartTime').value,
      endTime: document.getElementById('atEndTime').value,
      batch: document.getElementById('atBatch').value.trim()
    };
    if(!payload.trainerUsername){ showToast('Please select a trainer.', true); return; }
    if(!payload.category){ showToast('Please select or enter the college training category.', true); return; }
    payload.updatedBy = currentUser.username;
    if(!isApproverUser()){ showToast('Trainers are not permitted to reassign jobs.', true); return; }
    assignmentWriteWithSchedule('assignTrainer', {...payload,projectType:'lesuccess',projectId:code}, () => {
      showToast('Trainer assigned. Notification sent to Trainer Alerts.');
      closeModal();renderCollegeProfile(code);
    });
  }

  function saveAssignmentStatus(assignmentID, code){
    if(!isApproverUser()){showToast('Trainers are not permitted to reassign jobs.',true);return;}
    const status=document.getElementById('asgStatus_'+assignmentID)?.value;
    const comments = window.prompt('Optional remark for this status change (leave blank to skip):','') || '';
    showLoading(true); callServer('updateTrainerAssignmentStatus',assignmentID,status,currentUser.username,comments).then(r=>{
      showLoading(false); if(!r.success){showToast(r.message||'Could not update assignment status.',true);return;} showToast('Assignment status updated.'); renderCollegeProfile(code);
    }).catch(err=>{showLoading(false);handleError(err);});
  }

  // Professional, read-only audit trail for one assignment: every status
  // change with who made it and when. Available to Admin and Reporting
  // Manager alike (view-only — only Admin has the Update control above).
  function openStatusTimeline(assignmentID, trainerName){
    showLoading(true);
    callServer('getTrainerAssignmentStatusTimeline', assignmentID).then(rows => {
      showLoading(false);
      rows = Array.isArray(rows) ? rows : [];
      document.getElementById('modalTitle').textContent = 'Status Timeline — ' + trainerName;
      document.getElementById('modalFooter').innerHTML = '<button class="btn btn-outline" onclick="closeModal()">Close</button>';
      document.getElementById('modalBody').innerHTML = rows.length
        ? `<table><thead><tr><th>Previous Status</th><th>New Status</th><th>Changed By</th><th>Date</th><th>Remarks</th></tr></thead>
           <tbody>${rows.map(r => `<tr>
             <td>${r.previousStatus ? `<span class="status-pill status-${statusClass(r.previousStatus)}">${escapeHtml(r.previousStatus)}</span>` : '—'}</td>
             <td><span class="status-pill status-${statusClass(r.newStatus)}">${escapeHtml(r.newStatus)}</span></td>
             <td>${escapeHtml(r.recordedBy)}</td>
             <td>${fmtDate(r.date)}</td>
             <td>${escapeHtml(r.comments || '—')}</td>
           </tr>`).join('')}</tbody></table>`
        : '<p style="color:var(--gray-500);text-align:center;">No status changes recorded yet for this assignment.</p>';
      document.getElementById('modalOverlay').classList.add('active');
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function openEditPlanning(code){
    const cats = window._profileData.categories.map(c => ({category:c.category, plannedDays:c.plannedDays}));
    categoryRows = cats.length ? cats : [{category:'', plannedDays:''}];
    document.getElementById('modalTitle').textContent = 'Edit Training Planning';
    document.getElementById('modalBody').innerHTML = `<div id="categoryRowsArea"></div><button type="button" class="add-row-btn" onclick="addCategoryRow()">+ Add Category</button>`;
    document.getElementById('modalFooter').innerHTML = `
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-red" onclick="submitEditPlanning('${code}')">Save Planning</button>
    `;
    renderCategoryRows();
    document.getElementById('modalOverlay').classList.add('active');
  }
  function submitEditPlanning(code){
    const cats = categoryRows.filter(r => r.category);
    showLoading(true);
    if(!isAdminUser()){ showToast('Only Admin can edit training planning.', true); return; }
    callServer('updateCategoryPlanning', code, cats, currentUser.username).then(result => {
      showLoading(false);
      if(!result.success){ showToast(result.message || 'Training planning update failed', true); return; } showToast('Training planning updated.');
      closeModal();
      renderCollegeProfile(code);
    }).catch(err => { showLoading(false); handleError(err); });
  }

  // ---------- ALERTS ----------
  const ALERT_GROUPS = [
    {id:'attention', title:'Needs Attention'},
    {id:'pending', title:'Waiting on Your Approval'},
    {id:'onhold', title:'On Hold'},
    {id:'ontrack', title:'On Track'}
  ];
  function openAlertNotification(el){
    const id = el.dataset.alertId;
    const target = el.dataset.target || 'alerts';
    const code = el.dataset.college || '';
    if(id){
      callServer('markAlertRead', id).then(r => {
        if(r && r.success === false){ showToast(r.message || 'Unable to mark notification read.', true); return; }
        updateAlertBadge();
        navigate(target, code);
      }).catch(handleError);
    } else {
      navigate(target, code);
    }
  }
  function renderAlerts(){
    content('<div class="page-heading"><h1>Alerts &amp; Notifications</h1></div><div id="alertsArea"></div>');
    showLoading(true);
    callServer('getAlerts', currentUser.username).then(alerts => {
      showLoading(false);
      const area = document.getElementById('alertsArea');
      if(alerts.length === 0){ area.innerHTML = '<div class="empty-state">No alerts right now — everything looks good.</div>'; return; }
      const alertRowHtml = a => {
        const assignmentNotice = Boolean(a.notificationID);
        const target = assignmentNotice && isTrainerUser() ? 'myprojects' :
          a.collegeCode ? 'collegeProfile' : a.collegeName === 'Leave Management' ? 'leave' :
          a.collegeName === 'Daily Tracker' ? 'dailytracker' : a.collegeName === 'Training Approvals' ? 'approvals' : a.collegeName === 'My Projects' ? 'myprojects' : a.collegeName === 'KPI' ? 'kpi' : 'alerts';
        return `<div class="alert-row ${escapeHtml(a.level)}" data-alert-id="${escapeHtml(a.notificationID || '')}" data-target="${escapeHtml(target)}" data-college="${escapeHtml(a.collegeCode || '')}" onclick="openAlertNotification(this)" style="cursor:pointer;">
          ${a.collegeLogo ? `<img class="alert-logo" src="${escapeHtml(a.collegeLogo)}">` : `<span class="alert-dot ${escapeHtml(a.level)}"></span>`}
          <div><b>${escapeHtml(a.collegeName)}</b><br><span class="msg">${escapeHtml(a.message)}</span></div>
        </div>`;
      };
      area.innerHTML = ALERT_GROUPS.map(g => {
        const rows = alerts.filter(a => a.group === g.id);
        if(rows.length === 0) return '';
        return `<div class="alert-group-title">${escapeHtml(g.title)} (${rows.length})</div>${rows.map(alertRowHtml).join('')}`;
      }).join('');
    }).catch(err => { showLoading(false); handleError(err); });
  }


  // ---------- LTMP LEAVE MANAGEMENT ----------
  function renderLeavePage(){
    content(`
      <div class="page-heading"><h1>Leave Management</h1></div>
      ${isSubmitterUser() ? `
        <div class="section-header"><h3>Apply for Leave</h3></div>
        <div class="card" style="max-width:760px;padding:20px;margin-bottom:22px;">
          <div class="form-row">
            <div class="field"><label>Start Date</label><input id="leaveStart" type="date" onchange="calculateLeaveDays()"></div>
            <div class="field"><label>End Date</label><input id="leaveEnd" type="date" onchange="calculateLeaveDays()"></div>
            <div class="field"><label>Number of Days</label><input id="leaveDays" type="number" readonly></div>
          </div>
          <div class="field"><label>Comments</label><textarea id="leaveComments" rows="3" placeholder="Enter comments"></textarea></div>
          <button class="btn btn-red" onclick="submitLeave()">Submit</button>
        </div>` : ''}
      ${isAdminUser() ? '<p style="margin:0 0 12px;color:var(--gray-700);">All leave requests are visible here. Approve or reject is available only to the assigned reporting manager.</p>' : ''}
      <div class="section-header"><h3>${isTrainerUser() ? 'My Leave Requests' : isAdminUser() ? 'All Leave Requests' : 'Team Leave Requests'}</h3>
        <button class="btn btn-outline btn-sm download-btn" onclick="downloadTableAsCSV('leaveRequestsArea','leave_requests')">Download</button>
      </div>
      ${isApproverUser() ? `<div class="filter-bar"><input type="text" id="leaveFilterInput" placeholder="Filter by Employee ID or Name" oninput="filterLeaveRequests()"></div>` : ''}
      <div id="leaveRequestsArea"></div>
    `);
    loadLeaveRequests();
  }
  let leaveRequestsCache = [];
  function filterLeaveRequests(){
    const q = (document.getElementById('leaveFilterInput')?.value || '').trim().toLowerCase();
    const filtered = q ? leaveRequestsCache.filter(r =>
      String(r.employeeUsername||'').toLowerCase().includes(q) || String(r.employeeName||'').toLowerCase().includes(q)
    ) : leaveRequestsCache;
    renderLeaveRequestsTable(filtered);
  }
  function calculateLeaveDays(){
    const s=document.getElementById('leaveStart')?.value, e=document.getElementById('leaveEnd')?.value, out=document.getElementById('leaveDays');
    if(!s||!e||!out){if(out)out.value='';return;}
    let d=new Date(s+'T00:00:00'), end=new Date(e+'T00:00:00'), n=0;
    if(end<d){out.value='';return;}
    while(d<=end){ if(d.getDay()!==0)n++; d.setDate(d.getDate()+1); }
    out.value=n;
  }
  function submitLeave(){
    const s=document.getElementById('leaveStart').value,e=document.getElementById('leaveEnd').value,c=document.getElementById('leaveComments').value.trim();
    if(!s||!e||!c){showToast('Start Date, End Date and Comments are required.',true);return;}
    showLoading(true); callServer('submitLeaveRequest',{employeeUsername:currentUser.username,startDate:s,endDate:e,comments:c}).then(r=>{showLoading(false);if(!r.success){showToast(r.message,true);return;}showToast('Leave request submitted for approval.');renderLeavePage();}).catch(err=>{showLoading(false);handleError(err);});
  }
  function loadLeaveRequests(){
    showLoading(true); Promise.all([callServer('getLeaveRequests',currentUser.username),callServer('getLeaveAlerts',currentUser.username)]).then(([rows,alerts])=>{
      showLoading(false);
      leaveRequestsCache = Array.isArray(rows) ? rows : [];
      if(isAdminUser()){
        leaveRequestsCache.sort((a,b) => (a.status === 'Pending' ? 0 : 1) - (b.status === 'Pending' ? 0 : 1));
      }
      renderLeaveRequestsTable(leaveRequestsCache);
      if(isApproverUser() && alerts.length){ showToast(alerts.length+' leave item(s) require your attention.'); }
      updateAlertBadge();
    }).catch(err=>{showLoading(false);handleError(err);});
  }
  function renderLeaveRequestsTable(rows){
    const area=document.getElementById('leaveRequestsArea'); if(!area)return;
    // A row is actionable by the current user only if they are the exact
    // stamped ReportingManagerUsername on that row -- the same one-level-up
    // rule the backend enforces, so a manager never sees an Approve/Reject
    // button on a request that isn't actually theirs to review.
    const myKey = String(currentUser.username||'').toLowerCase();
    area.innerHTML=`<table><thead><tr><th>Employee</th><th>From</th><th>To</th><th>Days</th><th>Comments</th><th>Status</th><th>Assigned Approver</th><th>Review Comments</th><th>Action</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${escapeHtml(r.employeeName)}<div class="external-project-meta">${escapeHtml(r.employeeUsername)}</div></td><td>${fmtDate(r.startDate)}</td><td>${fmtDate(r.endDate)}</td><td>${r.numberOfDays}</td><td class="comments-cell">${escapeHtml(r.comments||'—')}</td><td><span class="status-pill status-${statusClass(r.status)}">${escapeHtml(r.status)}</span></td><td>${escapeHtml(r.reportingManagerUsername||'—')}</td><td>${escapeHtml(r.reviewComments||'—')}</td><td>${r.status==='Pending' && String(r.reportingManagerUsername||'').toLowerCase()===myKey ? `<button class="btn btn-primary btn-sm" onclick="reviewLeave('${escapeHtml(r.leaveID)}','Approved')">Approve</button> <button class="btn btn-outline btn-sm" onclick="reviewLeave('${escapeHtml(r.leaveID)}','Rejected')">Reject</button>` : '—'}</td></tr>`).join('')||'<tr><td colspan="9" style="text-align:center;color:var(--gray-500);">No leave requests found.</td></tr>'}</tbody></table>`;
  }
  function reviewLeave(id,decision){
    const answer=prompt('Review comments (optional):','');
    if(answer === null) return;
    const comment=answer;
    showLoading(true); callServer('reviewLeaveRequest',id,currentUser.username,decision,comment).then(r=>{showLoading(false);if(!r.success){showToast(r.message,true);return;}showToast('Leave request '+decision.toLowerCase()+'.');loadLeaveRequests();}).catch(err=>{showLoading(false);handleError(err);});
  }
  function loadAdminLeaveCard(){
    callServer('getLeaveDashboardSummary',currentUser.username).then(rows=>{const el=document.getElementById('adminLeaveCardCount');if(el)el.textContent=(rows||[]).reduce((n,r)=>n+Number(r.numberOfDays||0),0);}).catch(handleError);
  }
  function loadAdminPendingLeaveCount(){
    callServer('getLeaveRequests',currentUser.username).then(rows=>{
      const el=document.getElementById('adminPendingLeaveCount');
      if(el) el.textContent=(Array.isArray(rows)?rows:[]).filter(r=>r.status==='Pending').length;
    }).catch(handleError);
  }
  function openLeaveDashboardCard(){
    if(!isAdminUser() && !isTeamLeaderUser() && !isReportingManagerUser())return;
    showLoading(true); callServer('getLeaveDashboardSummary',currentUser.username).then(rows=>{showLoading(false);rows=Array.isArray(rows)?rows:[];document.getElementById('modalTitle').textContent='Leave';document.getElementById('modalFooter').innerHTML='<button class="btn btn-outline" onclick="closeModal()">Close</button>';document.getElementById('modalOverlay').classList.add('active');document.getElementById('modalBody').innerHTML=`<table><thead><tr><th>Trainer</th><th>Employee ID</th><th>From</th><th>To</th><th>Days</th><th>Status</th><th>Project / Assignment</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${escapeHtml(r.employeeName)}</td><td>${escapeHtml(r.employeeUsername)}</td><td>${fmtDate(r.startDate)}</td><td>${fmtDate(r.endDate)}</td><td>${r.numberOfDays}</td><td><span class="status-pill status-${statusClass(r.status)}">${escapeHtml(r.status)}</span></td><td>${escapeHtml(r.projectName||'—')}${r.projectSource?` (${escapeHtml(r.projectSource)})`:''}</td></tr>`).join('')||'<tr><td colspan="7" style="text-align:center;color:var(--gray-500);">No current leave information.</td></tr>'}</tbody></table>`;}).catch(err=>{showLoading(false);handleError(err);});
  }

  // ---------- DOWNLOAD HELPER ----------
  // Exports whatever table is currently rendered inside the given container
  // to a CSV file, scoped to exactly what that person can already see on
  // screen (their own rows, or their team's, depending on role) -- no
  // separate backend export endpoint needed, so it can never show more
  // than the on-screen table already does.
  function downloadTableAsCSV(containerId, filenamePrefix){
    const table = document.querySelector('#'+containerId+' table');
    if(!table){ showToast('Nothing to download yet.', true); return; }
    const rows = Array.from(table.querySelectorAll('tr')).map(tr =>
      Array.from(tr.querySelectorAll('th,td')).map(cell => {
        const controls = Array.from(cell.querySelectorAll('input,select,textarea')).map(el => el.value).filter(Boolean);
        const text = (controls.length ? controls.join(' | ') : cell.innerText).replace(/\s+/g,' ').trim();
        // Prevent formulas executing when a CSV is opened in a spreadsheet.
        const safe = /^[=+@\-\t\r]/.test(text) ? '\'' + text : text;
        return '"' + safe.replace(/"/g,'""') + '"';
      }).join(',')
    );
    const csv = rows.join('\r\n');
    const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filenamePrefix + '_' + new Date().toISOString().slice(0,10) + '.csv';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ---------- LTMP DAILY ACTIVITY TRACKER ----------
  // Trainer: submits one activity entry at a time (Date, Activity, and — only
  // for "Class Handling" — College/Center + Online/Offline). Reporting
  // ---------- DAILY ACTIVITY TRACKER (unified hierarchy) ----------
  // Trainer / Team Leader / Reporting Manager: each submits their own entry
  // (Date, Activity, and — only for "Class Handling" — College/Center +
  // Online/Offline). Team Leader / Reporting Manager / Admin: reviews
  // entries from whoever reports directly to them, same pattern as Leave.
  let activityMasterCache = [];

  function renderDailyTrackerPage(){
    content(`
      <div class="page-heading"><h1>Daily Tracker</h1><p style="color:var(--gray-500)">Pending = waiting for your assigned immediate manager (Trainer → Team Leader → Reporting Manager → Admin). Only your assigned reviewer can approve or reject.</p></div>
      ${isSubmitterUser() ? `
        <div class="section-header"><h3>Log Today's Activity</h3></div>
        <div class="card" style="max-width:860px;padding:20px;margin-bottom:22px;">
          <div class="form-row">
            <div class="field"><label>Date</label><input id="dtDate" type="date"></div>
            <div class="field"><label>Activity</label><select id="dtActivity" onchange="onDtActivityChange()"><option value="">Select Activity…</option></select></div>
          </div>
          <div class="form-row" id="dtClassFieldsRow" style="display:none;">
            <div class="field"><label>College / Center</label><select id="dtCollege"><option value="">Select…</option></select></div>
            <div class="field"><label>Online / Offline</label><select id="dtMode"><option value="">Select…</option><option>Online</option><option>Offline</option></select></div>
          </div>
          <div class="form-row">
            <div class="field"><label>Topic Covered / Work Done</label><textarea id="dtTopic" rows="2" placeholder="Describe what was covered"></textarea></div>
            <div class="field" style="max-width:140px;"><label>Hours</label><input id="dtHours" type="number" min="0.5" step="0.5" placeholder="e.g. 1.5"></div>
          </div>
          <button class="btn btn-red" onclick="submitDailyActivityEntry()">Submit</button>
        </div>
        <div class="section-header"><h3>My Daily Tracker Entries</h3>
          <button class="btn btn-outline btn-sm download-btn" onclick="downloadTableAsCSV('dtMyEntriesArea','my_daily_tracker')">Download</button>
        </div>
        <div id="dtMyEntriesArea" style="margin-bottom:26px;"></div>` : ''}
      ${isApproverUser() ? `
        <div class="section-header"><h3>Team's Daily Tracker Entries</h3>
          <button class="btn btn-outline btn-sm download-btn" onclick="downloadTableAsCSV('dtEntriesArea','team_daily_tracker')">Download</button>
        </div>
        <div class="filter-bar"><input type="text" id="dtFilterInput" placeholder="Filter by Employee ID or Name" oninput="filterDailyTrackerEntries()"></div>
        <div id="dtEntriesArea"></div>` : ''}
    `);
    showLoading(true);
    callServer('getActivityMaster').then(list => {
      showLoading(false);
      activityMasterCache = Array.isArray(list) ? list : [];
      const sel = document.getElementById('dtActivity');
      if (sel) sel.innerHTML = '<option value="">Select Activity…</option>' +
        activityMasterCache.map(a => `<option value="${escapeHtml(a.code)}">${escapeHtml(a.name)} (${escapeHtml(a.code)})</option>`).join('');
    }).catch(err => { showLoading(false); handleError(err); });
    if (isSubmitterUser()) {
      callServer('getClassLocationOptions').then(names => {
        const sel = document.getElementById('dtCollege');
        if (sel) sel.innerHTML = '<option value="">Select…</option>' + (names||[]).map(n => `<option>${escapeHtml(n)}</option>`).join('');
      });
      loadMyDailyTrackerEntries();
    }
    if (isApproverUser()) loadDailyTrackerEntries();
  }

  function onDtActivityChange(){
    const code = document.getElementById('dtActivity')?.value;
    const activity = activityMasterCache.find(a => a.code === code);
    const isClassHandling = activity && activity.name === 'Class Handling';
    const row = document.getElementById('dtClassFieldsRow');
    if (row) row.style.display = isClassHandling ? '' : 'none';
  }

  function submitDailyActivityEntry(){
    const payload = {
      trainerUsername: currentUser.username,
      date: document.getElementById('dtDate').value,
      activityCode: document.getElementById('dtActivity').value,
      topicCovered: document.getElementById('dtTopic').value.trim(),
      hours: document.getElementById('dtHours').value,
      collegeName: document.getElementById('dtCollege')?.value || '',
      classMode: document.getElementById('dtMode')?.value || ''
    };
    if(!payload.date || !payload.activityCode){ showToast('Date and Activity are required.', true); return; }
    showLoading(true);
    callServer('submitDailyActivity', payload).then(r => {
      showLoading(false);
      if(!r.success){ showToast(r.message || 'Could not submit entry.', true); return; }
      showToast('Daily Tracker entry submitted for approval.');
      renderDailyTrackerPage();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function loadMyDailyTrackerEntries(){
    const area = document.getElementById('dtMyEntriesArea');
    if(!area) return;
    showLoading(true);
    callServer('getMyDailyActivities', currentUser.username).then(rows => {
      showLoading(false);
      rows = Array.isArray(rows) ? rows : [];
      area.innerHTML = `<table><thead><tr><th>Date</th><th>Activity</th><th>College / Mode</th><th>Work Covered</th><th>Hours</th><th>Approval Status</th><th>Assigned Reviewer</th><th>Review Comments</th></tr></thead><tbody>${
        rows.map(r => `<tr>
          <td>${fmtDate(r.date)}</td>
          <td>${escapeHtml(r.activityName)}</td>
          <td>${r.collegeName && r.collegeName !== 'In-House' ? escapeHtml(r.collegeName) + (r.classMode ? ' · ' + escapeHtml(r.classMode) : '') : 'In-House'}</td>
          <td class="comments-cell">${escapeHtml(r.topicCovered || '—')}</td>
          <td>${r.hours}</td>
          <td><span class="status-pill status-${statusClass(r.status)}">${escapeHtml(r.status)}</span></td>
          <td>${escapeHtml(r.approverUsername || '—')}</td>
          <td>${escapeHtml(r.reviewComments || '—')}</td>
        </tr>`).join('') || `<tr><td colspan="8" style="text-align:center;color:var(--gray-500);">No Daily Tracker entries found.</td></tr>`
      }</tbody></table>`;
    }).catch(err => { showLoading(false); handleError(err); });
  }

  let dailyTrackerApprovalsCache = [];
  function filterDailyTrackerEntries(){
    const q = (document.getElementById('dtFilterInput')?.value || '').trim().toLowerCase();
    const filtered = q ? dailyTrackerApprovalsCache.filter(r =>
      String(r.trainerUsername||'').toLowerCase().includes(q) || String(r.trainerName||'').toLowerCase().includes(q)
    ) : dailyTrackerApprovalsCache;
    renderDailyTrackerApprovalsTable(filtered);
  }

  function loadDailyTrackerEntries(){
    const area = document.getElementById('dtEntriesArea');
    if(!area) return;
    showLoading(true);
    callServer('getDailyActivityApprovals', currentUser.username).then(rows => {
      showLoading(false);
      dailyTrackerApprovalsCache = Array.isArray(rows) ? rows : [];
      renderDailyTrackerApprovalsTable(dailyTrackerApprovalsCache);
      updateAlertBadge();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function renderDailyTrackerApprovalsTable(rows){
    const area = document.getElementById('dtEntriesArea');
    if(!area) return;
    area.innerHTML = `<table><thead><tr><th>Employee</th><th>Date</th><th>Activity</th><th>College / Mode</th><th>Work Covered</th><th>Hours</th><th>Status</th><th>Action</th></tr></thead><tbody>${
      rows.map(r => `<tr>
        <td>${escapeHtml(r.trainerName)}<div class="external-project-meta">${escapeHtml(r.trainerUsername)}</div></td>
        <td>${fmtDate(r.date)}</td>
        <td>${escapeHtml(r.activityName)}</td>
        <td>${r.collegeName && r.collegeName !== 'In-House' ? escapeHtml(r.collegeName) + (r.classMode ? ' · ' + escapeHtml(r.classMode) : '') : 'In-House'}</td>
        <td class="comments-cell">${escapeHtml(r.topicCovered || '—')}</td>
        <td>${r.hours}</td>
        <td><span class="status-pill status-${statusClass(r.status)}">${escapeHtml(r.status)}</span></td>
        <td>${r.status==='Pending' ? `<button class="btn btn-primary btn-sm" onclick="reviewDailyTrackerEntry('${escapeHtml(r.entryID)}','Approved')">Approve</button> <button class="btn btn-outline btn-sm" onclick="reviewDailyTrackerEntry('${escapeHtml(r.entryID)}','Rejected')">Reject</button>` : '—'}</td>
      </tr>`).join('') || `<tr><td colspan="8" style="text-align:center;color:var(--gray-500);">No Daily Tracker entries found.</td></tr>`
    }</tbody></table>`;
  }

  function reviewDailyTrackerEntry(entryID, decision){
    const comment = prompt('Review comments (optional):', '');
    if(comment === null) return;
    showLoading(true);
    callServer('reviewDailyActivity', entryID, currentUser.username, decision, comment).then(r => {
      showLoading(false);
      if(!r.success){ showToast(r.message || 'Could not review entry.', true); return; }
      showToast('Daily Tracker entry ' + decision.toLowerCase() + '.');
      loadDailyTrackerEntries();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  // ---------- ACTIVITY MASTER (ADMIN) ----------
  function renderActivityMaster(){
    if(!isAdminUser()){ content('<div class="empty-state">Only Admin can manage the Activity Master.</div>'); return; }
    content(`
      <div class="page-heading"><h1>Activity Master</h1></div>
      <button class="btn btn-outline btn-sm" style="margin-bottom:14px;" onclick="openCreateActivity()">+ Add Activity</button>
      <div id="activityMasterArea"></div>
    `);
    loadActivityMaster();
  }

  function loadActivityMaster(){
    const area = document.getElementById('activityMasterArea');
    if(!area) return;
    showLoading(true);
    callServer('getActivityMasterAdmin', currentUser.username).then(rows => {
      showLoading(false);
      rows = Array.isArray(rows) ? rows : [];
      area.innerHTML = `<table><thead><tr><th>Activity Code</th><th>Activity Name</th><th>Status</th><th>Action</th></tr></thead><tbody>${
        rows.map(a => `<tr><td>${escapeHtml(a.code)}</td><td>${escapeHtml(a.name)}</td><td><span class="status-pill status-${a.active?'Running':'NotActive'}">${a.active?'Active':'Inactive'}</span></td><td><button class="btn btn-outline btn-sm" onclick="toggleActivityActive('${escapeHtml(a.code)}',${!a.active})">${a.active?'Deactivate':'Activate'}</button></td></tr>`).join('') ||
        '<tr><td colspan="4" style="text-align:center;color:var(--gray-500);">No activities defined yet.</td></tr>'
      }</tbody></table>`;
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function openCreateActivity(){
    document.getElementById('modalTitle').textContent = 'Add Activity';
    document.getElementById('modalBody').innerHTML = `
      <div class="field"><label>Activity Code</label><input id="newActivityCode" placeholder="e.g. T25026"></div>
      <div class="field"><label>Activity Name</label><input id="newActivityName" placeholder="e.g. Content Review"></div>
    `;
    document.getElementById('modalFooter').innerHTML = `<button class="btn btn-outline" onclick="closeModal()">Cancel</button><button class="btn btn-red" onclick="submitCreateActivity()">Save</button>`;
    document.getElementById('modalOverlay').classList.add('active');
  }

  function submitCreateActivity(){
    const code = document.getElementById('newActivityCode').value.trim();
    const name = document.getElementById('newActivityName').value.trim();
    if(!code || !name){ showToast('Activity Code and Name are required.', true); return; }
    showLoading(true);
    callServer('createActivityMaster', { code, name, createdBy: currentUser.username }).then(r => {
      showLoading(false);
      if(!r.success){ showToast(r.message || 'Could not add activity.', true); return; }
      showToast('Activity added.');
      closeModal();
      renderActivityMaster();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function toggleActivityActive(code, active){
    showLoading(true);
    callServer('setActivityMasterActive', code, active, currentUser.username).then(() => {
      showLoading(false);
      renderActivityMaster();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  // ---------- REPORTS ----------
  // ---------- KPI MODULE ----------
  // Same one-level-up hierarchy as everything else: Trainer -> Team Leader
  // -> Reporting Manager -> Admin. "My KPIs" is a person's own ratings
  // (including Admin's own, auto-approved since nobody sits above Admin).
  // "Team KPIs" is whoever reports directly to the current user's ratings,
  // shown to Team Leader / Reporting Manager / Admin only.
  let kpiDashboardCache = { myKpis: [], teamKpis: [] };

  function renderKpiPage(){
    content(`
      <div class="page-heading"><h1>KPI</h1>${isAdminUser() ? '<button class="btn btn-outline btn-sm" onclick="openKpiMasterManager()">Manage KPI Parameters</button>' : ''}</div>
      <div class="section-header"><h3>My KPIs</h3>
        <button class="btn btn-outline btn-sm download-btn" onclick="downloadTableAsCSV('myKpisArea','my_kpi')">Download</button>
      </div>
      <div id="myKpisArea"></div>
      ${isApproverUser() ? `
        <div class="section-header" style="margin-top:26px;"><h3>Team KPIs</h3>
          <button class="btn btn-outline btn-sm download-btn" onclick="downloadTableAsCSV('teamKpisArea','team_kpi')">Download</button>
        </div>
        <div class="filter-bar"><input type="text" id="kpiFilterInput" placeholder="Filter by Employee ID or Name" oninput="filterTeamKpis()"></div>
        <div id="teamKpisArea"></div>` : ''}
    `);
    loadKpiDashboard();
  }

  function loadKpiDashboard(){
    showLoading(true);
    callServer('getKpiDashboardData', currentUser.username).then(data => {
      showLoading(false);
      kpiDashboardCache = data || { myKpis: [], teamKpis: [] };
      renderMyKpisTable(kpiDashboardCache.myKpis || []);
      if(isApproverUser()) renderTeamKpisTable(kpiDashboardCache.teamKpis || []);
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function renderMyKpisTable(rows){
    const area = document.getElementById('myKpisArea');
    if(!area) return;
    area.innerHTML = `<table><thead><tr><th>Category</th><th>Parameter</th><th>Target</th><th>Rating</th><th>Status</th><th>Action</th></tr></thead><tbody>${
      rows.map(r => {
        const editable = (r.status === 'Pending' || r.status === 'Returned');
        return `<tr>
          <td>${escapeHtml(r.category)}</td>
          <td>${escapeHtml(r.parameter)}</td>
          <td>${escapeHtml(r.target)}</td>
          <td>${editable
            ? `<input type="number" min="0" step="0.5" id="myKpiRating_${r.kpiId}" value="${r.rating != null ? r.rating : ''}" style="width:70px;">`
            : (r.rating != null ? r.rating : '—')}</td>
          <td><span class="status-pill status-${statusClass(r.status)}">${escapeHtml(r.status)}</span>${r.status==='Returned' && r.returnReason ? `<div class="external-project-meta">${escapeHtml(r.returnReason)}</div>` : ''}</td>
          <td>${editable ? `<button class="btn btn-primary btn-sm" onclick="submitMyKpiRating(${r.kpiId})">Submit</button>` : '—'}</td>
        </tr>`;
      }).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--gray-500);">No KPI parameters found.</td></tr>'
    }</tbody></table>`;
  }

  function submitMyKpiRating(kpiId){
    const input = document.getElementById('myKpiRating_' + kpiId);
    const rating = input ? input.value : '';
    if(rating === '' || isNaN(Number(rating))){ showToast('Please enter a valid rating.', true); return; }
    showLoading(true);
    callServer('submitRating', currentUser.username, kpiId, Number(rating)).then(r => {
      showLoading(false);
      if(!r.success){ showToast(r.message || 'Could not submit rating.', true); return; }
      showToast('KPI rating submitted.');
      loadKpiDashboard(); updateAlertBadge();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  let teamKpisFlatCache = [];
  function renderTeamKpisTable(rows){
    teamKpisFlatCache = rows;
    filterTeamKpis();
  }
  function filterTeamKpis(){
    const q = (document.getElementById('kpiFilterInput')?.value || '').trim().toLowerCase();
    const rows = q ? teamKpisFlatCache.filter(r =>
      String(r.employeeId||'').toLowerCase().includes(q) || String(r.employeeName||'').toLowerCase().includes(q)
    ) : teamKpisFlatCache;
    const area = document.getElementById('teamKpisArea');
    if(!area) return;
    area.innerHTML = `<table><thead><tr><th>Employee</th><th>Category</th><th>Parameter</th><th>Target</th><th>Rating</th><th>Status</th><th>Action</th></tr></thead><tbody>${
      rows.map(r => `<tr>
        <td>${escapeHtml(r.employeeName)}<div class="external-project-meta">${escapeHtml(r.employeeId)}</div></td>
        <td>${escapeHtml(r.category)}</td>
        <td>${escapeHtml(r.parameter)}</td>
        <td>${escapeHtml(r.target)}</td>
        <td>${r.rating != null ? r.rating : '—'}</td>
        <td><span class="status-pill status-${statusClass(r.status)}">${escapeHtml(r.status)}</span></td>
        <td>${
          r.status === 'Submitted'
            ? `<button class="btn btn-primary btn-sm" onclick="decideKpiRating(${r.kpiId},'${escapeHtml(r.employeeId)}','Approved')">Approve</button> <button class="btn btn-outline btn-sm" onclick="decideKpiRating(${r.kpiId},'${escapeHtml(r.employeeId)}','Returned')">Return</button>`
            : (r.status === 'Approved'
              ? `<button class="btn btn-outline btn-sm" onclick="reopenKpiRating(${r.kpiId},'${escapeHtml(r.employeeId)}')">Reopen</button>`
              : '—')
        }</td>
      </tr>`).join('') || '<tr><td colspan="7" style="text-align:center;color:var(--gray-500);">No team KPI entries found.</td></tr>'
    }</tbody></table>`;
  }

  function decideKpiRating(kpiId, employeeUsername, decision){
    const reason = decision === 'Returned' ? (prompt('Reason for returning this rating:', '') || '') : '';
    showLoading(true);
    callServer('decideOnRating', currentUser.username, kpiId, employeeUsername, decision, reason).then(r => {
      showLoading(false);
      if(!r.success){ showToast(r.message || 'Could not update rating.', true); return; }
      showToast('KPI rating ' + decision.toLowerCase() + '.');
      loadKpiDashboard(); updateAlertBadge();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function reopenKpiRating(kpiId, employeeUsername){
    showLoading(true);
    callServer('unlockRating', currentUser.username, kpiId, employeeUsername).then(r => {
      showLoading(false);
      if(!r.success){ showToast(r.message || 'Could not reopen rating.', true); return; }
      showToast('KPI rating reopened for revision.');
      loadKpiDashboard(); updateAlertBadge();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  // ---------- KPI MASTER MANAGEMENT (Admin) ----------
  function openKpiMasterManager(){
    if(!isAdminUser()) return;
    document.getElementById('modalTitle').textContent = 'KPI Parameters';
    document.getElementById('modalFooter').innerHTML = `
      <button class="btn btn-outline" onclick="closeModal()">Close</button>
      <button class="btn btn-red" onclick="openKpiParameterForm(null)">+ Add Parameter</button>
    `;
    document.getElementById('modalOverlay').classList.add('active');
    loadKpiMasterList();
  }

  function loadKpiMasterList(){
    showLoading(true);
    callServer('getKpiMasterForAdmin', currentUser.username).then(rows => {
      showLoading(false);
      rows = Array.isArray(rows) ? rows : [];
      document.getElementById('modalBody').innerHTML = `<table><thead><tr><th>Category</th><th>Parameter</th><th>Target</th><th></th></tr></thead><tbody>${
        rows.map(k => `<tr>
          <td>${escapeHtml(k.category)}</td><td>${escapeHtml(k.parameter)}</td><td>${escapeHtml(k.target)}</td>
          <td><button class="btn btn-outline btn-sm" onclick='openKpiParameterForm(${JSON.stringify(k)})'>Edit</button>
          <button class="btn btn-outline btn-sm" onclick="deleteKpiParameter(${k.id})">Delete</button></td>
        </tr>`).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--gray-500);">No KPI parameters yet.</td></tr>'
      }</tbody></table>`;
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function openKpiParameterForm(kpi){
    document.getElementById('modalTitle').textContent = kpi ? 'Edit KPI Parameter' : 'Add KPI Parameter';
    document.getElementById('modalBody').innerHTML = `
      <div class="form-row">
        <div class="field"><label>Category</label><input id="kpiCategory" value="${kpi ? escapeHtml(kpi.category) : ''}"></div>
        <div class="field"><label>Target (e.g. 5%)</label><input id="kpiTarget" value="${kpi ? escapeHtml(kpi.target) : ''}"></div>
      </div>
      <div class="field"><label>Parameter</label><textarea id="kpiParameter" rows="2">${kpi ? escapeHtml(kpi.parameter) : ''}</textarea></div>
    `;
    document.getElementById('modalFooter').innerHTML = `
      <button class="btn btn-outline" onclick="openKpiMasterManager()">Cancel</button>
      <button class="btn btn-red" onclick="saveKpiParameter(${kpi ? kpi.id : 'null'})">Save</button>
    `;
  }

  function saveKpiParameter(id){
    const payload = {
      id: id, category: document.getElementById('kpiCategory').value.trim(),
      parameter: document.getElementById('kpiParameter').value.trim(),
      target: document.getElementById('kpiTarget').value.trim()
    };
    if(!payload.category || !payload.parameter || !payload.target){ showToast('Category, Parameter, and Target are all required.', true); return; }
    showLoading(true);
    callServer('saveKpiMaster', currentUser.username, payload).then(r => {
      showLoading(false);
      if(!r.success){ showToast(r.message || 'Could not save KPI parameter.', true); return; }
      showToast('KPI parameter saved.');
      openKpiMasterManager();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function deleteKpiParameter(id){
    if(!confirm('Delete this KPI parameter? Every rating already given against it will be deleted too.')) return;
    showLoading(true);
    callServer('deleteKpiMaster', currentUser.username, id).then(r => {
      showLoading(false);
      if(!r.success){ showToast(r.message || 'Could not delete KPI parameter.', true); return; }
      showToast('KPI parameter deleted.');
      loadKpiMasterList();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  function renderReports(){
    content(`
      <div class="page-heading"><h1>Reports</h1><button class="btn btn-outline btn-sm download-btn" onclick="downloadTableAsCSV('reportPanel','report')">Download</button></div>
      <div class="tab-bar" id="reportTabs"></div>
      <div class="tab-panel" id="reportPanel"></div>
    `);
    const tabs = [
      {id:'collegewise', label:'College-wise'},
      {id:'trainerwise', label:'Trainer-wise'},
      {id:'statuswise', label:'Status-wise'},
      {id:'categorywise', label:'Category-wise Progress'},
      {id:'attendance', label:'Attendance'}
    ];
    if(isAdminUser()) tabs.push({id:'activityreport', label:'Trainer Activity Report'});
    document.getElementById('reportTabs').innerHTML = tabs.map((t,i) =>
      `<button class="tab-btn ${i===0?'active':''}" data-rtab="${t.id}" onclick="switchReportTab('${t.id}')">${t.label}</button>`).join('');
    switchReportTab('collegewise');
  }
  function switchReportTab(tab){
    document.querySelectorAll('#reportTabs .tab-btn').forEach(b => b.classList.toggle('active', b.dataset.rtab === tab));
    const panel = document.getElementById('reportPanel');
    panel.innerHTML = '<div class="empty-state">Loading…</div>';
    if(tab === 'collegewise'){
      callServer('getCollegeWiseReport').then(rows => {
        panel.innerHTML = `<table><thead><tr><th>Code</th><th>College</th><th>Status</th><th>Total Days</th><th>Progress</th><th>Trainers</th><th>Attendance</th></tr></thead><tbody>${
          rows.map(r => `<tr><td>${escapeHtml(r.collegeCode)}</td><td><div class="table-logo">${r.logoURL ? `<img src="${escapeHtml(r.logoURL)}">` : ''}<span>${escapeHtml(r.collegeName)}</span></div></td><td>${escapeHtml(r.status)}</td><td>${r.totalPlannedDays}</td><td>${r.progressPercent}%</td><td>${r.trainerCount}</td><td>${r.avgAttendance}%</td></tr>`).join('') || '<tr><td colspan="7">No data</td></tr>'
        }</tbody></table>`;
      });
    } else if(tab === 'trainerwise'){
      callServer('getTrainerWiseReport').then(rows => {
        panel.innerHTML = `<table><thead><tr><th>Trainer</th><th>Assigned Colleges</th><th>Sessions Submitted</th></tr></thead><tbody>${
          rows.map(r => `<tr><td>${escapeHtml(r.trainerName)}</td><td>${r.assignedColleges}</td><td>${r.sessionsSubmitted}</td></tr>`).join('') || '<tr><td colspan="3">No data</td></tr>'
        }</tbody></table>`;
      });
    } else if(tab === 'statuswise'){
      callServer('getStatusWiseReport').then(grouped => {
        panel.innerHTML = Object.keys(grouped).map(status => `
          <div style="margin-bottom:18px;"><b>${escapeHtml(status)}</b> (${grouped[status].length})
          <ul>${grouped[status].map(n => `<li>${escapeHtml(n)}</li>`).join('')}</ul></div>
        `).join('') || '<div class="empty-state">No data</div>';
      });
    } else if(tab === 'categorywise'){
      callServer('getCategoryWiseProgress').then(rows => {
        panel.innerHTML = `<table><thead><tr><th>Category</th><th>Planned Days</th><th>Completed Days</th><th>Progress</th></tr></thead><tbody>${
          rows.map(r => `<tr><td>${escapeHtml(r.category)}</td><td>${r.plannedDays}</td><td>${r.completedDays}</td><td>${r.progressPercent}%</td></tr>`).join('') || '<tr><td colspan="4">No data</td></tr>'
        }</tbody></table>`;
      });
    } else if(tab === 'attendance'){
      callServer('getAttendanceReport').then(rows => {
        panel.innerHTML = `<table><thead><tr><th>College</th><th>Avg. Attendance</th></tr></thead><tbody>${
          rows.map(r => `<tr><td><div class="table-logo">${r.logoURL ? `<img src="${escapeHtml(r.logoURL)}">` : ''}<span>${escapeHtml(r.collegeName)}</span></div></td><td>${r.avgAttendance}%</td></tr>`).join('') || '<tr><td colspan="2">No data</td></tr>'
        }</tbody></table>`;
      });
    } else if(tab === 'activityreport'){
      loadTrainerActivityReport('');
    }
  }

  // Admin-only aggregated view of Daily Tracker activity — counts and total
  // hours per Trainer per Activity, for a chosen month. No individual entry
  // detail (Topic/College) is shown here, by design.
  let activityReportCache = [];
  function loadTrainerActivityReport(monthKey){
    const panel = document.getElementById('reportPanel');
    panel.innerHTML = '<div class="empty-state">Loading…</div>';
    Promise.all([
      callServer('getDailyActivityAvailableMonths'),
      callServer('getTrainerActivityReport', monthKey || '')
    ]).then(([months, rows]) => {
      months = Array.isArray(months) ? months : [];
      rows = Array.isArray(rows) ? rows : [];
      activityReportCache = rows;
      const selected = monthKey || (months[0] || '');
      panel.innerHTML = `
        <div class="form-row" style="align-items:flex-end;margin-bottom:14px;">
          <div class="field" style="max-width:220px;">
            <label>Month</label>
            <select id="activityReportMonth" onchange="loadTrainerActivityReport(this.value)">
              <option value="">All Months</option>
              ${months.map(m => `<option value="${m}" ${m===selected?'selected':''}>${m}</option>`).join('')}
            </select>
          </div>
          <button class="btn btn-outline btn-sm" onclick="exportTrainerActivityReport()">Export CSV</button>
        </div>
        <table><thead><tr><th>Trainer</th><th>Activity</th><th>Count</th><th>Total Hours</th></tr></thead><tbody>${
          rows.map(r => `<tr><td>${escapeHtml(r.trainerName)}</td><td>${escapeHtml(r.activityName)}</td><td>${r.count}</td><td>${r.totalHours}</td></tr>`).join('') ||
          '<tr><td colspan="4" style="text-align:center;color:var(--gray-500);">No approved Daily Tracker entries for this period.</td></tr>'
        }</tbody></table>
      `;
    }).catch(err => handleError(err));
  }

  function exportTrainerActivityReport(){
    if(!activityReportCache.length){ showToast('Nothing to export.', true); return; }
    const header = 'Trainer,Activity,Count,Total Hours\n';
    const body = activityReportCache.map(r =>
      `"${String(r.trainerName).replace(/"/g,'""')}","${String(r.activityName).replace(/"/g,'""')}",${r.count},${r.totalHours}`
    ).join('\n');
    const blob = new Blob([header + body], {type:'text/csv'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'Trainer_Activity_Report.csv';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ---------- USER MANAGEMENT (Admin) ----------
  function renderUsers(){
    content(`
      <div class="page-heading"><h1>User Management</h1><button class="btn btn-red" onclick="openCreateUser()">+ Add User</button></div>
      <div class="filter-bar"><input type="text" id="userFilterInput" placeholder="Filter by Employee ID or Name" oninput="filterUsersTable()"></div>
      <div id="usersArea"></div>
    `);
    showLoading(true);
    callServer('getUsers').then(users => {
      showLoading(false);
      usersTableCache = Array.isArray(users) ? users : [];
      renderUsersTable(usersTableCache);
    }).catch(err => { showLoading(false); handleError(err); });
  }
  let usersTableCache = [];
  function filterUsersTable(){
    const q = (document.getElementById('userFilterInput')?.value || '').trim().toLowerCase();
    const filtered = q ? usersTableCache.filter(u =>
      String(u.username||'').toLowerCase().includes(q) || String(u.fullName||'').toLowerCase().includes(q)
    ) : usersTableCache;
    renderUsersTable(filtered);
  }
  function renderUsersTable(users){
    document.getElementById('usersArea').innerHTML = `
      <table><thead><tr><th>Employee ID</th><th>Full Name</th><th>Role</th><th>Designation</th><th>Reports To</th><th>Email</th><th>Status</th><th></th></tr></thead>
      <tbody>${users.map(u => `
        <tr><td>${escapeHtml(u.username)}</td><td>${escapeHtml(u.fullName)}</td><td>${escapeHtml(u.role)}</td>
        <td>${u.role === 'Admin' ? `<select id="desig_${escapeHtml(u.username)}"><option value="">— none —</option></select><button class="btn btn-outline btn-sm" style="margin-left:6px;" onclick="saveUserDesignation('${escapeHtml(u.username)}')">Save</button>` : '—'}</td>
        <td>${u.role !== 'Admin' ? `<select id="rm_${escapeHtml(u.username)}" data-role="${escapeHtml(u.role)}" data-current-rm="${escapeHtml(u.reportingManagerUsername || '')}"><option value="">Select…</option></select><button class="btn btn-outline btn-sm" style="margin-left:6px;" onclick="saveUserReportingManager('${escapeHtml(u.username)}')">Save</button>` : '—'}</td>
        <td>${escapeHtml(u.email)}</td>
        <td>${(u.active === true || u.active === 'TRUE') ? 'Active' : 'Inactive'}</td>
        <td><button class="btn btn-outline btn-sm" onclick="toggleUserActive('${u.username}', ${!(u.active === true || u.active === 'TRUE')})">${(u.active === true || u.active === 'TRUE') ? 'Deactivate' : 'Activate'}</button></td></tr>
      `).join('')}</tbody></table>
    `;
    // Each reporting-manager dropdown is populated with the CORRECT tier
    // for that row's role (Trainer -> Team Leaders, Team Leader -> Reporting
    // Managers, Reporting Manager -> Admins) — never a flat list of RMs.
    document.querySelectorAll('select[id^="rm_"]').forEach(sel => {
      const role = sel.dataset.role;
      callServer('getManagersForRole', role).then(mgrs => {
        const current = sel.dataset.currentRm || '';
        sel.innerHTML = '<option value="">Select…</option>' + (mgrs||[]).map(m =>
          `<option value="${escapeHtml(m.username)}" ${m.username===current?'selected':''}>${escapeHtml(m.fullName)} (${escapeHtml(m.username)})</option>`).join('');
      });
    });
    callServer('getAdminDesignationOptions').then(options => {
      document.querySelectorAll('select[id^="desig_"]').forEach(sel => {
        const username = sel.id.replace('desig_','');
        const current = (usersTableCache.find(u => u.username === username) || {}).designation || '';
        sel.innerHTML = '<option value="">— none —</option>' + (options||[]).map(o =>
          `<option value="${escapeHtml(o)}" ${o===current?'selected':''}>${escapeHtml(o)}</option>`).join('');
      });
    });
  }
  function saveUserDesignation(username){
    if(!isAdminUser()){showToast('Only Admin can update designations.',true);return;}
    const val=document.getElementById('desig_'+username)?.value || '';
    showLoading(true); callServer('setUserDesignation',username,val,currentUser.username).then(r=>{showLoading(false);if(!r.success){showToast(r.message,true);return;}showToast('Designation updated.');renderUsers();}).catch(err=>{showLoading(false);handleError(err);});
  }
  function saveUserReportingManager(username){
    if(!isAdminUser()){showToast('Only Admin can update reporting mappings.',true);return;}
    const rm=document.getElementById('rm_'+username)?.value;
    if(!rm){showToast('Please select a reporting manager.',true);return;}
    showLoading(true); callServer('updateReportingManagerMapping',username,rm,currentUser.username).then(r=>{showLoading(false);if(!r.success){showToast(r.message,true);return;}showToast('Reporting manager updated.');renderUsers();}).catch(err=>{showLoading(false);handleError(err);});
  }
  function toggleUserActive(username, active){
    showLoading(true);
    if(!isAdminUser()){ showToast('Only Admin can change user status.', true); return; }
    callServer('setUserActive', username, active, currentUser.username).then(() => { showLoading(false); renderUsers(); }).catch(err => { showLoading(false); handleError(err); });
  }
  function openCreateUser(){
    document.getElementById('modalTitle').textContent = 'Add User';
    document.getElementById('modalBody').innerHTML = `
      <div class="form-row">
        <div class="field"><label>Employee ID</label><input id="nuUsername" placeholder="Also used to log in"></div>
        <div class="field"><label>Full Name</label><input id="nuFullName"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>Role</label><select id="nuRole" onchange="onCreateUserRoleChange()"><option>Trainer</option><option>Team Leader</option><option>Reporting Manager</option><option>Admin</option></select></div>
        <div class="field"><label>Temporary Password</label><input id="nuPassword" placeholder="Default: lesuccess@123"></div>
      </div>
      <div class="form-row">
        <div class="field" id="nuRMField"><label>Reports To</label><select id="nuRM"><option value="">Select…</option></select></div>
        <div class="field" id="nuDesigField" style="display:none;"><label>Designation</label><select id="nuDesignation"><option value="">— none —</option></select></div>
        <div class="field"><label>Email</label><input id="nuEmail"></div>
        <div class="field"><label>Phone</label><input id="nuPhone"></div>
      </div>
    `;
    document.getElementById('modalFooter').innerHTML = `
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-red" onclick="submitCreateUser()">Create User</button>
    `;
    document.getElementById('modalOverlay').classList.add('active');
    onCreateUserRoleChange();
  }
  function onCreateUserRoleChange(){
    const role = document.getElementById('nuRole')?.value || 'Trainer';
    const rmField = document.getElementById('nuRMField');
    const desigField = document.getElementById('nuDesigField');
    if(role === 'Admin'){
      if(rmField) rmField.style.display = 'none';
      if(desigField) desigField.style.display = '';
      callServer('getAdminDesignationOptions').then(options => {
        const sel = document.getElementById('nuDesignation'); if(!sel) return;
        sel.innerHTML = '<option value="">— none —</option>' + (options||[]).map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('');
      });
    } else {
      if(rmField) rmField.style.display = '';
      if(desigField) desigField.style.display = 'none';
      callServer('getManagersForRole', role).then(mgrs => {
        const sel = document.getElementById('nuRM'); if(!sel) return;
        sel.innerHTML = '<option value="">Select…</option>' + (mgrs||[]).map(m => `<option value="${escapeHtml(m.username)}">${escapeHtml(m.fullName)} (${escapeHtml(m.username)})</option>`).join('');
      });
    }
  }
  function submitCreateUser(){
    const role = document.getElementById('nuRole').value;
    const payload = {
      employeeId: document.getElementById('nuUsername').value.trim(),
      fullName: document.getElementById('nuFullName').value.trim(),
      role: role,
      password: document.getElementById('nuPassword').value.trim(),
      email: document.getElementById('nuEmail').value.trim(),
      phone: document.getElementById('nuPhone').value.trim(),
      reportingManagerUsername: role === 'Admin' ? '' : document.getElementById('nuRM').value,
      designation: role === 'Admin' ? (document.getElementById('nuDesignation')?.value || '') : '',
      createdBy: currentUser.username
    };
    if(!isAdminUser()){ showToast('Only Admin can create users.', true); return; }
    if(!payload.employeeId || !payload.fullName){ showToast('Employee ID and full name are required.', true); return; }
    showLoading(true);
    callServer('createUser', payload).then(res => {
      showLoading(false);
      if(!res.success){ showToast(res.message, true); return; }
      showToast('User created.');
      closeModal();
      renderUsers();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  // ---------- REPORTING MANAGER / TEAM LEADER: APPROVALS ----------
  function renderApprovals(){
    if(!isReportingManagerUser() && !isAdminUser()){
      content('<div class="empty-state">Only Reporting Manager or Admin can review training updates.</div>');
      return;
    }
    content('<div class="page-heading"><h1>Training Update Approvals</h1><p>LeSuccess, Vendor and Freelancer submissions assigned to you.</p></div><div id="approvalsArea"></div>');
    showLoading(true);
    callServer('getPendingApprovals', null).then(rows => {
      showLoading(false);
      const area = document.getElementById('approvalsArea');

      // Apps Script should return an array, but guard the UI as well so a
      // missing/empty response can never cause `rows.length` / `rows.map`
      // errors.
      rows = Array.isArray(rows) ? rows : [];

      if(rows.length === 0){
        area.innerHTML = `
          <div class="empty-state">
            <div style="font-size:15px;font-weight:700;margin-bottom:6px;">No Pending Syllabus Approvals</div>
            <div style="color:var(--gray-500);">Trainer submissions will appear here after they submit a daily training update.</div>
          </div>
        `;
        return;
      }

      area.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Project Type</th>
              <th>Project / College</th>
              <th>Category</th>
              <th>Topic</th>
              <th>Trainer</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map(r => `
              <tr>
                <td>${escapeHtml(r.ProjectType || 'LeSuccess')}</td>
                <td>${escapeHtml(r.CollegeName || r.CollegeCode || '—')}</td>
                <td>${escapeHtml(r.Category || '—')}</td>
                <td>${escapeHtml(r.Topic || '—')}</td>
                <td>${escapeHtml(r.TrainerUsername || '—')}</td>
                <td><span class="status-pill status-OnHold">Pending</span></td>
                <td>
                  <button class="btn btn-primary btn-sm"
                          onclick="decideApproval('${escapeHtml(r.SyllabusID || '')}','Approved')">
                    Approve
                  </button>
                  <button class="btn btn-outline btn-sm"
                          onclick="decideApproval('${escapeHtml(r.SyllabusID || '')}','Rejected')">
                    Reject
                  </button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }).catch(err => {
      showLoading(false);
      const area = document.getElementById('approvalsArea');
      if(area){
        area.innerHTML = `
          <div class="empty-state">
            Unable to load syllabus approvals. Please refresh and try again.
          </div>
        `;
      }
      handleError(err);
    });
  }
  function decideApproval(id, decision){
    if(!isReportingManagerUser() && !isAdminUser()){
      showToast('Only Reporting Manager or Admin can approve training updates.', true);
      return;
    }
    showLoading(true);
    callServer('approveSyllabus', id, currentUser.username, decision).then(result => {
      showLoading(false);
      if(!result.success){ showToast(result.message || 'Syllabus review failed', true); return; } showToast('Syllabus ' + decision.toLowerCase() + '.');
      renderApprovals(); updateAlertBadge();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  // ---------- TRAINER: MY PROJECTS (ALL THREE TYPES) ----------
  function renderMyProjects(){
    content(`<div class="page-heading"><h1>My Projects</h1><p style="color:var(--gray-500);">LeSuccess, Vendor and Freelancer assignments linked to your Employee ID.</p></div>
      <div id="myProjectList" class="external-project-grid"><div class="empty-state">Loading your projects…</div></div>`);
    callServer('getMyProjects', currentUser.username).then(projects => {
      const area = document.getElementById('myProjectList');
      if(!area || currentPage !== 'myprojects') return;
      if(!Array.isArray(projects) || !projects.length){
        area.innerHTML = '<div class="empty-state">No active projects are assigned to your Employee ID yet. Contact Admin to assign your account in LeSuccess, Vendor or Freelancer Projects.</div>';
        return;
      }
      area.innerHTML = projects.map(p => `<div class="external-project-card view-only-card" style="padding:20px;">
        <div class="external-project-head"><div><b style="font-size:18px;">${escapeHtml(p.projectName)}</b>
          <div class="external-project-meta">${escapeHtml(p.projectType === 'lesuccess' ? 'LeSuccess' : p.projectType === 'vendor' ? 'Vendor' : 'Freelancer')} Project • ${escapeHtml(p.vendor || '')}</div></div>
          <span class="status-pill status-${statusClass(p.status)}">${escapeHtml(p.status)}</span></div>
        <div class="external-project-details">
          <div class="external-project-detail"><span>Category</span><b>${escapeHtml((p.myCategories || []).join(', '))}</b></div>
          <div class="external-project-detail"><span>Planned Days</span><b>${Number(p.plannedDays) || 0}</b></div>
        </div>
        <div style="margin-top:14px;display:flex;justify-content:space-between;align-items:center;gap:8px;">
          <small>${p.canSubmit ? 'Ready for training updates' : 'Daily updates available when project is Running'}</small>
          <button class="btn btn-red btn-sm" ${p.canSubmit ? '' : 'disabled'} data-project-key="${escapeHtml(p.projectKey)}" onclick="openProjectDailyUpdate(this.dataset.projectKey)">Daily Update</button>
        </div>
      </div>`).join('');
    }).catch(err => {
      const area = document.getElementById('myProjectList');
      if(area) area.innerHTML = `<div class="empty-state">Unable to load project assignments: ${escapeHtml(err.message || String(err))}</div>`;
      handleError(err);
    });
  }
  function openProjectDailyUpdate(projectKey){
    window._selectedDailyProject = projectKey;
    navigate('dailyupdate');
  }

  // ---------- TRAINER: MY COLLEGES ----------
  function renderMyColleges(){
    content(`
      <div class="page-heading"><h1>My Colleges</h1></div>
      <div id="collegeGridArea"></div>
    `);

    showLoading(true);
    callServer('getMyColleges', currentUser.username)
      .then(colleges => {
        showLoading(false);
        colleges = Array.isArray(colleges) ? colleges : [];
        collegesCache = colleges;
        document.getElementById('collegeGridArea').innerHTML =
          collegeCardsHtml(colleges, true);
      })
      .catch(err => {
        showLoading(false);
        handleError(err);
        document.getElementById('collegeGridArea').innerHTML =
          '<div class="empty-state">Unable to load your colleges.</div>';
      });
  }

  function renderDailyUpdateForm(){
    content(`
      <div class="page-heading">
        <h1>Daily Training Update</h1>
        <p style="color:var(--gray-500);margin-top:4px;">Submit today's training update and view your submitted updates below.</p>
      </div>
      <div id="dailyFormArea" style="max-width:560px;"></div>
      <div class="section-header" style="margin-top:28px;">
        <h3>My Daily Updates</h3>
      </div>
      <div id="myDailyUpdatesArea"></div>
    `);

    loadDailyUpdateForm();
    loadMyDailyUpdates();
  }

  function loadDailyUpdateForm(){
    showLoading(true);
    callServer('getMyProjects', currentUser.username).then(colleges => {
      showLoading(false);
      colleges = Array.isArray(colleges) ? colleges : [];
      const area = document.getElementById('dailyFormArea');
      if(!area) return;

      if(!colleges.some(p => p.canSubmit)){
        area.innerHTML = '<div class="empty-state">Checking your assignment status…</div>';
        callServer('getMyAssignmentStatus', currentUser.username).then(info => {
          if(document.getElementById('dailyFormArea') !== area) return;
          area.innerHTML = `<div class="empty-state"><b>No available project for Daily Update.</b><p>${escapeHtml(colleges.length ? 'You have assigned projects, but none are Running. Check the status in My Projects or ask Admin to activate the assignment.' : info.message || 'Ask Admin to check your assignments.')}</p><button class="btn btn-outline btn-sm" onclick="navigate('myprojects')">View My Projects</button><p>Logged-in Employee ID: <b>${escapeHtml(currentUser.username)}</b></p><p>Vendor/Freelancer assignments also need an exact internal Trainer account.</p><button class="btn btn-outline btn-sm" onclick="loadDailyUpdateForm()">Check Again</button></div>`;
        }).catch(err => {
          if(document.getElementById('dailyFormArea') === area)
            area.innerHTML = '<div class="empty-state">No current college assignment found. Contact Admin to check the assignment status.</div>';
          handleError(err);
        });
        return;
      }

      area.innerHTML = `
        <div style="background:#fff; border-radius:var(--radius); box-shadow:var(--shadow); padding:22px 24px;">
          <div class="field"><label>Project / College</label>
            <select id="duCollege" onchange="populateDuCategories()">
              ${colleges.filter(c => c.canSubmit).map(c => `<option value="${escapeHtml(c.projectKey)}" data-cats="${escapeHtml(JSON.stringify(c.myCategories || []))}">${escapeHtml(c.projectType === 'lesuccess' ? 'LeSuccess' : c.projectType === 'vendor' ? 'Vendor' : 'Freelancer')} — ${escapeHtml(c.projectName)}</option>`).join('')}
            </select>
          </div>
          <div class="field"><label>Category</label><select id="duCategory"></select></div>
          <div class="field"><label>Date</label><input id="duDate" type="date" value="${new Date().toISOString().substring(0,10)}"></div>
          <div class="field"><label>Topic Covered</label><input id="duTopic" placeholder="e.g. Collections Framework"></div>
          <div class="field"><label>Attendance (%)</label><input id="duAttendance" type="number" min="0" max="100" placeholder="e.g. 95"></div>
          <button class="btn btn-red btn-block" onclick="submitDailyUpdate()">Submit Update</button>
        </div>
      `;
      if(window._selectedDailyProject && Array.from(document.getElementById('duCollege').options).some(o => o.value === window._selectedDailyProject)){
        document.getElementById('duCollege').value = window._selectedDailyProject;
        window._selectedDailyProject = '';
      }
      populateDuCategories();
    }).catch(err => {
      showLoading(false);
      const area = document.getElementById('dailyFormArea');
      if(area) area.innerHTML = '<div class="empty-state">Unable to load college assignments. <button class="btn btn-outline btn-sm" onclick="loadDailyUpdateForm()">Retry</button></div>';
      handleError(err);
    });
  }

  function loadMyDailyUpdates(){
    const area = document.getElementById('myDailyUpdatesArea');
    if(!area) return;

    area.innerHTML = '<div class="empty-state">Loading your updates…</div>';

    callServer('getMyDailyUpdates', currentUser.username).then(rows => {
      rows = Array.isArray(rows) ? rows : [];

      if(rows.length === 0){
        area.innerHTML = '<div class="empty-state">You have not submitted any daily updates yet.</div>';
        return;
      }

      area.innerHTML = `
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Project / College</th>
                <th>Category</th>
                <th>Topic Covered</th>
                <th>Attendance</th>
                <th>RM Status</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map(r => {
                const status = String(r.rmStatus || 'Pending');
                const statusCls = status === 'Approved' ? 'status-Running' :
                                  status === 'Rejected' ? 'status-Cancelled' : 'status-OnHold';
                return `
                  <tr>
                    <td>${escapeHtml(r.date || '—')}</td>
                    <td>
                      <div style="display:flex;align-items:center;gap:8px;">
                        ${r.collegeLogo ? `<img src="${escapeHtml(r.collegeLogo)}" style="width:30px;height:30px;object-fit:contain;border-radius:6px;" onerror="this.style.display='none'">` : ''}
                        <span>${escapeHtml(r.projectType ? (r.projectType === 'lesuccess' ? 'LeSuccess' : r.projectType === 'vendor' ? 'Vendor' : 'Freelancer') + ' — ' : '')}${escapeHtml(r.collegeName || r.collegeCode || '—')}</span>
                      </div>
                    </td>
                    <td>${escapeHtml(r.category || '—')}</td>
                    <td>${escapeHtml(r.topicCovered || '—')}</td>
                    <td>${escapeHtml(r.attendance || '—')}</td>
                    <td><span class="status-pill ${statusCls}">${escapeHtml(status)}</span></td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      `;
    }).catch(err => {
      area.innerHTML = '<div class="empty-state">Unable to load your daily updates.</div>';
      handleError(err);
    });
  }
  function populateDuCategories(){
    const sel = document.getElementById('duCollege');
    const opt = sel.options[sel.selectedIndex];
    let cats = [];
    try { cats = JSON.parse(opt.dataset.cats); } catch(e){}
    document.getElementById('duCategory').innerHTML = (cats.length ? cats : ['General']).map(c => `<option>${escapeHtml(c)}</option>`).join('');
  }
  function submitDailyUpdate(){
    const payload = {
      projectType: document.getElementById('duCollege').value.split(':', 1)[0],
      projectId: document.getElementById('duCollege').value.substring(document.getElementById('duCollege').value.indexOf(':') + 1),
      collegeCode: document.getElementById('duCollege').value.substring(document.getElementById('duCollege').value.indexOf(':') + 1),
      category: document.getElementById('duCategory').value,
      date: document.getElementById('duDate').value,
      topicCovered: document.getElementById('duTopic').value.trim(),
      attendance: document.getElementById('duAttendance').value + '%',
      trainerUsername: currentUser.username,
      trainerName: currentUser.fullName
    };
    if(!payload.topicCovered){ showToast('Please enter the topic covered.', true); return; }
    showLoading(true);
    callServer('submitDailyUpdate', payload).then(result => {
      showLoading(false);
      if(!result.success){ showToast(result.message || 'Daily update failed', true); return; } showToast('Update submitted. It is now visible in My Daily Updates and is waiting for Reporting Manager approval.');
      document.getElementById('duTopic').value = '';
      document.getElementById('duAttendance').value = '';
      loadMyDailyUpdates();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  // ---------- CHANGE PASSWORD ----------
  function openChangePassword(){
    document.getElementById('modalTitle').textContent = 'Change Password';
    document.getElementById('modalBody').innerHTML = `
      <div class="field"><label>Current Password</label><input id="cpOld" type="password"></div>
      <div class="field"><label>New Password</label><input id="cpNew" type="password"></div>
      <div class="field"><label>Confirm New Password</label><input id="cpConfirm" type="password"></div>
    `;
    document.getElementById('modalFooter').innerHTML = `
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-red" onclick="submitChangePassword()">Update Password</button>
    `;
    document.getElementById('modalOverlay').classList.add('active');
  }
  function submitChangePassword(){
    const oldP = document.getElementById('cpOld').value;
    const newP = document.getElementById('cpNew').value;
    const confirmP = document.getElementById('cpConfirm').value;
    if(!oldP || !newP){ showToast('Please fill all fields.', true); return; }
    if(newP !== confirmP){ showToast('New passwords do not match.', true); return; }
    showLoading(true);
    callServer('changePassword', currentUser.username, oldP, newP).then(res => {
      showLoading(false);
      if(!res.success){ showToast(res.message, true); return; }
      showToast('Password updated. Please sign in again.');
      closeModal();
      logout();
    }).catch(err => { showLoading(false); handleError(err); });
  }

  // ---------- MODAL HELPERS ----------
  function closeModal(){ document.getElementById('modalOverlay').classList.remove('active'); }
  document.getElementById('modalOverlay').addEventListener('click', e => { if(e.target.id === 'modalOverlay') closeModal(); });
  document.getElementById('loginPassword').addEventListener('keydown', e => { if(e.key === 'Enter') doLogin(); });
  