# PageMetrics

A local library analytics website with staff authentication, role-based access, CSV imports, combined comparisons, filtered reports, and audit history.

## Start on localhost (macOS)

For a fresh copy, open Terminal and run:

```sh
git clone https://github.com/AmishaaaPaliwal/PageMetrics-SD-lab-.git
cd PageMetrics-SD-lab-
python3 server.py --create-admin
```

This one-time setup asks for your name, @lnmiit.ac.in email, and a password of 12–128 characters. Password typing is hidden in Terminal. It creates the first library administrator; there is no preset password. If it says an active administrator already exists, skip setup and use that account.

For a local demo, run `python3 server.py`. OTP is disabled by default. New and existing pending staff accounts still require administrator approval. To enable email verification again, use the Gmail launcher below:

```sh
python3 start_with_gmail.py
```

Open **http://127.0.0.1:5173** (or **http://localhost:5173**) and sign in. Keep Terminal open while using the site. Press **Control+C** in Terminal to stop it. Next time, run `python3 start_with_gmail.py` again. If SMTP settings are already exported in the environment, `python3 server.py` also works. Python 3.10+ is required; there are no Python packages to install. If Node.js is available, `npm run create-admin` and `npm start` are equivalent shortcuts.

If port 5173 is occupied:

```sh
python3 server.py --port 5174
```

Then open http://127.0.0.1:5174. Do not use `python3 -m http.server`, open index.html directly, or use an editor's static Live Server: authentication requires the Python application server.

## Register staff and import the supplied data

1. Sign in as the administrator to explore the dashboard and reports.
2. Sign out and choose **Create an account**. Register another @lnmiit.ac.in email with the **Librarian** role. Enter the OTP delivered to that institutional inbox. After verification the role remains pending.
3. Sign back in as the administrator. Open **Account approvals**, confirm institutional identity and the requested role, check the verification box, and approve the librarian.
4. Sign in as that librarian. Choose **Import data**, select `samples/pagemetrics-circulation-sample.csv`, then **Validate & import**.
5. The file contains **864 fictional records**, January–September 2026, covering six subjects, 12 resources, five formats, three reader segments and anonymous reader tokens. All 864 rows should import. Successful imports replace the shared dataset.
6. Use multiple selections in the dashboard or report filters to compare subjects, titles, formats and groups. Hold **Command** on macOS or **Ctrl** on Windows when selecting several options. Selections within a field are OR; different fields combine with AND.

Students remain a reader segment in circulation data. They are not application users and cannot register or log in. Legacy student accounts are disabled and their sessions revoked on server startup; history is preserved.

## Permissions

| Role | Dashboard | Reports | Import / restore | Staff approvals / audit |
| --- | --- | --- | --- | --- |
| Librarian | All subjects and filters | Filtered aggregate reports | Yes | No; import history only |
| Library administrator | All subjects and filters | Filtered aggregate reports | No | Yes |
| Faculty / department head | Approved subject only | Approved subject only | No | No |
| University / institute management | No transaction-level endpoint | Filtered aggregate usage and utilization | No | No |

The server checks every endpoint. Registration requires email OTP verification and administrator approval before staff access. OTP proves control of the email inbox, not entitlement to a staff role. Faculty data and filter metadata are scoped on the server. Management reports do not contain reader tokens or individual circulation records.

Administrator approval requires an explicit attestation that institutional identity, role, and faculty subject were verified. Registration defaults to the exact `lnmiit.ac.in` email domain (case-insensitive). Addresses such as `person@lnmiit.ac.in.evil.com` are rejected. `PAGEMETRICS_EMAIL_DOMAINS` can override the domain allowlist for an explicitly configured deployment or isolated tests. Domain screening, OTP inbox verification, and manual role approval are separate checks. This is not institutional SSO. Connecting an institutional identity provider requires actual provider configuration.

## Analytics, reports, and states

- Date boundaries are inclusive; weekly buckets start Monday.
- Seasonal convention: Jan–Mar winter, Apr–Jun spring, Jul–Sep summer, Oct–Dec autumn. Confirm this convention with the team before academic submission.
- On-time rate includes only RETURNED_ON_TIME and RETURNED_LATE in the denominator. No known returned loans yields N/A.
- Reports include the exact applied filters in CSV exports. Aggregates and resource comparisons all use the same filtered records.
- Resource utilization reports count distinct resources borrowed and checkouts by resource/format. A complete catalogue is required to measure zero-use resources or utilization as a percentage of the entire collection.
- Imports record AVAILABLE → SELECTED → VALIDATING → VALIDATED → PROCESSING → PROCESSED. Invalid files/rows can lead to REJECTED; processing/storage failures lead to FAILED. Re-import creates a new attempt with its own history. Availability and selection are recorded when the request arrives, rather than tracking local browser file-picker events on the server.
- Dashboard states explicitly include LOADING, UPDATING, READY, EMPTY, ERROR and CLOSED. Failed dashboard updates retain previous results. KPIs are integrated into the dashboard, not a separate route.
- Activity history records account creation, login success/failure/denial, logout, approvals/rejections, imports, and sample restoration. Audit entries store account IDs/roles and safe counts/statuses, not passwords or reader data. Administrators can browse audit history; librarians can view recent import states.

