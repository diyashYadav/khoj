import os
import boto3

ses = boto3.client("ses")
email = os.environ["SES_VERIFY_EMAIL"]
response = ses.verify_email_identity(EmailAddress=email)
print(f"Verification email sent to {email}")
print("Check your inbox and click the verification link.")
print(response)
