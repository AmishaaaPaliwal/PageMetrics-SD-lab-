"""PageMetrics local application server. Python standard library only."""
import argparse
import csv
import datetime as dt
import getpass
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from mailer import send_verification_code, DeliveryError
from reporting import validate_criteria, filter_rows, aggregate

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'data' / 'pagemetrics.sqlite3'
PERMISSIONS = {
    'faculty': {'explore', 'reports'},
    'librarian': {'explore', 'import', 'reports', 'import_history'},
    'administrator': {'explore', 'reports', 'approve_accounts', 'audit', 'import_history'},
    'management': {'reports'},
}
ROLES = set(PERMISSIONS)
SUBJECTS = ['Computer Science', 'Literature', 'Engineering', 'Mathematics', 'Natural Sciences', 'History']
FIELDS = ['circulationId', 'checkoutDate', 'returnDate', 'returnStatus', 'resourceId', 'title', 'subject', 'deweyClass', 'format', 'anonymizedReaderId', 'userSegment']
STATUSES = {'NOT_RETURNED', 'RETURNED_ON_TIME', 'RETURNED_LATE', 'UNKNOWN'}
SESSION_SECONDS = 8 * 60 * 60

class APIError(Exception):
    def __init__(self, message, status=400, code=None):
        self.status = status
        self.code = code
        super().__init__(message)

@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()

