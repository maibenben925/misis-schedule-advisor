import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from search_engine import get_lesson_info, get_valid_alternatives, find_room_for_event
    print("search_engine OK")
except Exception as e:
    print(f"search_engine FAIL: {e}")

try:
    from scoring import score_alternatives
    print("scoring OK")
except Exception as e:
    print(f"scoring FAIL: {e}")

try:
    from optimization import mass_reallocate
    print("optimization OK")
except Exception as e:
    print(f"optimization FAIL: {e}")

try:
    info = get_lesson_info(2)
    print(f"get_lesson_info: {info['lesson_title']}")
except Exception as e:
    print(f"get_lesson_info FAIL: {e}")

try:
    alts = get_valid_alternatives(2)
    print(f"get_valid_alternatives: {len(alts)}")
except Exception as e:
    print(f"get_valid_alternatives FAIL: {e}")

try:
    scored = score_alternatives(2)
    print(f"score_alternatives: {len(scored)}")
except Exception as e:
    print(f"score_alternatives FAIL: {e}")

try:
    result = mass_reallocate([2, 3])
    print(f"mass_reallocate: {len(result.assignments)} assigned, {len(result.unassigned)} unassigned")
except Exception as e:
    print(f"mass_reallocate FAIL: {e}")

try:
    results = find_room_for_event(30, True, False, 'Понедельник', '2026-01-12T10:50:00+03:00', '2026-01-12T12:25:00+03:00', 'upper')
    print(f"find_room_for_event: {len(results)}")
except Exception as e:
    print(f"find_room_for_event FAIL: {e}")

print("DONE")
