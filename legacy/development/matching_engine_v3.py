


































import math
import re
from datetime import date, datetime

STOPWORDS = {"the", "a", "an", "on", "near", "with", "and", "of", "his", "her", "was", "were", "is", "are", "person", "found"}
NEGATION_WORDS = {"no", "not", "without", "none", "never", "clean", "absent"}
LOCATION_ALIASES = {"railway": "station", "rly": "station", "ps": "police", "p.s": "police", "stn": "station"}









FIELD_M = {
    "name": 0.95,
    "distinctive_marks": 0.90,  
    "age": 0.85,
    "height_cm": 0.85,
    "complexion": 0.55,  
    "clothing": 0.60,    
    "location": 0.75,
    "time_gap": 0.80,
}

NUMERIC_TOLERANCE = {"age": 3, "height_cm": 8}








def _numeric_bounds(value):
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        try:
            lo, hi = float(value[0]), float(value[1])
            if lo <= 0 and hi <= 0:
                return None
            vals = sorted(v for v in (lo, hi) if v > 0)
            return (vals[0], vals[-1]) if vals else None
        except (TypeError, ValueError):
            return None
    try:
        v = float(value)
        return (v, v) if v > 0 else None
    except (TypeError, ValueError):
        return None


def degree_numeric(value_a, value_b, tolerance):
    a = _numeric_bounds(value_a)
    b = _numeric_bounds(value_b)
    if a is None or b is None:
        return None
    
    
    if max(a[0], b[0]) <= min(a[1], b[1]):
        return 1.0
    gap = b[0] - a[1] if a[1] < b[0] else a[0] - b[1]
    return math.exp(-(gap ** 2) / (2 * tolerance ** 2))


def degree_categorical(value_a, value_b):
    if not value_a or not value_b:
        return None
    return 1.0 if str(value_a).strip().lower() == str(value_b).strip().lower() else 0.0


def _tokens(text):
    return set(re.findall(r"[a-z]+", str(text).lower())) - STOPWORDS


def _has_negation(text):
    words = re.findall(r"[a-z]+", str(text).lower())
    return any(w in NEGATION_WORDS for w in words)


def degree_text_overlap(text_a, text_b):

    if not text_a or not text_b:
        return None
    a, b = _tokens(text_a), _tokens(text_b)
    if not a or not b:
        return None
    overlap = len(a & b) / max(len(a), len(b))
    
    
    if _has_negation(text_a) != _has_negation(text_b):
        negated = b if _has_negation(text_b) else a
        positive = a if _has_negation(text_b) else b
        mark_terms = {"scar", "scars", "mark", "marks", "tattoo", "birthmark", "mole", "injury", "wound"}
        if positive & mark_terms and (negated & mark_terms or "clean" in negated):
            return 0.0
    return overlap


def degree_location(text_a, text_b):
    if not text_a or not text_b:
        return None
    def norm(t):
        words = _tokens(t)
        return {LOCATION_ALIASES.get(w, w) for w in words}
    a, b = norm(text_a), norm(text_b)
    if not a or not b:
        return None
    if a & b:
        return min(1.0, 0.5 + 0.5 * len(a & b) / max(len(a), len(b)))
    return 0.0


def degree_time_gap(date_a, date_b):
    if not date_a or not date_b:
        return None
    try:
        da = date_a if isinstance(date_a, date) else datetime.fromisoformat(date_a).date()
        db = date_b if isinstance(date_b, date) else datetime.fromisoformat(date_b).date()
    except (ValueError, TypeError):
        return None
    days = (db - da).days
    if days < 0:
        return 0.0  
    return math.exp(-days / 30)


def clothing_relevance(days_since_missing):





    if days_since_missing is None:
        return 0.5
    return max(0.0, 1 - days_since_missing / 14)








