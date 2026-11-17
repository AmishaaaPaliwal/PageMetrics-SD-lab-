let csrf = '';
export let account = null;
export const roleLabels = {librarian:'Librarian',faculty:'Faculty / department head',administrator:'Library administrator',management:'University / institute management'};
export const can = permission => account?.permissions?.includes(permission) === true;
const $ = selector => document.querySelector(selector);
export async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    credentials: 'same-origin',
    headers: body === undefined ? {} : {'Content-Type':'application/json','X-PageMetrics':'1','X-CSRF-Token':csrf},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})
  });
  let result;
  try { result = await response.json(); }
  catch { throw Error('The authentication server is unavailable. Run npm start in the project folder.'); }
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/login' && account) showAuth('Your session has expired. Please sign in again.');
    const error=Error(result.error || 'Request failed.');error.code=result.code;throw error;
  }
  return result;
}
function showAuth(message = '') {
  document.dispatchEvent(new CustomEvent('pagemetrics:logout'));
  account = null;
  csrf = '';
  $('#auth-screen').hidden = false;
  $('#workspace-app').hidden = true;
  $('#auth-message').textContent = message;
  $('#auth-form').reset();
}
let verificationCredentials=null;
let registering = location.pathname === '/register';
function authMode() {
  verificationCredentials=null;$('#otp-panel').hidden=true;$('#auth-form').hidden=false;$('#auth-toggle').hidden=false;
  $('#auth-title').textContent = registering ? 'Create your account' : 'Welcome back';
  $('#auth-description').textContent = registering ? 'Use your @lnmiit.ac.in email and choose your staff role.' : 'Sign in to your library workspace.';
  $('#registration-fields').hidden = !registering;
  $('#register-name').required = registering;
  $('#register-role').disabled = !registering;
  $('#auth-password').autocomplete = registering ? 'new-password' : 'current-password';
  $('#auth-submit').textContent = registering ? 'Create account →' : 'Sign in →';
  $('#auth-toggle').textContent = registering ? 'Already registered? Sign in' : 'New to PageMetrics? Create an account';
  $('#auth-message').textContent = '';
  facultyField();
}
function facultyField() {
  const faculty = registering && $('#register-role').value === 'faculty';
  $('#faculty-field').hidden = !faculty;
  $('#register-subject').required = faculty;
  $('#register-subject').disabled = !faculty;
  $('#approval-note').hidden = !registering;
}
function enter(result) {
  account = result.user;
  csrf = result.csrf;
  $('#auth-screen').hidden = true;
  $('#workspace-app').hidden = false;
  $('#profile-name').textContent = account.name;
  $('#profile-role').textContent = roleLabels[account.role] + (account.subject ? ' · '+account.subject : '');
  $('#profile-initials').textContent = account.name.split(/\s+/).map(x=>x[0]).slice(0,2).join('').toUpperCase();
  $('#session-label').textContent = `${roleLabels[account.role]} workspace`;
  const canImport = can('import');
  $('[data-page=imports]').hidden = !canImport;
  $('#import-shortcut').hidden = !canImport;
  $('[data-page=accounts]').hidden = !can('approve_accounts');
  $('[data-page=overview]').hidden = !can('explore');
  $('[data-page=resources]').hidden = !can('explore');
  $('[data-page=reports]').hidden = !can('reports');
  $('[data-page=audit]').hidden = !can('audit');
  $('#permission-note').textContent = ({faculty:`Subject access: ${account.subject}. Use subject trends to guide resource requests.`,librarian:'Analyze borrowing trends and plan collections. Only librarians can import circulation data.',administrator:'Explore all library filters, view reports, and approve verified staff accounts.',management:'Read-only aggregate reports on library usage and resource utilization.',student:'Students benefit from collection improvements. Analytics access is reserved for authorized staff.'})[account.role];
  document.dispatchEvent(new CustomEvent('pagemetrics:login'));
}
$('#auth-toggle').onclick = () => { registering = !registering; authMode(); };
$('#register-role').onchange = facultyField;
$('#auth-form').onsubmit = async event => {
  event.preventDefault();
  const button = $('#auth-submit');
  button.disabled = true;
  $('#auth-message').textContent = '';
  try {
    const data = Object.fromEntries(new FormData(event.target));
    if (registering) {
      const result = await api('/api/register',data);
      await showVerification(data);
    } else {
      const result = await api('/api/login',data);
      $('#auth-password').value = '';
      enter(result);
    }
  } catch(error) { if(error.code==='EMAIL_VERIFICATION_REQUIRED')await showVerification(Object.fromEntries(new FormData(event.target)));else $('#auth-message').textContent = error.message; }
  finally { button.disabled = false; }
};
$('#logout').onclick = async () => {
  try {
    await api('/api/logout',{});
    showAuth('You have signed out.');
  } catch(error) { $('#message').textContent = error.message; }
};
export async function initializeAuth() {
  authMode();
  try { enter(await api('/api/me')); }
  catch(error) { if (!error.message.includes('Sign in to continue')) $('#auth-message').textContent = error.message; }
}
export async function renderAccounts() {
  const panel = $('#account-list');
  panel.textContent = 'Loading accounts…';
  try {
    const {users} = await api('/api/users');
    panel.replaceChildren();
    for (const user of users) {
      const row = document.createElement('div');
      row.className = 'account-row';
      const description = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = user.name;
      const detail = document.createElement('p');
      detail.textContent = `${user.email} · ${roleLabels[user.role] || user.role}${user.subject ? ' · '+user.subject : ''}`;
      description.append(title,detail);
      const actions = document.createElement('div');
      actions.className = 'account-actions';
      const status = document.createElement('span');
      status.className = 'tag';
      status.textContent = user.status;
      actions.append(status);
      if(user.status==='pending'&&!user.email_verified){const note=document.createElement('small');note.textContent='Awaiting email verification';actions.append(note);}
      if (user.status === 'pending' && user.email_verified) {
        const verification=document.createElement('label');
        verification.className='approval-check';
        const checkbox=document.createElement('input');checkbox.type='checkbox';
        verification.append(checkbox,document.createTextNode('I verified institutional identity and the requested role/subject.'));
        actions.append(verification);
        for (const action of ['approve','reject']) {
          const button = document.createElement('button');
          button.className = action === 'approve' ? 'primary' : 'secondary';
          button.textContent = action === 'approve' ? 'Approve role' : 'Reject';
          button.onclick = async () => {
            if(action==='approve'&&!checkbox.checked){$('#accounts-message').textContent='Verify institutional identity and select the confirmation checkbox first.';return;}
            actions.querySelectorAll('button').forEach(b=>b.disabled=true);
            try { await api('/api/users/review',{id:user.id,action,identityVerified:checkbox.checked}); await renderAccounts(); }
            catch(error) { $('#accounts-message').textContent=error.message; actions.querySelectorAll('button').forEach(b=>b.disabled=false); }
          };
          actions.append(button);
        }
      }
      row.append(description,actions);
      panel.append(row);
    }
  } catch(error) { panel.textContent=error.message; }
}

