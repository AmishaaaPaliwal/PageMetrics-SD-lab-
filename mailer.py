"""Gmail SMTP transport. Secrets come from environment; never log messages/codes."""
import os
import smtplib
import ssl
from email.message import EmailMessage

class DeliveryError(Exception):
    pass

def send_verification_code(recipient, code):
    sender = os.environ.get('PAGEMETRICS_GMAIL_ADDRESS', '').strip()
    password = os.environ.get('PAGEMETRICS_GMAIL_APP_PASSWORD', '').replace(' ', '')
    if not sender or not password:
        raise DeliveryError('Email delivery is not configured. Ask the administrator to configure Gmail SMTP, then resend the code.')
    message = EmailMessage()
    message['From'] = sender
    message['To'] = recipient
    message['Subject'] = 'Verify your PageMetrics email'
    message.set_content(f'Your PageMetrics verification code is {code}.\n\nIt expires in 10 minutes and can be used once. Do not share this code.\nIf you did not request this email, ignore it.\n\nEmail verification does not approve a staff role.')
    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(sender, password)
            if smtp.send_message(message):
                raise DeliveryError('Email could not be sent. Ask the administrator to check Gmail SMTP, then try again.')
    except (OSError, smtplib.SMTPException):
        raise DeliveryError('Email could not be sent. Ask the administrator to check Gmail SMTP, then try again.') from None