def passes_hard_filters(missing: dict, found: dict) -> bool:
    g1, g2 = missing.get("gender"), found.get("gender")
    if g1 and g2 and g1.lower() != "unknown" and g2.lower() != "unknown" and g1.lower() != g2.lower():
        return False

    m_age = missing.get("age")
    f_age = found.get("age_range") or found.get("age")
    if m_age is not None and f_age is not None:
        bounds = _numeric_bounds(f_age)
        if bounds:
            
            
            if m_age < bounds[0] - 18 or m_age > bounds[1] + 18:
                return False

    return True









def compute_population_frequencies(candidates: list, missing: dict) -> dict:
    n = len(candidates) or 1
    freqs = {}

    target_name = missing.get("name")
    if target_name:
        count = sum(1 for c in candidates if (degree_name(target_name, c.get("name")) or 0) >= 0.5)
        freqs["name"] = max(count / n, 0.02)
    else:
        freqs["name"] = 0.3

    for field in ("complexion", "clothing"):
        target = missing.get(field)
        if target:
            count = sum(1 for c in candidates
                        if str(c.get(field, "")).strip().lower() == str(target).strip().lower())
            freqs[field] = max(count / n, 0.02)
        else:
            freqs[field] = 0.3

    for field in ("age", "height_cm"):
        target = missing.get(field)
        tol = NUMERIC_TOLERANCE[field]
        if target is not None:
            count = 0
            for c in candidates:
                cand_val = c.get("age_range") if field == "age" else c.get(field)
                cand_val = c.get(field) if cand_val is None else cand_val
                if cand_val is None:
                    continue
                bounds = _numeric_bounds(cand_val)
                if bounds and degree_numeric(target, bounds, tol) >= 0.5:
                    count += 1
            freqs[field] = max(count / n, 0.02)
        else:
            freqs[field] = 0.3

    target_marks = missing.get("distinctive_marks")
    if target_marks:
        count = sum(1 for c in candidates
                     if (degree_text_overlap(target_marks, c.get("distinctive_marks")) or 0) > 0.15)
        freqs["distinctive_marks"] = max(count / n, 0.01)
    else:
        freqs["distinctive_marks"] = 0.05

    target_loc = missing.get("last_seen_location")
    if target_loc:
        count = sum(1 for c in candidates
                     if (degree_location(target_loc, c.get("location")) or 0) > 0.3)
        freqs["location"] = max(count / n, 0.05)
    else:
        freqs["location"] = 0.3

    freqs["time_gap"] = 0.3  

    return freqs







def log_odds_contribution(agreement_degree, m, u):
    if agreement_degree is None:
        return 0.0
    
    
    
    
    
    
    u = min(max(u, 0.05), 0.95)
    m = min(max(m, 0.05), 0.95)
    agree_weight = math.log2(m / u)
    disagree_weight = math.log2((1 - m) / (1 - u))
    return agreement_degree * agree_weight + (1 - agreement_degree) * disagree_weight


def to_similarity_score(total_log_odds, scale=8.0):






    return round(100 / (1 + math.exp(-total_log_odds / scale)), 1)






def degree_name(value_a, value_b):
    if not value_a or not value_b:
        return None
    a = _tokens(value_a)
    b = _tokens(value_b)
    if not a or not b:
        return None
    if a == b:
        return 1.0
    overlap = len(a & b) / max(len(a), len(b))
    
    return min(0.85, overlap) if overlap > 0 else 0.0