## Data validation and persistence

Required CSV header:

```text
circulationId,checkoutDate,returnDate,returnStatus,resourceId,title,subject,deweyClass,format,anonymizedReaderId,userSegment
```

CSV files are limited to 5 MB. Dates are YYYY-MM-DD. Return date can be blank. Reader tokens must start with `anon-`. Allowed statuses: NOT_RETURNED, RETURNED_ON_TIME, RETURNED_LATE, UNKNOWN. Formats: Print, E-book, Journal, Audio, Media. Segments: STUDENT, FACULTY, STAFF.

The server rejects unsupported columns, incomplete rows, impossible dates, returns before checkout, unsupported enum values, duplicates, and likely email/phone details in title/subject/reader-token fields. Free-text privacy checks are heuristic, not a guarantee: anonymize real data upstream. Import errors show row numbers/reasons without echoing values. A transaction commits the accepted rows, final import state, and audit event together; failed writes preserve earlier data.

SQLite data lives at `data/pagemetrics.sqlite3`, inside this project and excluded from Git and static routes. Passwords use salted scrypt; session tokens are hashed in the database and expire after eight hours. Cookies use HttpOnly and SameSite=Strict; authenticated mutations require a CSRF token. The app enforces same-origin JSON requests and persistent login-attempt limits.

## Structure and limitations

- `server.py`: HTTP endpoints, authorization, import validation/processing, SQLite persistence and audit/state tracking.
- `mailer.py`: Gmail SMTP transport with TLS; no code or credential logging.
- `start_with_gmail.py`: hidden local credential prompts and server launcher.
- `reporting.py`: independently testable filter validation and report aggregation.
- `dist/auth.js`: authentication and approval UI.
- `dist/analytics.js`: browser dashboard computations.
- `dist/app.js`: dashboard, reports, import/history views and navigation.
- `tests/`: API, permission, import, session, audit and analytics tests.

The current schema uses a validated JSON circulation snapshot rather than separate normalized resource/reader/subject tables. The application implements the main workflows and explicit state history, but does not reproduce every UML class as a code class. No institutional SSO, complete catalogue, or production availability/load guarantee is included. These remain documented integration/modeling limitations, not claimed completed features.

The published Sites URL is the old static prototype. All current work is local to this folder. A production deployment needs Python-compatible hosting, persistent storage, HTTPS and `PAGEMETRICS_SECURE_COOKIES=1`. Do not publish only `dist/` as an authentication-enabled application.

## Tests

```sh
npm test
```

Or independently:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/analytics.test.js
```

Tests use isolated temporary databases inside `.test-data/` and do not change your real accounts or circulation dataset.

## Gmail setup for OTP verification

1. Choose a Gmail account to send verification emails. The sender can be Gmail; registration recipients must still use `@lnmiit.ac.in`.
2. Enable Google **2-Step Verification**, then create a dedicated **App Password** for PageMetrics. Use an App Password, not the normal Google account password. Some Workspace/security policies do not allow App Passwords; consult the account administrator if the option is unavailable. [Google instructions](https://support.google.com/mail/answer/185833?hl=en).
3. Run `python3 start_with_gmail.py`. Enter the Gmail sender address and App Password at the local prompts. Password entry is hidden. The launcher passes these values to the server process without saving them in source, shell history, or a local configuration file.
4. Open http://localhost:5173 and register a staff account with an LNMIIT address. Enter the six-digit email code, then wait for administrator role approval.

SMTP uses `smtp.gmail.com:587` and mandatory STARTTLS with certificate verification. The environment variable names are `PAGEMETRICS_GMAIL_ADDRESS` and `PAGEMETRICS_GMAIL_APP_PASSWORD`. `.env.example` documents them; the application does not auto-load `.env` files. `.env` and `.env.*` secrets are excluded from Git.

OTP controls: 10-minute expiry, single use, salted scrypt storage, five incorrect attempts per code, 60-second resend cooldown, five sends per account per hour, and 20 sends per source IP per hour. Resending invalidates the previous code. Successful verification does not activate a pending staff role. Failed SMTP delivery never marks an address verified or claims delivery succeeded; return to sign-in to resume verification for an already-created account. Code requests and verification require the account password, and attempts use the existing authentication limits.

Existing accounts gain `email_verified=0` on upgrade and must verify before logging in; old unverified sessions are denied. The first administrator created through the trusted local `--create-admin` terminal command is deliberately marked verified so it can bootstrap the approval workflow. There is no browser-accessible bootstrap exception. Administrative role approval is blocked until an applicant's email is verified.

The tests mock SMTP and do not send emails. Actual delivery still needs the user's sender configuration and a successful inbox test; automated tests are not evidence of live Gmail delivery. These codes verify registration/email ownership, not a second factor on every login.

## Forgot password

Save the private recovery key shown at registration. Choose **Forgot password?** on the sign-in screen and enter your email, recovery key, and new password twice. Save the replacement key after each reset. A successful reset signs out prior sessions and preserves the account’s role and approval status.

For an existing account without a key, the trusted local operator can issue a replacement from the project directory containing that account’s database:

```sh
python3 server.py --issue-recovery-key user@lnmiit.ac.in
```

Issuing a replacement invalidates the previous key. Verify the account holder before sharing a key privately.
