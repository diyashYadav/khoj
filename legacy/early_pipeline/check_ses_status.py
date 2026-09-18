









import boto3

ses = boto3.client("ses")
sesv2 = boto3.client("sesv2")


def check():
    print("=" * 60)
    print("SES ACCOUNT STATUS")
    print("=" * 60)

    try:
        account = sesv2.get_account()
        sending_enabled = account.get("SendingEnabled", "unknown")
        production_access = account.get("ProductionAccessEnabled", False)
        print(f"Sending enabled       : {sending_enabled}")
        print(f"Production access     : {production_access}")
        if not production_access:
            print("\n  -> You're in SANDBOX MODE.")
            print("     You can only send TO addresses verified below.")
            print("     To reach real users, request production access:")
            print("     SES Console -> Account dashboard -> 'Request production access'")
    except Exception as exc:
        print(f"Could not fetch account status: {exc}")

    print("\n" + "=" * 60)
    print("VERIFIED IDENTITIES (emails/domains you can send FROM,")
    print("and in sandbox mode, also the only addresses you can send TO)")
    print("=" * 60)

    try:
        identities = ses.list_identities()["Identities"]
        if not identities:
            print("No verified identities found — you need to verify at least one")
            print("email address before you can send anything, even in sandbox mode.")
            print("SES Console -> Verified identities -> Create identity")
        else:
            for identity in identities:
                status = ses.get_identity_verification_attributes(Identities=[identity])
                verification = status["VerificationAttributes"].get(identity, {})
                print(f"  {identity}: {verification.get('VerificationStatus', 'unknown')}")
    except Exception as exc:
        print(f"Could not fetch identities: {exc}")

    print("\n" + "=" * 60)
    print("SENDING QUOTA")
    print("=" * 60)
    try:
        quota = ses.get_send_quota()
        print(f"Max 24hr send         : {quota['Max24HourSend']}")
        print(f"Sent in last 24hr     : {quota['SentLast24Hours']}")
        print(f"Max send rate/sec     : {quota['MaxSendRate']}")
    except Exception as exc:
        print(f"Could not fetch quota: {exc}")


if __name__ == "__main__":
    check()
