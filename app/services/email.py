import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import get_settings

async def send_otp_email(to_email: str, otp: str):
    settings = get_settings()

    print("SMTP HOST:", settings.smtp_host)
    print("SMTP USER:", settings.smtp_user)
    print("SMTP PASS:", settings.smtp_pass[:5], "...")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Verification OTP - IntellectaFlow"
    msg["From"] = f"IntellectaFlow <{settings.smtp_user}>"
    msg["To"] = to_email

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 400px; margin: auto; 
                background: #0C0E14; padding: 32px; border-radius: 12px;">
        <h2 style="color: #F59E0B; margin-bottom: 8px;">Verify your email</h2>
        <p style="color: #888; margin-bottom: 24px;">
            Use the OTP below to complete your registration on IntellectaFlow.
        </p>
        <div style="font-size: 36px; font-weight: bold; letter-spacing: 10px;
                    background: #1a1c24; color: #F59E0B; padding: 20px;
                    text-align: center; border-radius: 8px; margin-bottom: 24px;">
            {otp}
        </div>
        <p style="color: #888; font-size: 13px;">
            This OTP expires in <strong style="color:#fff">5 minutes</strong>.
            If you didn't request this, please ignore this email.
        </p>
    </div>
    """

    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(settings.smtp_user, to_email, msg.as_string())
            print("Email sent successfully to:", to_email)
    except smtplib.SMTPAuthenticationError:
        raise Exception("Gmail authentication failed. Check App Password.")
    except smtplib.SMTPException as e:
        raise Exception(f"SMTP error: {str(e)}")