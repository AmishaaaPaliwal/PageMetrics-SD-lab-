"""Gmail SMTP transport. Secrets come from environment; never log messages/codes."""
import os
import smtplib
import socket
import ssl
from email.message import EmailMessage

class DeliveryError(Exception):
    pass

# Send a short-lived registration code using authenticated Gmail SMTP over verified TLS.
def send_verification_code(recipient, code):
    # Read the sender address from the server process environment.
    sender = os.environ.get('PAGEMETRICS_GMAIL_ADDRESS', '').strip()
    # Read the App Password and remove display-grouping spaces.
    password = os.environ.get('PAGEMETRICS_GMAIL_APP_PASSWORD', '').replace(' ', '')
    # Stop before connecting when sender credentials are missing.
    if not sender or not password:
        raise DeliveryError('Email delivery is not configured. Ask the administrator to configure Gmail SMTP, then resend the code.')
    # Build an email object with headers and plain-text content.
    message = EmailMessage()
    # Use the authenticated Gmail sender as the message author.
    message['From'] = sender
    # Address the verification email to the registered account.
    message['To'] = recipient
    # Give the email a recognizable verification subject.
    message['Subject'] = 'Verify your PageMetrics email'
    # Include the one-time code, expiry and role-approval explanation.
    message.set_content(f'Your PageMetrics verification code is {code}.\n\nIt expires in 10 minutes and can be used once. Do not share this code.\nIf you did not request this email, ignore it.\n\nEmail verification does not approve a staff role.')
    try:
        # Open the Gmail submission port with a bounded connection timeout.
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=15) as smtp:
            # Negotiate the SMTP capabilities supported by the server.
            smtp.ehlo()
            # Upgrade the connection to TLS and verify Gmail’s server certificate.
            smtp.starttls(context=ssl.create_default_context())
            # Negotiate the SMTP capabilities supported by the server.
            smtp.ehlo()
            # Authenticate using the sender’s App Password.
            smtp.login(sender, password)
            # A nonempty refusal result means at least one recipient was rejected.
            if smtp.send_message(message):
                raise DeliveryError('Email could not be sent. Ask the administrator to check Gmail SMTP, then try again.')
    # Translate rejected credentials into a safe, actionable UI error.
    except smtplib.SMTPAuthenticationError:
        raise DeliveryError('Gmail rejected the sender login. Restart the Gmail launcher with an App Password for the sender account.') from None
    # Identify a recipient-address failure without returning SMTP internals.
    except smtplib.SMTPRecipientsRefused:
        raise DeliveryError('Gmail refused the recipient address. Check the registered email address.') from None
    # Report certificate validation failure while retaining TLS verification.
    except ssl.SSLCertVerificationError:
        raise DeliveryError('Python could not verify the Gmail TLS certificate. Check the Python certificate installation and system clock.') from None
    # Explain common connection failures without exposing connection internals.
    except (socket.gaierror, TimeoutError, ConnectionRefusedError):
        raise DeliveryError('PageMetrics could not reach smtp.gmail.com on port 587. Check the network connection and SMTP access.') from None
    # Return the numeric SMTP status while omitting the raw server response.
    except smtplib.SMTPResponseException as error:
        raise DeliveryError(f'Gmail declined the email operation (SMTP {error.smtp_code}).') from None
    # Provide a generic fallback for other transport failures.
    except (OSError, smtplib.SMTPException):
        raise DeliveryError('Email could not be sent. Ask the administrator to check Gmail SMTP, then try again.') from None
