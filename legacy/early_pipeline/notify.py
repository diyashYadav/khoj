














import boto3

ses = boto3.client("ses")

FROM_EMAIL = "PASTE_YOUR_VERIFIED_SES_EMAIL_HERE"


def send_match_notification(to_email: str, case_id: str, found_id: str, score: float) -> bool:

    if "PASTE_YOUR" in FROM_EMAIL:
        print("FROM_EMAIL is still a placeholder in notify.py — set it to a verified SES sender first.")
        return False

    subject = "Dhund — A potential match was found for your report"
    body = (
        f"Hello,\n\n"
        f"Our system found a potential match for missing-person case {case_id}.\n\n"
        f"Match confidence: {score}/100\n"
        f"Found-record reference: {found_id}\n\n"
        f"Please log in to review the details and confirm or reject this match.\n"
        f"This is an automated notification — no personal contact details are being "
        f"shared without your review.\n\n"
        f"— Dhund"
    )

    try:
        ses.send_email(
            Source=FROM_EMAIL,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            },
        )
        print(f"Notification sent to {to_email} for case {case_id}.")
        return True
    except Exception as exc:
        print(f"Failed to send notification to {to_email}: {exc}")
        return False