def score_candidate(missing: dict, found: dict, freqs: dict) -> dict:
    days_since_missing = None
    if missing.get("last_seen_date") and found.get("date_found"):
        try:
            d1 = datetime.fromisoformat(missing["last_seen_date"]).date()
            d2 = datetime.fromisoformat(found["date_found"]).date()
            days_since_missing = (d2 - d1).days
        except (ValueError, TypeError):
            pass

    breakdown = {}
    total = 0.0

    def add(field, degree, m_key=None):
        nonlocal total
        m = FIELD_M[m_key or field]
        u = freqs[m_key or field]
        contrib = log_odds_contribution(degree, m, u)
        total_local = contrib
        breakdown[field] = {"agreement": degree, "bits": round(total_local, 2)}
        return total_local

    total += add("name", degree_name(missing.get("name"), found.get("name")))
    total += add("age", degree_numeric(missing.get("age"),
                                        found.get("age_range") or found.get("age"),
                                        NUMERIC_TOLERANCE["age"]))
    total += add("height_cm", degree_numeric(missing.get("height_cm"), found.get("height_cm"),
                                              NUMERIC_TOLERANCE["height_cm"]))
    total += add("complexion", degree_categorical(missing.get("complexion"), found.get("complexion")))
    total += add("distinctive_marks", degree_text_overlap(missing.get("distinctive_marks"),
                                                           found.get("distinctive_marks")))
    total += add("location", degree_location(missing.get("last_seen_location"), found.get("location")))
    total += add("time_gap", degree_time_gap(missing.get("last_seen_date"), found.get("date_found")))

    
    clothing_degree = degree_text_overlap(missing.get("clothing"), found.get("clothing"))
    relevance = clothing_relevance(days_since_missing)
    raw = log_odds_contribution(clothing_degree, FIELD_M["clothing"], freqs["clothing"])
    scaled = raw * relevance
    breakdown["clothing"] = {"agreement": clothing_degree, "bits": round(scaled, 2),
                              "note": f"time-decayed x{relevance:.2f} (case age: {days_since_missing} days)"
                              if days_since_missing is not None else "time-decay unknown"}
    total += scaled

    return {"candidate": found, "total_log_odds": round(total, 2), "breakdown": breakdown}







def apply_face_similarity(scored_result, missing, compare_fn=None):
    if compare_fn is None or not missing.get("photo") or not scored_result["candidate"].get("photo"):
        return scored_result
    similarity = compare_fn(missing["photo"], scored_result["candidate"]["photo"])  
    contrib = log_odds_contribution(similarity, m=0.92, u=0.02)
    scored_result["total_log_odds"] = round(scored_result["total_log_odds"] + contrib, 2)
    scored_result["breakdown"]["face_similarity"] = {"agreement": similarity, "bits": round(contrib, 2)}
    return scored_result







def fuse_sources(results_for_same_candidate: list) -> dict:







    if not results_for_same_candidate:
        return {}
    ranked = sorted(results_for_same_candidate, key=lambda r: r["total_log_odds"], reverse=True)
    base = ranked[0]
    bonus = 0.0
    corroborating = 0
    for extra in ranked[1:]:
        if extra["total_log_odds"] > 0:
            bonus += 2.0 / (corroborating + 2)  
            corroborating += 1
    fused = dict(base)
    fused["total_log_odds"] = round(base["total_log_odds"] + bonus, 2)
    fused["fusion_bonus"] = round(bonus, 2)
    fused["corroborating_sources"] = corroborating + 1
    return fused






def rank_candidates(missing: dict, raw_candidates: list, top_n_expensive: int = 20, face_compare_fn=None) -> list:
    
    
    
    
    freqs = compute_population_frequencies(raw_candidates, missing)
    survivors = [c for c in raw_candidates if passes_hard_filters(missing, c)]

    scored = [score_candidate(missing, c, freqs) for c in survivors]
    scored.sort(key=lambda s: s["total_log_odds"], reverse=True)

    for s in scored[:top_n_expensive]:
        apply_face_similarity(s, missing, face_compare_fn)

    scored.sort(key=lambda s: s["total_log_odds"], reverse=True)
    for s in scored:
        s["similarity_score"] = to_similarity_score(s["total_log_odds"])

    return scored


def render_explanation(result: dict) -> str:
    cid = result["candidate"].get("found_id", "?")
    lines = [f"CANDIDATE {cid} — Similarity Score: {result['similarity_score']}/100"]
    for field, detail in result["breakdown"].items():
        deg = detail["agreement"]
        symbol = "\u00b7" if deg is None else ("\u2713" if deg >= 0.5 else "\u2717")
        note = f" ({detail['note']})" if "note" in detail else ""
        deg_txt = "no data" if deg is None else f"{deg:.2f} agreement"
        lines.append(f"{symbol} {field}: {deg_txt}{note} [{detail['bits']:+.2f} bits]")
    if "corroborating_sources" in result:
        lines.append(f"\u2713 corroborated by {result['corroborating_sources']} independent source(s) "
                      f"[+{result['fusion_bonus']:.2f} bits]")
    return "\n".join(lines)





