let csrf = '';
export let account = null;
export const roleLabels = {librarian:'Librarian',faculty:'Faculty / department head',administrator:'Library administrator',management:'University / institute management'};
export const can = permission => account?.permissions?.includes(permission) === true;
const $ = selector => document.querySelector(selector);
// Send a same-origin API request, include CSRF protection on writes, and expose server errors to the UI.
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
// Clear account state and dashboard data, then show the sign-in form.
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
// Switch registration/sign-in labels and required fields; the recovery button is intentionally hidden.
function authMode() {
  $('#confirm-label').hidden = !registering;
  $('#auth-confirm').disabled = !registering;
  $('#auth-confirm').required = registering;
  $('#auth-confirm').value = '';
  // Temporarily hide password recovery from the sign-in screen to display replace true with registeing.
  $('#forgot').hidden = true;
  $('#recovery-form').hidden = true;
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
// Require a subject only when the selected registration role is faculty.
function facultyField() {
  const faculty = registering && $('#register-role').value === 'faculty';
  $('#faculty-field').hidden = !faculty;
  $('#register-subject').required = faculty;
  $('#register-subject').disabled = !faculty;
  $('#approval-note').hidden = !registering;
}
// Store the authenticated account and show navigation matching its server-provided permissions.
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
// Switch between existing-account sign-in and new-account registration.
$('#auth-toggle').onclick = () => { registering = !registering; authMode(); };
// Update the subject field when the chosen role changes.
$('#register-role').onchange = facultyField;
// Submit registration or login; registration requires matching password fields.
$('#auth-form').onsubmit = async event => {
  event.preventDefault();
  const button = $('#auth-submit');
  button.disabled = true;
  $('#auth-message').textContent = '';
  try {
    const data = Object.fromEntries(new FormData(event.target));
    if (registering) {
      if (data.password !== data.confirmPassword) throw Error('The passwords do not match.');
      const result = await api('/api/register',data);
      $('#auth-password').value = $('#auth-confirm').value = '';
      const continueRegistration = async () => {
        if (result.user.awaitingEmailVerification) {
          await showVerification(data);
        } else {
          registering = false;
          authMode();
          $('#auth-message').textContent = 'Account created. An administrator must approve your role before you can sign in.';
        }
      };
      if (result.user.recoveryKey) displayRecoveryKey(result.user.recoveryKey, continueRegistration);
      else await continueRegistration();
    } else {
      const result = await api('/api/login',data);
      $('#auth-password').value = '';
      enter(result);
    }
  } catch(error) { if(error.code==='EMAIL_VERIFICATION_REQUIRED')await showVerification(Object.fromEntries(new FormData(event.target)));else $('#auth-message').textContent = error.message; }
  finally { button.disabled = false; }
};
// End the server session and clear the authenticated interface.
$('#logout').onclick = async () => {
  try {
    await api('/api/logout',{});
    showAuth('You have signed out.');
  } catch(error) { $('#message').textContent = error.message; }
};
// Initialize form state and attempt to restore an existing session from the server cookie.
export async function initializeAuth() {
  authMode();
  try { enter(await api('/api/me')); }
  catch(error) { if (!error.message.includes('Sign in to continue')) $('#auth-message').textContent = error.message; }
}
// Build the administrator review list and approval actions using safe DOM text.
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
      if(user.status==='pending'&&user.awaitingEmailVerification){const note=document.createElement('small');note.textContent='Awaiting email verification';actions.append(note);}
      if (user.status === 'pending' && !user.awaitingEmailVerification) {
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

// Keep credentials briefly in memory and open the registration-code panel.
async function showVerification(data){
 $('#forgot').hidden=true;
 verificationCredentials={email:data.email,password:data.password};
 $('#auth-password').value='';$('#auth-form').hidden=true;$('#auth-toggle').hidden=true;$('#otp-panel').hidden=false;
 $('#auth-title').textContent='Verify your account';$('#auth-description').textContent='Enter the registration code for '+data.email+'.';
 $('#otp-code').value='';$('#otp-message').textContent='';await sendCode();
}
// Request a new registration code and display delivery or cooldown feedback.
async function sendCode(){
 if(!verificationCredentials)return;
 $('#otp-resend').disabled=true;
 try{const result=await api('/api/request-email-code',verificationCredentials);$('#otp-message').textContent=result.message+' You can resend after 60 seconds.';}
 catch(error){$('#otp-message').textContent=error.message;}
 finally{$('#otp-resend').disabled=false;}
}
// Submit the six-digit registration code and return to sign-in on success.
$('#otp-form').onsubmit=async event=>{
 event.preventDefault();if(!verificationCredentials)return;$('#otp-verify').disabled=true;
 try{const result=await api('/api/verify-email',{...verificationCredentials,code:$('#otp-code').value});registering=false;authMode();$('#auth-message').textContent=result.message;}
 catch(error){$('#otp-message').textContent=error.message;}
 finally{$('#otp-verify').disabled=false;}
};
// Allow the user to request a fresh registration code.
$('#otp-resend').onclick=sendCode;
// Exit verification and return to the standard sign-in screen.
$('#otp-back').onclick=()=>{registering=false;authMode();};

// Hide the standard account controls while a recovery step is displayed.
function hideAuthControls() {
  for (const selector of ['#auth-form', '#forgot', '#auth-toggle', '#recovery-form']) {
    $(selector).hidden = true;
  }
}

// Display the private recovery key until the user confirms saving it, then clear it from the page.
function displayRecoveryKey(key, next) {
  hideAuthControls();
  $('#auth-title').textContent = 'Save your recovery key';
  $('#auth-description').textContent = '';
  $('#new-key').textContent = key;
  $('#save-key').hidden = false;
  $('#key-saved').onclick = () => {
    $('#new-key').textContent = '';
    $('#save-key').hidden = true;
    $('#key-saved').onclick = null;
    next();
  };
}

// Open password recovery and prefill the email from the sign-in form.
$('#forgot').onclick = () => {
  hideAuthControls();
  const form = $('#recovery-form');
  form.reset();
  $('#reset-secret').name = 'code';
  form.elements.code.closest('label').firstChild.textContent = 'Reset code';
  form.elements.email.value = $('#auth-email').value;
  $('#reset-message').textContent = '';
  $('#auth-title').textContent = 'Reset your password';
  $('#auth-description').textContent = 'Request a reset code for your registered email address.';
  form.hidden = false;
  form.elements.email.focus();
};
// Request a demo reset code and show where the user can retrieve it.
$('#request-reset').onclick = async event => {
  const button = event.currentTarget;
  const form = $('#recovery-form');
  if (!form.elements.email.reportValidity()) return;
  button.disabled = true;
  try {
    const result = await api('/api/request-reset-code', {email: form.elements.email.value});
    $('#reset-secret').name = result.useKey ? 'recoveryKey' : 'code';
    $('#reset-secret').closest('label').firstChild.textContent = result.useKey ? 'Recovery key' : 'Reset code';
    $('#reset-message').textContent = result.message;
    $('#reset-secret').focus();
  } catch (error) { $('#reset-message').textContent = error.message; }
  finally { button.disabled = false; }
};
// Clear recovery inputs and return to sign-in.
$('#reset-back').onclick = () => { $('#recovery-form').reset(); authMode(); };
// Require matching new passwords, submit the reset and clear the sensitive form values.
$('#recovery-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('.primary');
  button.disabled = true;
  try {
    const data = Object.fromEntries(new FormData(form));
    if (data.password !== data.confirmPassword) throw Error('The passwords do not match.');
    const result = await api('/api/reset-password', data);
    form.reset();
    const finish = () => {
      authMode();
      $('#auth-email').value = data.email;
      $('#auth-password').value = '';
      $('#auth-message').textContent = 'Password updated. Sign in with your new password.';
    };
    if (result.recoveryKey) displayRecoveryKey(result.recoveryKey, finish);
    else finish();
  } catch (error) {
    $('#reset-message').textContent = error.message;
  } finally {
    button.disabled = false;
  }
};