def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS email_verifications (
            user_id INTEGER PRIMARY KEY REFERENCES users(id), code_hash TEXT NOT NULL,
            expires_at INTEGER NOT NULL, attempts INTEGER NOT NULL, sent_at INTEGER NOT NULL,
            window_start INTEGER NOT NULL, send_count INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS password_recovery (
            user_id INTEGER PRIMARY KEY REFERENCES users(id), digest TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            csrf TEXT NOT NULL, expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dataset (id INTEGER PRIMARY KEY CHECK(id=1), records TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY, occurred_at INTEGER NOT NULL, actor_id INTEGER,
            actor_role TEXT NOT NULL, event TEXT NOT NULL, outcome TEXT NOT NULL, details TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS import_jobs (
            id INTEGER PRIMARY KEY, actor_id INTEGER NOT NULL, created_at INTEGER NOT NULL,
            state TEXT NOT NULL, imported_count INTEGER NOT NULL DEFAULT 0, rejected_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS import_states (
            id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES import_jobs(id),
            state TEXT NOT NULL, occurred_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_attempts (key TEXT PRIMARY KEY, failures INTEGER NOT NULL, reset_at INTEGER NOT NULL);
        ''')
        columns={r['name'] for r in db.execute('PRAGMA table_info(users)')}
        if 'email_verified' not in columns:
            db.execute('ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0')
        # Retire legacy student accounts without deleting their history.
        db.execute("UPDATE users SET status='inactive' WHERE role='student'")
        db.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE role='student')")
    os.chmod(DB_PATH, 0o600)

def audit(db, user, event, outcome='SUCCESS', details=None):
    db.execute('INSERT INTO audit_events(occurred_at,actor_id,actor_role,event,outcome,details) VALUES(?,?,?,?,?,?)',
               (int(time.time()), user['id'] if user else None, user['role'] if user else 'anonymous', event, outcome, json.dumps(details or {})))

def audit_history(user, offset=0):
    require_permission(user, 'audit')
    with connect() as db:
        rows = db.execute('SELECT * FROM audit_events ORDER BY id DESC LIMIT 100 OFFSET ?', (offset,)).fetchall()
    return {'events': [dict(r) for r in rows], 'nextOffset': offset+100 if len(rows)==100 else None}

def import_state(db, job_id, state):
    db.execute('UPDATE import_jobs SET state=? WHERE id=?', (state, job_id))
    db.execute('INSERT INTO import_states(job_id,state,occurred_at) VALUES(?,?,?)', (job_id,state,int(time.time())))

def import_history(user):
    require_permission(user, 'import_history')
    with connect() as db:
        rows = db.execute('SELECT * FROM import_jobs ORDER BY id DESC LIMIT 50').fetchall()
        jobs = []
        for row in rows:
            item = dict(row)
            item['states'] = [r['state'] for r in db.execute('SELECT state FROM import_states WHERE job_id=? ORDER BY id',(row['id'],))]
            jobs.append(item)
    return {'jobs': jobs}

def password_hash(password):
    salt = secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + value

def password_matches(password, encoded):
    salt, expected = encoded.split(':')
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, expected)

def clean_text(data, key, limit=150):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > limit:
        raise APIError(f'Invalid {key}.')
    return value.strip()

def credentials(data):
    email = clean_text(data, 'email', 254).lower()
    password = data.get('password', '')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise APIError('Enter a valid email address.')
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise APIError('Use a password between 12 and 128 characters.')
    return email, password

def requires_email_code():
    return os.environ.get('PAGEMETRICS_REQUIRE_OTP', '0') == '1'


def awaiting_email(row):
    return requires_email_code() and not row['email_verified']


def public_user(row):
    result = {k: row[k] for k in ('id', 'name', 'email', 'role', 'subject', 'status', 'email_verified')}
    result['awaitingEmailVerification'] = awaiting_email(row)
    result['permissions'] = sorted(PERMISSIONS.get(row['role'], set()))
    return result

def issue_recovery_key(db, user_id):
    key = secrets.token_urlsafe(24)
    digest = hashlib.sha256(key.encode()).hexdigest()
    db.execute('INSERT OR REPLACE INTO password_recovery VALUES(?,?)', (user_id, digest))
    return key


def reset_password(data):
    email, password = credentials(data)
    if password != data.get('confirmPassword'):
        raise APIError('The passwords do not match.')
    key = clean_text(data, 'recoveryKey', 128)
    digest = hashlib.sha256(key.encode()).hexdigest()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        user = db.execute("""SELECT users.*, password_recovery.digest FROM users
            JOIN password_recovery ON password_recovery.user_id=users.id WHERE email=?""", (email,)).fetchone()
        if not user or not hmac.compare_digest(digest, user['digest']):
            raise APIError('The email or recovery key is incorrect.')
        db.execute('UPDATE users SET password_hash=? WHERE id=?', (password_hash(password), user['id']))
        db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
        db.execute('DELETE FROM login_attempts WHERE key=?', ('account:' + email,))
        db.execute('DELETE FROM email_verifications WHERE user_id=?', (user['id'],))
        replacement = issue_recovery_key(db, user['id'])
        audit(db, user, 'PASSWORD_RESET')
    return {'recoveryKey': replacement}


def register(data, bootstrap=False):
    email, password = credentials(data)
    name = clean_text(data, 'name', 100)
    role = clean_text(data, 'role', 30)
    subject = clean_text(data, 'subject', 100)
    if not name or role not in ROLES:
        raise APIError('A name and valid role are required.')
    if role == 'faculty' and subject not in SUBJECTS:
        raise APIError('Choose a faculty subject area.')
    if bootstrap and role != 'administrator':
        raise APIError('Only the initial administrator can be bootstrapped.')
    allowed = [d.strip().lower() for d in os.environ.get('PAGEMETRICS_EMAIL_DOMAINS','lnmiit.ac.in').split(',') if d.strip()]
    if allowed and email.rsplit('@',1)[1] not in allowed:
        raise APIError('Use an email address from an approved institutional domain.')
    status = 'active' if bootstrap else 'pending'
    with connect() as db:
        # Serialize first-admin bootstrap with concurrent processes.
        db.execute('BEGIN IMMEDIATE')
        if bootstrap and db.execute("SELECT 1 FROM users WHERE role='administrator' AND status='active'").fetchone():
            raise APIError('An active administrator already exists.')
        try:
            cursor = db.execute('INSERT INTO users(name,email,password_hash,role,subject,status,created_at) VALUES(?,?,?,?,?,?,?)',
                                (name, email, password_hash(password), role, subject if role == 'faculty' else '', status, int(time.time())))
        except sqlite3.IntegrityError:
            raise APIError('An account with that email already exists.', 409)
        if bootstrap: db.execute('UPDATE users SET email_verified=1 WHERE id=?',(cursor.lastrowid,))
        result = public_user(db.execute('SELECT * FROM users WHERE id=?', (cursor.lastrowid,)).fetchone())
        if not bootstrap:
            result['recoveryKey'] = issue_recovery_key(db, cursor.lastrowid)
        audit(db,result,'ACCOUNT_CREATED',details={'status':status})
        return result

def authenticate(data, remote='local'):
    email, password = credentials(data)
    now = int(time.time())
    # Both account and source limits survive a server restart.
    keys = ['account:' + email, 'ip:' + remote]
    with connect() as db:
        for key in keys:
            attempt = db.execute('SELECT * FROM login_attempts WHERE key=?', (key,)).fetchone()
            if attempt and attempt['reset_at'] > now and attempt['failures'] >= (10 if key.startswith('account:') else 50):
                raise APIError('Too many sign-in attempts. Try again in 15 minutes.', 429)
        user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        matched = password_matches(password, user['password_hash'] if user else DUMMY_HASH)
        if not user or not matched:
            for key in keys:
                db.execute('INSERT INTO login_attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET failures=CASE WHEN reset_at<=? THEN 1 ELSE failures+1 END, reset_at=CASE WHEN reset_at<=? THEN ? ELSE reset_at END', (key, now+900, now, now, now+900))
            audit(db,None,'LOGIN','FAILED')
            db.commit()
            raise APIError('Email or password is incorrect.', 401)
        if user['role'] not in ROLES:
            audit(db,user,'LOGIN','DENIED'); db.commit()
            raise APIError('Student login is not supported. PageMetrics is for authorized library staff.',403)
        if user['status'] not in {'active','pending'}:
            raise APIError('This account is not eligible for access. Contact an administrator.',403)
        db.execute('DELETE FROM login_attempts WHERE key=?', (keys[0],))
        return user

def login(data, remote='local'):
    user=authenticate(data,remote)
    if awaiting_email(user):
        raise APIError('Verify your institutional email before signing in.',403,'EMAIL_VERIFICATION_REQUIRED')
    if user['status']!='active':
        with connect() as db: audit(db,user,'LOGIN','DENIED')
        raise APIError('Your staff account is awaiting approval.',403)
    now=int(time.time())
    with connect() as db:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires_at<=?', (now,))
        db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user['id'], csrf, now + SESSION_SECONDS))
        audit(db,user,'LOGIN')
    return token, csrf, public_user(user)

def request_email_code(data, remote='local'):
    user=authenticate(data,remote)
    if user['email_verified']: raise APIError('This email is already verified.')
    allowed=[d.strip().lower() for d in os.environ.get('PAGEMETRICS_EMAIL_DOMAINS','lnmiit.ac.in').split(',') if d.strip()]
    if allowed and user['email'].rsplit('@',1)[1] not in allowed:
        raise APIError('This account does not use an approved institutional email domain.',403)
    now=int(time.time())
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT * FROM email_verifications WHERE user_id=?',(user['id'],)).fetchone()
        if old and now-old['sent_at']<60: raise APIError('Wait 60 seconds before requesting another code.',429)
        count=old['send_count'] if old and now-old['window_start']<3600 else 0
        start=old['window_start'] if count else now
        if count>=5: raise APIError('Hourly email limit reached. Try again later.',429)
        key='otp-send:'+remote
        limit=db.execute('SELECT * FROM login_attempts WHERE key=?',(key,)).fetchone()
        if limit and limit['reset_at']>now and limit['failures']>=20:
            raise APIError('Too many verification emails requested. Try again later.',429)
        code=f'{secrets.randbelow(1000000):06d}'
        try: send_verification_code(user['email'],code)
        except DeliveryError as error: raise APIError(str(error),503,'EMAIL_DELIVERY_FAILED') from None
        db.execute('INSERT INTO email_verifications VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET code_hash=excluded.code_hash,expires_at=excluded.expires_at,attempts=0,sent_at=excluded.sent_at,window_start=excluded.window_start,send_count=excluded.send_count',
                   (user['id'],password_hash(code),now+600,0,now,start,count+1))
        db.execute('INSERT INTO login_attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET failures=CASE WHEN reset_at<=? THEN 1 ELSE failures+1 END,reset_at=CASE WHEN reset_at<=? THEN ? ELSE reset_at END',(key,now+3600,now,now,now+3600))
        audit(db,user,'EMAIL_CODE_SENT')
    return {'message':'Verification code sent. It expires in 10 minutes.','resendAfter':60}

def verify_email_code(data, remote='local'):
    user=authenticate(data,remote)
    code=clean_text(data,'code',6)
    if not re.fullmatch(r'[0-9]{6}',code): raise APIError('Enter the six-digit verification code.')
    now=int(time.time())
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        record=db.execute('SELECT * FROM email_verifications WHERE user_id=?',(user['id'],)).fetchone()
        if user['email_verified'] or not record or record['expires_at']<=now:
            raise APIError('The code has expired or has already been used. Request a new code.')
        if record['attempts']>=5: raise APIError('Too many incorrect codes. Request a new code.',429)
        if not password_matches(code,record['code_hash']):
            db.execute('UPDATE email_verifications SET attempts=attempts+1 WHERE user_id=?',(user['id'],))
            audit(db,user,'EMAIL_VERIFICATION','FAILED'); db.commit()
            raise APIError('The verification code is incorrect.')
        db.execute('UPDATE users SET email_verified=1 WHERE id=?',(user['id'],))
        # Retain only rate-limit metadata until expiry; remove usable code material.
        db.execute("UPDATE email_verifications SET code_hash='',expires_at=0 WHERE user_id=?",(user['id'],))
        audit(db,user,'EMAIL_VERIFICATION')
    return {'message':'Email verified. Your staff role still requires administrator approval.' if user['status']=='pending' else 'Email verified. You can now sign in.'}


def session(token):
    if not token:
        raise APIError('Sign in to continue.', 401)
    with connect() as db:
        row = db.execute('SELECT u.*, s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE token_hash=? AND expires_at>? AND u.status=\'active\'',
                         (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
    if not row or row['role'] not in ROLES or awaiting_email(row):
        raise APIError('Your session has expired. Please sign in again.', 401)
    return row

def require_role(user, roles):
    if user['role'] not in roles:
        raise APIError('Your role does not have permission for this action.', 403)

def require_permission(user, permission):
    if permission not in PERMISSIONS.get(user['role'], set()):
        raise APIError('Your role does not have permission for this action.', 403)

def sample_data():
    titles = ['Introduction to Algorithms', 'The Great Gatsby', 'Engineering Mechanics', 'Linear Algebra Done Right', 'A Brief History of Time', 'The Discovery of India', 'Clean Code', 'Pride and Prejudice', 'The Design of Everyday Things', 'Calculus', 'The Selfish Gene', 'Sapiens']
    rows = []
    for i in range(864):
        date = dt.date(2026, 1, 1) + dt.timedelta(days=(i*37)%270)
        returned = i%7 != 0
        rows.append(dict(zip(FIELDS, [f'C-{i+1}', str(date), str(date+dt.timedelta(days=5+i%16)) if returned else '', ('RETURNED_LATE' if i%9 == 0 else 'RETURNED_ON_TIME') if returned else 'NOT_RETURNED', f'R-{i%12}', titles[i%12], SUBJECTS[i%6], ['005','800','620','510','500','900'][i%6], ['Print','Print','E-book','Journal','Print','Audio','E-book'][i%7], f'anon-{(i*13)%217}', ['STUDENT','STUDENT','STUDENT','FACULTY','STAFF'][i%5]])))
    return rows

def read_dataset():
    with connect() as db:
        saved = db.execute('SELECT records FROM dataset WHERE id=1').fetchone()
    return json.loads(saved['records']) if saved else sample_data(), bool(saved)

def get_records(user):
    require_permission(user, 'explore')
    records, imported = read_dataset()
    if user['role'] == 'faculty':
        records = [r for r in records if r['subject'] == user['subject']]
    return {'records': records, 'imported': imported}

def report_options(user):
    require_permission(user, 'reports')
    records, _ = read_dataset()
    if user['role']=='faculty': records=[r for r in records if r['subject']==user['subject']]
    options = {key: sorted({r[key] for r in records}) for key in ('subject','deweyClass','format','userSegment')}
    options['resourceId'] = [{'value':key,'label':title} for key,title in sorted({r['resourceId']:r['title'] for r in records}.items())]
    return {'options':options}

def get_report(user, criteria=None):
    require_permission(user, 'reports')
    try: criteria=validate_criteria(criteria)
    except ValueError as error: raise APIError(str(error))
    records, imported = read_dataset()
    if user['role']=='faculty':
        if any(value!=user['subject'] for value in criteria['subject']): raise APIError('Subject access is restricted.',403)
        records=[r for r in records if r['subject']==user['subject']]
    records=filter_rows(records,criteria)
    result=aggregate(records,criteria.get('grouping','MONTHLY'))
    result.update(imported=imported,criteria=criteria)
    return result


def valid_date(value):
    try:
        return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)) and str(dt.date.fromisoformat(value)) == value
    except (ValueError, TypeError):
        return False

def validate_import(text):
    if not isinstance(text, str) or len(text.encode()) > 5*1024*1024:
        raise APIError('CSV must be smaller than 5 MB.')
    try:
        rows = list(csv.reader(io.StringIO(text.lstrip('\ufeff')), strict=True))
    except csv.Error:
        raise APIError('Invalid CSV quoting.')
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise APIError('Include a header and at least one record.')
    headers = [h.strip() for h in rows.pop(0)]
    if any(h not in FIELDS for h in headers):
        raise APIError('PRIVACY_REJECTED: Remove personal or unrecognized columns.')
    if len(headers) != len(FIELDS) or set(headers) != set(FIELDS):
        raise APIError('Required columns are missing or duplicated.')
    accepted, errors, seen = [], [], set()
    for number, cells in enumerate(rows, 1):
        r = dict(zip(headers, [c.strip() for c in cells]))
        reason = ''
        if len(cells) != len(headers): reason = 'Incorrect column count'
        elif any(not r[k] for k in FIELDS if k != 'returnDate'): reason = 'Required field is empty'
        elif not valid_date(r['checkoutDate']): reason = 'Invalid checkout date'
        elif r['returnDate'] and (not valid_date(r['returnDate']) or r['returnDate'] < r['checkoutDate']): reason = 'Invalid return date or return before checkout'
        elif r['returnStatus'] not in STATUSES: reason = 'Invalid return status'
        elif r['userSegment'] not in {'STUDENT', 'FACULTY', 'STAFF'}: reason = 'Invalid user segment'
        elif r['format'] not in {'Print','E-book','Journal','Audio','Media'}: reason = 'Invalid resource format'
        elif not re.fullmatch(r'anon-[a-zA-Z0-9_-]+', r['anonymizedReaderId']): reason = 'Reader ID must be an anonymous token beginning anon-'
        elif any(re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)(?:\+?\d[ -]?){10,15}(?!\d)',r[k]) for k in ('title','subject','anonymizedReaderId')): reason = 'Possible personal contact information'
        elif r['circulationId'] in seen: reason = 'Duplicate circulation ID'
        if reason: errors.append({'row': number, 'reason': reason})
        else:
            accepted.append(r)
            seen.add(r['circulationId'])
    return accepted, errors

def save_records(db, accepted):
    db.execute('INSERT INTO dataset VALUES(1,?) ON CONFLICT(id) DO UPDATE SET records=excluded.records', (json.dumps(accepted),))

def import_csv(text, user):
    require_permission(user, 'import')
    with connect() as db:
        job_id=db.execute('INSERT INTO import_jobs(actor_id,created_at,state) VALUES(?,?,?)',(user['id'],int(time.time()),'AVAILABLE')).lastrowid
        for state in ('AVAILABLE','SELECTED','VALIDATING'): import_state(db,job_id,state)
    try:
        accepted,errors=validate_import(text)
        if not accepted:
            with connect() as db:
                import_state(db,job_id,'REJECTED')
                db.execute('UPDATE import_jobs SET rejected_count=? WHERE id=?',(len(errors),job_id))
                audit(db,user,'IMPORT','REJECTED',{'jobId':job_id,'rejected':len(errors)})
        else:
            with connect() as db:
                import_state(db,job_id,'VALIDATED')
                import_state(db,job_id,'PROCESSING')
            with connect() as db:
                save_records(db,accepted)
                db.execute('UPDATE import_jobs SET imported_count=?,rejected_count=? WHERE id=?',(len(accepted),len(errors),job_id))
                import_state(db,job_id,'PROCESSED')
                audit(db,user,'IMPORT','PARTIAL_SUCCESS' if errors else 'SUCCESS',{'jobId':job_id,'imported':len(accepted),'rejected':len(errors)})
        return {'jobId':job_id,'status':'REJECTED' if not accepted else 'PARTIAL_SUCCESS' if errors else 'SUCCESS','importedCount':len(accepted),'rejectedCount':len(errors),'errors':errors[:100]}
    except Exception as error:
        with connect() as db:
            state='REJECTED' if isinstance(error,APIError) else 'FAILED'
            import_state(db,job_id,state)
            audit(db,user,'IMPORT',state,{'jobId':job_id})
        raise


def user_list(user):
    require_permission(user, 'approve_accounts')
    with connect() as db:
        return [public_user(row) for row in db.execute('SELECT * FROM users ORDER BY created_at DESC,id DESC')]

def review_user(user, data):
    require_permission(user, 'approve_accounts')
    target, action = data.get('id'), data.get('action')
    if type(target) is not int or action not in {'approve', 'reject'}:
        raise APIError('Choose a valid account and approval action.')
    if action=='approve' and data.get('identityVerified') is not True:
        raise APIError('Confirm that institutional identity and requested role were verified before approval.')
    with connect() as db:
        row = db.execute('SELECT * FROM users WHERE id=?', (target,)).fetchone()
        if not row or row['status'] != 'pending' or row['role'] not in ROLES:
            raise APIError('This account is no longer awaiting review.', 409)
        if action=='approve' and awaiting_email(row): raise APIError('The applicant must verify their email before approval.')
        db.execute('UPDATE users SET status=? WHERE id=?', ('active' if action == 'approve' else 'rejected', target))
        audit(db,user,'ACCOUNT_REVIEW',details={'targetId':target,'action':action,'identityVerified':action=='approve'})
    return {'message': 'Account approved.' if action == 'approve' else 'Account rejected.'}

DUMMY_HASH = password_hash('constant-dummy-password-not-an-account')

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'dist'), **kwargs)

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Frame-Options', 'DENY')
        super().end_headers()

    def send_json(self, value, status=200, cookie=None):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        if cookie: self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(payload)

    def token(self):
        cookie = SimpleCookie()
        try: cookie.load(self.headers.get('Cookie', ''))
        except Exception: return ''
        return cookie['pm_session'].value if 'pm_session' in cookie else ''

    def cookie(self, token, age=SESSION_SECONDS):
        secure = '; Secure' if os.environ.get('PAGEMETRICS_SECURE_COOKIES') == '1' else ''
        return f'pm_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}{secure}'

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith('/api/'):
            try:
                user = session(self.token())
                if path == '/api/me': result = {'user': public_user(user), 'csrf': user['csrf']}
                elif path == '/api/records': result = get_records(user)
                elif path == '/api/reports':
                    query=parse_qs(urlparse(self.path).query)
                    criteria={key:values[-1] if key in {'start','end','grouping'} else values for key,values in query.items()}
                    result = get_report(user,criteria)
                elif path == '/api/report-options': result = report_options(user)
                elif path == '/api/import-history': result = import_history(user)
                elif path == '/api/audit':
                    raw=parse_qs(urlparse(self.path).query).get('offset',['0'])[0]
                    if not raw.isdigit(): raise APIError('Invalid page offset.')
                    result=audit_history(user,int(raw))
                elif path == '/api/users': result = {'users': user_list(user)}
                else: raise APIError('Endpoint not found.', 404)
                self.send_json(result)
            except APIError as error: self.send_json({'error': str(error), 'code': error.code}, error.status)
            except Exception: self.send_json({'error': 'The server could not complete the request.'}, 500)
        elif path in {'/', '/index.html', '/login', '/register', '/style.css', '/app.js', '/analytics.js', '/auth.js'}:
            if path in {'/login', '/register'}: self.path = '/index.html'
            super().do_GET()
        else:
            self.send_error(404)

    def do_HEAD(self):
        if urlparse(self.path).path not in {'/', '/index.html', '/style.css', '/app.js', '/analytics.js', '/auth.js'}:
            self.send_error(404)
        else: super().do_HEAD()

    def do_POST(self):
        try:
            # Custom JSON header prevents cross-origin simple requests. No CORS is enabled.
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json' or self.headers.get('X-PageMetrics') != '1':
                raise APIError('Unsupported request.', 415)
            origin = self.headers.get('Origin')
            if origin and urlparse(origin).netloc != self.headers.get('Host'):
                raise APIError('Cross-origin requests are not permitted.', 403)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 6*1024*1024: raise APIError('Request is too large or empty.', 413)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict): raise APIError('Invalid request body.')
            path = urlparse(self.path).path
            if path == '/api/reset-password':
                self.send_json(reset_password(data)); return
            if path == '/api/register':
                if 'confirmPassword' in data and data['confirmPassword'] != data.get('password'):
                    raise APIError('The passwords do not match.')
                self.send_json({'user': register(data)}, 201)
                return
            if path in ('/api/request-email-code', '/api/verify-email') and not requires_email_code():
                raise APIError('Email verification is disabled for this workspace.', 403)
            if path == '/api/request-email-code':
                self.send_json(request_email_code(data,self.client_address[0])); return
            if path == '/api/verify-email':
                self.send_json(verify_email_code(data,self.client_address[0])); return
            if path == '/api/login':
                token, csrf, user = login(data, self.client_address[0])
                # Rotate any existing browser session on a new sign-in.
                with connect() as db:
                    db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(self.token().encode()).hexdigest(),))
                self.send_json({'user': user, 'csrf': csrf}, cookie=self.cookie(token))
                return
            user = session(self.token())
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), user['csrf']):
                raise APIError('Invalid request token. Refresh and try again.', 403)
            if path == '/api/logout':
                with connect() as db:
                    db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(self.token().encode()).hexdigest(),))
                    audit(db,user,'LOGOUT')
                self.send_json({'message': 'Signed out.'}, cookie=self.cookie('', 0))
                return
            if path == '/api/import': result = import_csv(data.get('csv'), user)
            elif path == '/api/restore':
                require_permission(user, 'import')
                with connect() as db:
                    db.execute('DELETE FROM dataset')
                    audit(db,user,'RESTORE_SAMPLE')
                result = {'message': 'Sample dataset restored.'}
            elif path == '/api/users/review': result = review_user(user, data)
            else: raise APIError('Endpoint not found.', 404)
            self.send_json(result)
        except APIError as error: self.send_json({'error': str(error), 'code': error.code}, error.status)
        except (ValueError, UnicodeError): self.send_json({'error': 'Invalid request body.'}, 400)
        except Exception: self.send_json({'error': 'The server could not complete the request. Existing data was retained.'}, 500)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='PageMetrics local server')
    parser.add_argument('--issue-recovery-key', metavar='EMAIL', help='Issue a replacement recovery key from the trusted local terminal')
    parser.add_argument('--create-admin', action='store_true', help='Create the first administrator using terminal prompts')
    parser.add_argument('--port', type=int, default=5173)
    args = parser.parse_args()
    initialize()
    if args.issue_recovery_key:
        with connect() as db:
            user = db.execute('SELECT * FROM users WHERE email=?', (args.issue_recovery_key.strip().lower(),)).fetchone()
            if not user:
                raise SystemExit('Account not found in this project database.')
            key = issue_recovery_key(db, user['id'])
            audit(db, user, 'LOCAL_RECOVERY_KEY_ISSUED')
        print('Save this private recovery key:', key)
    elif args.create_admin:
        try:
            name = input('Administrator name: ')
            email = input('Administrator email: ')
            password = getpass.getpass('Password (12–128 characters): ')
            if password != getpass.getpass('Confirm password: '): raise APIError('Passwords do not match.')
            register({'name': name, 'email': email, 'password': password, 'role': 'administrator'}, bootstrap=True)
            print('Administrator created. Start the server with npm start.')
        except APIError as error: raise SystemExit(str(error))
    else:
        httpd = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
        print(f'PageMetrics: http://127.0.0.1:{args.port}', flush=True)
        try: httpd.serve_forever()
        except KeyboardInterrupt: httpd.server_close()
