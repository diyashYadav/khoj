








from db_helpers import (
    create_match,
    get_active_cases_due_for_recheck,
    get_found_reports_updated_since,
    get_user_email,
    match_already_exists,
    update_case_after_check,
)
from matching_engine import rank_candidates
from notify import send_match_notification

MATCH_THRESHOLD = 60  


def lambda_handler(event, context):
    cases = get_active_cases_due_for_recheck()
    print(f"{len(cases)} case(s) due for recheck.")

    for case in cases:
        since = case.get("last_checked_at") or case.get("created_at")
        candidates = get_found_reports_updated_since(since)
        print(f"Case {case['case_id']}: {len(candidates)} found-report(s) updated since {since}")

        found_strong_match = False
        if candidates:
            results = rank_candidates(case, candidates)
            for result in results:
                if result["match_score"] < MATCH_THRESHOLD:
                    break  
                found_id = result["candidate"].get("found_id")
                if match_already_exists(case["case_id"], found_id):
                    continue

                match_id = create_match(case["case_id"], found_id, result["match_score"], result["breakdown"])
                found_strong_match = True
                print(f"Match created ({match_id}): case {case['case_id']} <-> {found_id} "
                      f"at {result['match_score']}%")

                reporter_email = get_user_email(case.get("reporter_user_id"))
                if reporter_email:
                    send_match_notification(reporter_email, case["case_id"], found_id, result["match_score"])

        update_case_after_check(case["case_id"], found_strong_match)

    return {"statusCode": 200, "cases_checked": len(cases)}