if __name__ == "__main__":
    missing_case = {
        "name": "Rahul", "age": 17, "gender": "male", "complexion": "wheatish",
        "height_cm": 173, "last_seen_location": "Andheri station Mumbai",
        "last_seen_date": "2026-09-01", "clothing": "blue hoodie",
        "distinctive_marks": "small scar above left eyebrow", "photo": None,
    }

    candidates = [
        {"found_id": "A", "age_range": (16, 18), "gender": "male", "complexion": "wheatish",
         "height_cm": 170, "location": "Malad Mumbai", "date_found": "2026-09-10",
         "clothing": "grey t-shirt", "distinctive_marks": None},

        {"found_id": "B", "age_range": (17, 17), "gender": "male", "complexion": "wheatish",
         "height_cm": 174, "location": "Andheri East Mumbai", "date_found": "2026-09-02",
         "clothing": "blue hoodie", "distinctive_marks": "scar near left eyebrow, small"},

        {"found_id": "C", "age_range": (16, 19), "gender": "female", "complexion": "wheatish",
         "height_cm": 172, "location": "Andheri Mumbai", "date_found": "2026-09-02",
         "clothing": "blue hoodie", "distinctive_marks": None},

        {"found_id": "D", "age_range": (45, 50), "gender": "male", "complexion": "wheatish",
         "height_cm": 171, "location": "Andheri Mumbai", "date_found": "2026-09-02",
         "clothing": "blue hoodie", "distinctive_marks": None},

        {"found_id": "E (contradicts)", "age_range": (17, 18), "gender": "male", "complexion": "wheatish",
         "height_cm": 172, "location": "Andheri Mumbai", "date_found": "2026-09-02",
         "clothing": "blue hoodie", "distinctive_marks": "no marks or scars, clean face"},
    ]

    results = rank_candidates(missing_case, candidates)

    print(f"{len(candidates)} candidates in -> {len(results)} passed hard filters\n")
    for r in results:
        print(render_explanation(r))
        print()

    print("=" * 60)
    print("Evidence fusion demo: candidate B corroborated by a 2nd source")
    print("=" * 60)
    b_result = next(r for r in results if r["candidate"]["found_id"] == "B")
    
    
    b_from_news = dict(b_result)
    b_from_news["total_log_odds"] = b_result["total_log_odds"] * 0.7
    fused = fuse_sources([b_result, b_from_news])
    fused["similarity_score"] = to_similarity_score(fused["total_log_odds"])
    print(render_explanation(fused))

    
    
    
    
    
    
    
    
    import random
    random.seed(42)

    noise_locations = ["Malad Mumbai", "Bandra Mumbai", "Kurla Mumbai", "Thane", "Andheri Mumbai", "Dadar Mumbai"]
    noise_clothing = ["grey t-shirt", "white shirt", "black jacket", "blue hoodie", "green kurta"]
    noise_candidates = []
    for i in range(45):
        noise_candidates.append({
            "found_id": f"noise-{i}",
            "age_range": (random.randint(14, 20), random.randint(14, 20)),
            "gender": "male",
            "complexion": random.choice(["wheatish", "fair", "dark"]),
            "height_cm": random.randint(160, 185),
            "location": random.choice(noise_locations),
            "date_found": f"2026-09-{random.randint(1, 12):02d}",
            "clothing": random.choice(noise_clothing),
            "distinctive_marks": None,  
        })

    big_pool = candidates + noise_candidates
    big_results = rank_candidates(missing_case, big_pool)

    print(f"\n{'=' * 60}")
    print(f"Realistic-scale demo: {len(big_pool)} candidates in -> "
          f"{len(big_results)} passed hard filters")
    print("=" * 60)
    for r in big_results[:3]:
        print(render_explanation(r))
        print()
    print(f"... and {len(big_results) - 3} more candidates ranked below these.")