async function showVerification(data){
 verificationCredentials={email:data.email,password:data.password};
 $('#auth-password').value='';$('#auth-form').hidden=true;$('#auth-toggle').hidden=true;$('#otp-panel').hidden=false;
 $('#auth-title').textContent='Verify your email';$('#auth-description').textContent='Verify ownership of '+data.email+'.';
 $('#otp-code').value='';$('#otp-message').textContent='';await sendCode();
}
async function sendCode(){
 if(!verificationCredentials)return;
 $('#otp-resend').disabled=true;
 try{const result=await api('/api/request-email-code',verificationCredentials);$('#otp-message').textContent=result.message+' You can resend after 60 seconds.';}
 catch(error){$('#otp-message').textContent=error.message;}
 finally{$('#otp-resend').disabled=false;}
}
$('#otp-form').onsubmit=async event=>{
 event.preventDefault();if(!verificationCredentials)return;$('#otp-verify').disabled=true;
 try{const result=await api('/api/verify-email',{...verificationCredentials,code:$('#otp-code').value});registering=false;authMode();$('#auth-message').textContent=result.message;}
 catch(error){$('#otp-message').textContent=error.message;}
 finally{$('#otp-verify').disabled=false;}
};
$('#otp-resend').onclick=sendCode;
$('#otp-back').onclick=()=>{registering=false;authMode();};
