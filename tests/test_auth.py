import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import server

class FakeSocket:
    def __init__(self, raw):
        self.input = io.BytesIO(raw)
        self.output = bytearray()
    def makefile(self, *args): return self.input
    def sendall(self, data): self.output.extend(data)

class AuthTests(unittest.TestCase):
    def setUp(self):
        self.domain_patch=patch.dict(server.os.environ,{'PAGEMETRICS_EMAIL_DOMAINS':'example.edu'})
        self.domain_patch.start()
        self.mailbox={}
        self.mail_patch=patch('server.send_verification_code',side_effect=lambda email,code:self.mailbox.update({email:code}))
        self.mail_patch.start()
        base = server.ROOT / '.test-data'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.original_path = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / 'test.sqlite3'
        server.initialize()
        self.admin = server.register(self.data('administrator'), bootstrap=True)
    def tearDown(self):
        self.domain_patch.stop()
        self.mail_patch.stop()
        server.DB_PATH = self.original_path
        self.temp.cleanup()
    def data(self, role='faculty', email=None):
        return {'name':role.title(), 'email':email or f'{role}@example.edu', 'password':'long-test-password-123', 'role':role, 'subject':'Computer Science'}
    def active(self, role):
        user = server.register(self.data(role))
        self.verify(self.data(role))
        server.review_user(self.admin, {'id':user['id'], 'action':'approve', 'identityVerified':True})
        return server.login(self.data(role))
    def verify(self,data):
        server.request_email_code(data)
        return server.verify_email_code({**data,'code':self.mailbox[data['email'].lower()]})
    def http(self, path, method='GET', body=None, token='', csrf='', origin=None, custom=True):
        payload = json.dumps(body).encode() if body is not None else b''
        headers = [f'{method} {path} HTTP/1.1', 'Host: 127.0.0.1:5173', 'Connection: close']
        if body is not None:
            headers.extend(['Content-Type: application/json', f'Content-Length: {len(payload)}'])
            if custom: headers.append('X-PageMetrics: 1')
        if token: headers.append('Cookie: pm_session='+token)
        if csrf: headers.append('X-CSRF-Token: '+csrf)
        if origin: headers.append('Origin: '+origin)
        sock = FakeSocket(('\r\n'.join(headers)+'\r\n\r\n').encode()+payload)
        with patch.object(server.Handler, 'log_message'):
            server.Handler(sock, ('127.0.0.1', 1234), SimpleNamespace())
        header, content = bytes(sock.output).split(b'\r\n\r\n',1)
        return int(header.split()[1]), header.decode(), json.loads(content) if content.startswith(b'{') else content

    def test_registration_does_not_grant_staff_privileges(self):
        for role in ['librarian','faculty','administrator','management']:
            user=server.register(self.data(role,role+'2@example.edu'))
            self.assertEqual(user['status'],'pending')
            with self.assertRaises(server.APIError) as e: server.login(self.data(role,role+'2@example.edu'))
            self.assertEqual(e.exception.status,403)
    def test_staff_login_and_password_storage(self):
        token,csrf,user=self.active('faculty')
        self.assertEqual(server.session(token)['role'],'faculty')
        self.assertNotIn('password_hash',user)
        with server.connect() as db:
            row=db.execute('SELECT password_hash FROM users WHERE id=?',(user['id'],)).fetchone()
        self.assertNotIn(self.data()['password'],row['password_hash'])
        self.assertTrue(csrf)
    def test_cannot_bootstrap_second_administrator(self):
        with self.assertRaises(server.APIError): server.register(self.data('administrator','other@example.edu'),bootstrap=True)
    def test_case_insensitive_duplicate_and_invalid_registration(self):
        server.register(self.data())
        with self.assertRaises(server.APIError): server.register(self.data(email='FACULTY@EXAMPLE.EDU'))
        for field,value in [('role','superuser'),('password','short'),('email','invalid')]:
            data=self.data(email='new@example.edu'); data[field]=value
            with self.assertRaises(server.APIError): server.register(data)
    def test_approval_is_admin_only_and_pending_only(self):
        _,_,student=self.active('faculty')
        pending=server.register(self.data('librarian'))
        with self.assertRaises(server.APIError): server.review_user(student,{'id':pending['id'],'action':'approve','identityVerified':True})
        self.verify(self.data('librarian'))
        server.review_user(self.admin,{'id':pending['id'],'action':'approve','identityVerified':True})
        self.assertEqual(server.login(self.data('librarian'))[2]['status'],'active')
        with self.assertRaises(server.APIError): server.review_user(self.admin,{'id':pending['id'],'action':'reject'})
    def test_rejected_account_cannot_login(self):
        pending=server.register(self.data('faculty'))
        server.review_user(self.admin,{'id':pending['id'],'action':'reject'})
        with self.assertRaises(server.APIError): server.login(self.data('faculty'))
    def test_faculty_data_is_scoped_on_server(self):
        token,_,_=self.active('faculty')
        records=server.get_records(server.session(token))['records']
        self.assertTrue(records)
        self.assertEqual({r['subject'] for r in records},{'Computer Science'})
    def test_unauthorized_api_access_and_mutations(self):
        self.assertEqual(self.http('/api/records')[0],401)
        token,csrf,_=self.active('faculty')
        for path,body in [('/api/import',{'csv':'bad'}),('/api/restore',{}),('/api/users/review',{'id':1,'action':'approve','identityVerified':True})]:
            self.assertEqual(self.http(path,'POST',body,token,csrf)[0],403)
        self.assertEqual(self.http('/api/users',token=token)[0],403)
    def test_csrf_and_cross_origin_protection(self):
        token,csrf,_=server.login(self.data('administrator'))
        self.assertEqual(self.http('/api/restore','POST',{},token)[0],403)
        self.assertEqual(self.http('/api/restore','POST',{},token,csrf,origin='https://evil.example')[0],403)
        self.assertEqual(self.http('/api/login','POST',self.data('administrator'),custom=False)[0],415)
    def test_login_cookie_logout_and_session_expiry(self):
        code,headers,data=self.http('/api/login','POST',self.data('administrator'))
        self.assertEqual(code,200)
        self.assertIn('HttpOnly',headers); self.assertIn('SameSite=Strict',headers)
        cookie=next(line for line in headers.split('\r\n') if line.startswith('Set-Cookie:'))
        token=cookie.split('pm_session=')[1].split(';')[0]
        self.assertEqual(self.http('/api/logout','POST',{},token,data['csrf'])[0],200)
        self.assertEqual(self.http('/api/me',token=token)[0],401)
        token,_,_=server.login(self.data('administrator'))
        with patch('server.time.time',return_value=time.time()+server.SESSION_SECONDS+1):
            with self.assertRaises(server.APIError): server.session(token)
    def test_login_throttling(self):
        data=self.data('administrator');data['password']='incorrect-password-123'
        for _ in range(10):
            with self.assertRaises(server.APIError):server.login(data)
        with self.assertRaises(server.APIError) as error:server.login(data)
        self.assertEqual(error.exception.status,429)
    def test_librarian_import_validation_transaction_and_shared_data(self):
        _,_,librarian=self.active('librarian')
        output=io.StringIO(); writer=server.csv.DictWriter(output,fieldnames=server.FIELDS);writer.writeheader()
        rows=server.sample_data()[:2]; rows[1]['checkoutDate']='2026-02-30';writer.writerows(rows)
        result=server.import_csv(output.getvalue(),librarian)
        self.assertEqual(result['status'],'PARTIAL_SUCCESS');self.assertEqual(result['importedCount'],1)
        before=server.get_records(librarian)
        with self.assertRaises(server.APIError):server.import_csv('email,name\nperson@example.edu,Person',librarian)
        self.assertEqual(server.get_records(librarian),before)
        with patch('server.connect',side_effect=server.sqlite3.OperationalError('disk full')):
            with self.assertRaises(server.sqlite3.OperationalError):server.import_csv(output.getvalue(),librarian)
        self.assertEqual(server.get_records(librarian),before)
    def test_rbac_endpoint_matrix_for_all_roles(self):
        expected = {
            'faculty': (200,200,403),
            'librarian': (200,200,403),
            'administrator': (200,200,200),
            'management': (403,200,403),
        }
        for role,statuses in expected.items():
            token,csrf,user=server.login(self.data(role)) if role=='administrator' else self.active(role)
            with self.subTest(role=role):
                for path,status in zip(['/api/records','/api/reports','/api/users'],statuses):
                    self.assertEqual(self.http(path,token=token)[0],status)
                self.assertEqual(self.http('/api/restore','POST',{},token,csrf)[0],200 if role=='librarian' else 403)
                self.assertEqual(self.http('/api/import','POST',{'csv':'bad'},token,csrf)[0],400 if role=='librarian' else 403)
                code,_,me=self.http('/api/me',token=token)
                self.assertEqual(code,200)
                self.assertEqual(set(me['user']['permissions']),server.PERMISSIONS[role])

    def test_management_report_is_aggregate_and_matches_dataset(self):
        _,_,user=self.active('management')
        report=server.get_report(user)
        rows=server.sample_data()
        self.assertEqual(report['totalCheckouts'],len(rows))
        self.assertEqual(sum(report['months'].values()),len(rows))
        self.assertEqual(sum(report['subjects'].values()),len(rows))
        self.assertEqual(sum(report['formats'].values()),len(rows))
        self.assertEqual(sum(report['segments'].values()),len(rows))
        self.assertEqual(report['resourcesUsed'],12)
        self.assertEqual(report['uniqueReaders'],217)
        serialized=json.dumps(report)
        for forbidden in ['anonymizedReaderId','circulationId','anon-','records']:
            self.assertNotIn(forbidden,serialized)
        with server.connect() as db: db.execute("INSERT INTO dataset VALUES(1,'[]')")
        empty=server.get_report(user)
        self.assertEqual(empty['totalCheckouts'],0)
        self.assertIsNone(empty['onTimeRate'])
        self.assertIsNone(empty['dateFrom'])

    def test_user_supplied_permissions_do_not_authorize_requests(self):
        data=self.data('faculty');data['permissions']=['import','approve_accounts']
        user=server.register(data)
        self.assertEqual(user['permissions'],['explore','reports'])
        with self.assertRaises(server.APIError):server.import_csv('bad',user)
        with self.assertRaises(server.APIError):server.user_list(user)

    def test_students_blocked_in_registration_login_and_old_sessions(self):
        with self.assertRaises(server.APIError):server.register(self.data('student'))
        with server.connect() as db:
            uid=db.execute("INSERT INTO users(name,email,password_hash,role,status,created_at) VALUES(?,?,?,?,?,?)",('Old Student','old@example.edu',server.password_hash('long-test-password-123'),'student','active',0)).lastrowid
            token='old-session'
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(server.hashlib.sha256(token.encode()).hexdigest(),uid,'csrf',int(time.time())+9999))
        with self.assertRaises(server.APIError):server.session(token)
        with self.assertRaises(server.APIError):server.login(self.data('student','old@example.edu'))
        server.initialize()
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM users WHERE id=?',(uid,)).fetchone()['status'],'inactive')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions WHERE user_id=?',(uid,)).fetchone()[0],0)

    def test_report_filters_comparisons_and_faculty_scope(self):
        from reporting import filter_rows
        _,_,faculty=self.active('faculty')
        criteria={'start':'2026-01-01','end':'2026-03-31','subject':['Computer Science','Literature'],'userSegment':['STUDENT','FACULTY'],'grouping':'WEEKLY'}
        result=server.get_report(self.admin,criteria)
        expected=filter_rows(server.sample_data(),criteria)
        self.assertEqual(result['totalCheckouts'],len(expected))
        self.assertEqual(sum(result['resources'].values()),len(expected))
        self.assertEqual(sum(result['months'].values()),len(expected))
        with self.assertRaises(server.APIError):server.get_report(faculty,criteria)
        own=server.get_report(faculty)
        self.assertEqual(set(own['subjects']),{'Computer Science'})
        self.assertEqual(server.report_options(faculty)['options']['subject'],['Computer Science'])
        for bad in [{'start':'2026-01-01'},{'start':'2026-12-01','end':'2026-01-01'},{'grouping':'INVALID'}]:
            with self.assertRaises(server.APIError):server.get_report(self.admin,bad)

    def test_audit_and_import_state_history(self):
        _,_,librarian=self.active('librarian')
        output=io.StringIO();writer=server.csv.DictWriter(output,fieldnames=server.FIELDS);writer.writeheader();writer.writerows(server.sample_data()[:3])
        result=server.import_csv(output.getvalue(),librarian)
        job=server.import_history(self.admin)['jobs'][0]
        self.assertEqual(job['id'],result['jobId'])
        self.assertEqual(job['states'],['AVAILABLE','SELECTED','VALIDATING','VALIDATED','PROCESSING','PROCESSED'])
        previous=server.get_records(librarian)
        with patch('server.save_records',side_effect=server.sqlite3.OperationalError('disk full')):
            with self.assertRaises(server.sqlite3.OperationalError):server.import_csv(output.getvalue(),librarian)
        self.assertEqual(server.import_history(self.admin)['jobs'][0]['state'],'FAILED')
        self.assertEqual(server.get_records(librarian),previous)
        with self.assertRaises(server.APIError):server.import_csv('email,name\nsensitive@example.edu,Name',librarian)
        self.assertEqual(server.import_history(self.admin)['jobs'][0]['state'],'REJECTED')
        events=server.audit_history(self.admin)['events']
        self.assertTrue(any(r['event']=='IMPORT' and r['outcome']=='FAILED' for r in events))
        serialized=json.dumps(events)
        self.assertNotIn('sensitive@example.edu',serialized)
        self.assertNotIn('long-test-password',serialized)
        with self.assertRaises(server.APIError):server.audit_history(librarian)

    def test_approval_requires_manual_verification_and_domain_policy(self):
        pending=server.register(self.data('faculty'))
        with self.assertRaises(server.APIError):server.review_user(self.admin,{'id':pending['id'],'action':'approve'})
        with patch.dict(server.os.environ,{'PAGEMETRICS_EMAIL_DOMAINS':'institution.edu'}):
            with self.assertRaises(server.APIError):server.register(self.data('management','person@outside.edu'))
            self.assertEqual(server.register(self.data('management','person@institution.edu'))['status'],'pending')

    def test_lnmiit_default_domain_and_lookalike_rejection(self):
        with patch.dict(server.os.environ,{},clear=True):
            accepted=server.register(self.data('faculty','Teacher@LNMIIT.AC.IN'))
            self.assertEqual(accepted['email'],'teacher@lnmiit.ac.in')
            for email in ['user@gmail.com','user@lnmiit.ac.in.evil.com','user@fake-lnmiit.ac.in']:
                with self.assertRaises(server.APIError):server.register(self.data('faculty',email))

    def test_supplied_circulation_file(self):
        path=server.ROOT/'samples'/'pagemetrics-circulation-sample.csv'
        rows,errors=server.validate_import(path.read_text())
        self.assertEqual(len(rows),864)
        self.assertEqual(errors,[])
        self.assertEqual({r['format'] for r in rows},{'Print','E-book','Journal','Audio','Media'})
        self.assertTrue(all(r['anonymizedReaderId'].startswith('anon-') for r in rows))

    def test_email_otp_required_before_approval_and_login(self):
        data=self.data('librarian');user=server.register(data)
        with self.assertRaises(server.APIError) as error:server.login(data)
        self.assertEqual(error.exception.code,'EMAIL_VERIFICATION_REQUIRED')
        with self.assertRaises(server.APIError):server.review_user(self.admin,{'id':user['id'],'action':'approve','identityVerified':True})
        result=server.request_email_code(data)
        self.assertNotIn('code',result)
        code=self.mailbox[data['email']]
        with server.connect() as db:
            stored=db.execute('SELECT code_hash FROM email_verifications WHERE user_id=?',(user['id'],)).fetchone()[0]
        self.assertNotEqual(stored,code)
        server.verify_email_code({**data,'code':code})
        with self.assertRaises(server.APIError):server.login(data)  # Still pending role approval.
        with self.assertRaises(server.APIError):server.verify_email_code({**data,'code':code})
        server.review_user(self.admin,{'id':user['id'],'action':'approve','identityVerified':True})
        self.assertTrue(server.login(data)[2]['email_verified'])
        self.assertNotIn(code,json.dumps(server.audit_history(self.admin)))

    def test_otp_expiry_attempt_limit_resend_and_delivery_failure(self):
        data=self.data('librarian');server.register(data)
        with patch('server.send_verification_code',side_effect=server.DeliveryError('Email delivery is not configured.')):
            with self.assertRaises(server.APIError) as error:server.request_email_code(data)
            self.assertEqual(error.exception.status,503)
        server.request_email_code(data)
        old=self.mailbox[data['email']]
        with self.assertRaises(server.APIError) as error:server.request_email_code(data)
        self.assertEqual(error.exception.status,429)
        wrong='000000' if old!='000000' else '999999'
        for _ in range(5):
            with self.assertRaises(server.APIError):server.verify_email_code({**data,'code':wrong})
        with self.assertRaises(server.APIError) as error:server.verify_email_code({**data,'code':old})
        self.assertEqual(error.exception.status,429)
        now=time.time()
        with patch('server.time.time',return_value=now+61):
            with patch('server.secrets.randbelow',return_value=int(wrong)):
                server.request_email_code(data)
            with self.assertRaises(server.APIError):server.verify_email_code({**data,'code':old})
        with patch('server.time.time',return_value=now+662):
            with self.assertRaises(server.APIError):server.verify_email_code({**data,'code':wrong})

    def test_otp_is_account_bound_and_hourly_limited(self):
        data=self.data('librarian');server.register(data)
        other=self.data('faculty');server.register(other)
        with patch('server.secrets.randbelow',return_value=123456):server.request_email_code(data)
        with patch('server.secrets.randbelow',return_value=654321):server.request_email_code(other)
        with self.assertRaises(server.APIError):server.verify_email_code({**other,'code':'123456'})
        now=time.time()
        for i in range(1,5):
            with patch('server.time.time',return_value=now+i*61):server.request_email_code(data)
        with patch('server.time.time',return_value=now+305):
            with self.assertRaises(server.APIError) as error:server.request_email_code(data)
            self.assertEqual(error.exception.status,429)

    def test_gmail_transport_uses_tls_and_does_not_leak_errors(self):
        import mailer
        with patch.dict(server.os.environ,{'PAGEMETRICS_GMAIL_ADDRESS':'sender@gmail.com','PAGEMETRICS_GMAIL_APP_PASSWORD':'abcd efgh ijkl mnop'}):
            with patch('mailer.smtplib.SMTP') as smtp:
                client=smtp.return_value.__enter__.return_value;client.send_message.return_value={}
                mailer.send_verification_code('staff@lnmiit.ac.in','123456')
                smtp.assert_called_once_with('smtp.gmail.com',587,timeout=15)
                client.starttls.assert_called_once()
                client.login.assert_called_once_with('sender@gmail.com','abcdefghijklmnop')
                message=client.send_message.call_args[0][0]
                self.assertEqual(message['To'],'staff@lnmiit.ac.in')
                self.assertIn('123456',message.get_content())
            with patch('mailer.smtplib.SMTP',side_effect=mailer.smtplib.SMTPException('secret-password')):
                with self.assertRaises(mailer.DeliveryError) as error:mailer.send_verification_code('staff@lnmiit.ac.in','123456')
                self.assertNotIn('secret-password',str(error.exception))

    def test_database_is_not_served(self):
        self.assertEqual(self.http('/data/pagemetrics.sqlite3')[0],404)
        self.assertEqual(self.http('/server.py')[0],404)

if __name__=='__main__': unittest.main()
