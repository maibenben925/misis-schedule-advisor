import sqlite3
from datetime import date, timedelta, datetime as dt

from src.config import DB_PATH, WEEKDAYS, WD_R, SLOTS, BASE_MONDAY, EXCLUDED_BUILDINGS
from src.search_engine import get_lesson_info


def t2m(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m


def d2wt(d):
    if isinstance(d, dt):
        d = d.date()
    elif not isinstance(d, date):
        d = date(int(str(d)[:4]), int(str(d)[5:7]), int(str(d)[8:10]))
    diff = (d - BASE_MONDAY).days
    return "upper" if (diff // 7) % 2 == 0 else "lower"


def d2wd(d):
    if isinstance(d, dt):
        d = d.date()
    elif not isinstance(d, date):
        d = date(int(str(d)[:4]), int(str(d)[5:7]), int(str(d)[8:10]))
    return WD_R.get(d.weekday(), "")


def wd_to_date(wd_name):
    idx = WEEKDAYS.index(wd_name)
    return str(BASE_MONDAY + timedelta(days=idx))


def to_iso(t, d=None, weekday=None):
    if d:
        dt_str = str(d)
    elif weekday:
        dt_str = wd_to_date(weekday)
    else:
        dt_str = str(BASE_MONDAY)
    return f"{dt_str}T{t}:00+03:00"


def t_from_iso(s):
    return s[11:16] if s else ""


def slot_label(start_str, end_str):
    for sl in SLOTS:
        if sl["start"] == start_str and sl["end"] == end_str:
            return f"{sl['start']}–{sl['end']} ({sl['name']})"
    return f"{start_str}–{end_str}"


def gc():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables():
    c = gc()
    cur = c.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        schedule_id INT, old_room_id INT, new_room_id INT,
        weekday TEXT, start TEXT, end TEXT, week_type TEXT,
        lesson_id INT, group_id INT, reason TEXT,
        booking_date TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS event_bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        room_id INT, weekday TEXT, start TEXT, end TEXT, week_type TEXT,
        event_name TEXT, organizer TEXT, attendees_count INT,
        needs_projector BOOLEAN, needs_computers BOOLEAN,
        booking_date TEXT)""")
    c.commit()
    c.close()


def init_incidents_table():
    c = gc()
    c.execute("""CREATE TABLE IF NOT EXISTS incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        reason TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS incident_rooms (
        incident_id INTEGER NOT NULL,
        room_id INTEGER NOT NULL,
        FOREIGN KEY (incident_id) REFERENCES incidents(id),
        PRIMARY KEY (incident_id, room_id)
    )""")
    c.commit()
    c.close()


def get_rooms():
    c = gc()
    r = c.execute(
        "SELECT id,name,building,floor,capacity,has_projector,has_computers FROM rooms WHERE building NOT IN (?,?,?) ORDER BY building,name",
        list(EXCLUDED_BUILDINGS),
    ).fetchall()
    c.close()
    return r


def get_buildings():
    c = gc()
    r = c.execute(
        "SELECT DISTINCT building FROM rooms WHERE building NOT IN (?,?,?) ORDER BY building",
        list(EXCLUDED_BUILDINGS),
    ).fetchall()
    c.close()
    return [x[0] for x in r]


def _get_transferred_schedule_ids():
    c = gc()
    rows = c.execute("SELECT DISTINCT schedule_id FROM transfers").fetchall()
    c.close()
    return {r["schedule_id"] for r in rows}


def get_affected(room_ids, sd, ed):
    if not room_ids or not sd or not ed:
        return [], {}
    transferred_sids = _get_transferred_schedule_ids()
    c = gc()
    ph = ",".join("?" for _ in room_ids)
    dates = []
    d = sd
    while d <= ed:
        dates.append((d2wd(d), d2wt(d), d))
        d += timedelta(days=1)
    cond = " OR ".join("(s.weekday=? AND s.week_type=?)" for _ in dates)
    q = f"""SELECT s.id,r.name as room_name,r.id as room_id,r.building as room_building,r.floor as room_floor,
            s.weekday,s.start,s.end,s.week_type,
            l.id as lesson_id,l.title as lesson_title,l.lesson_type,
            l.needs_projector,l.needs_computers,
            g.id as group_id,g.name as group_name,g.students_count
        FROM schedule s JOIN rooms r ON s.room_id=r.id
        JOIN lessons l ON s.lesson_id=l.id JOIN groups g ON s.group_id=g.id
        WHERE r.id IN ({ph}) AND ({cond}) ORDER BY s.start,r.name"""
    params = list(room_ids)
    for wd, wt, _ in dates:
        params.extend([wd, wt])
    rows = c.execute(q, params).fetchall()

    date_strs = [str(d) for _, _, d in dates]
    tph = ",".join("?" for _ in room_ids)
    dph = ",".join("?" for _ in date_strs)
    transferred_in = c.execute(f"""
        SELECT t.schedule_id, t.new_room_id as room_id,
               nr.name as room_name, nr.building as room_building, nr.floor as room_floor,
               s.weekday, s.start, s.end, s.week_type,
               l.id as lesson_id, l.title as lesson_title, l.lesson_type,
               l.needs_projector, l.needs_computers,
               g.id as group_id, g.name as group_name, g.students_count
        FROM transfers t
        JOIN schedule s ON t.schedule_id = s.id
        JOIN rooms nr ON t.new_room_id = nr.id
        JOIN lessons l ON s.lesson_id = l.id
        JOIN groups g ON s.group_id = g.id
        WHERE t.new_room_id IN ({tph}) AND t.booking_date IN ({dph})
    """, list(room_ids) + date_strs).fetchall()

    c.close()
    result = []
    current_room_overrides = {}
    for r in rows:
        if r["id"] in transferred_sids:
            continue
        for wd, wt, d in dates:
            if r["weekday"] == wd and r["week_type"] == wt:
                result.append({**dict(r), "booking_date": str(d)})
                break
    for r in transferred_in:
        sid = r["schedule_id"]
        if sid not in {x["id"] for x in result}:
            for wd, wt, d in dates:
                if r["weekday"] == wd and r["week_type"] == wt:
                    result.append({**dict(r), "id": sid, "booking_date": str(d)})
                    current_room_overrides[sid] = {
                        "room_id": r["room_id"],
                        "room_building": r["room_building"],
                        "room_floor": r["room_floor"],
                    }
                    break
    return result, current_room_overrides


def get_sched_for_date(sel_date):
    wd = d2wd(sel_date)
    wt = d2wt(sel_date)
    c = gc()
    rows = c.execute("""
        SELECT s.id,s.room_id,r.name as room_name,r.building,r.floor,
               l.title as lesson_title,l.lesson_type,g.name as group_name,
               substr(s.start,12,5) as st,substr(s.end,12,5) as et
        FROM schedule s JOIN rooms r ON s.room_id=r.id
        JOIN lessons l ON s.lesson_id=l.id JOIN groups g ON s.group_id=g.id
        WHERE s.weekday=? AND s.week_type=? ORDER BY r.name,s.start
    """, (wd, wt)).fetchall()
    c.close()
    g = {}
    for r in rows:
        k = (r["room_id"], r["st"], r["et"])
        if k not in g:
            g[k] = {
                "room_id": r["room_id"], "room_name": r["room_name"],
                "building": r["building"], "floor": r["floor"],
                "lesson_title": r["lesson_title"], "lesson_type": r["lesson_type"],
                "sids": [], "groups": [], "start": r["st"], "end": r["et"],
            }
        g[k]["sids"].append(r["id"])
        g[k]["groups"].append(r["group_name"])
    out = []
    for v in g.values():
        v["gd"] = ", ".join(sorted(set(v["groups"]))) if len(v["groups"]) > 1 else v["groups"][0]
        out.append(v)
    return out, wd, wt


def get_transfers_for_date(sel_date):
    c = gc()
    r = c.execute("""
        SELECT t.id as tid,t.schedule_id,t.booking_date,r1.name as old_room,r2.name as new_room,
               r2.id as new_room_id,l.title as lesson_title,l.lesson_type,g.name as group_name,
               substr(t.start,12,5) as st,substr(t.end,12,5) as et
        FROM transfers t JOIN rooms r1 ON t.old_room_id=r1.id
        JOIN rooms r2 ON t.new_room_id=r2.id
        JOIN lessons l ON t.lesson_id=l.id JOIN groups g ON t.group_id=g.id
        WHERE t.booking_date=?
    """, (str(sel_date),)).fetchall()
    c.close()
    return r


def check_booking_conflict(room_id, sel_date, s, e, exclude_bid=None):
    c = gc()
    q = """SELECT COUNT(*) as cnt FROM event_bookings
           WHERE room_id=? AND booking_date=?
           AND substr(start,12,5) < ? AND substr(end,12,5) > ?"""
    params = [room_id, str(sel_date), e, s]
    if exclude_bid:
        q += " AND id != ?"
        params.append(exclude_bid)
    r = c.execute(q, params).fetchone()
    if r["cnt"] > 0:
        c.close()
        return True
    wd = d2wd(sel_date)
    wt = d2wt(sel_date)
    r2 = c.execute("""
        SELECT COUNT(*) as cnt FROM schedule
        WHERE room_id=? AND weekday=? AND week_type=?
        AND substr(start,12,5) < ? AND substr(end,12,5) > ?
        AND id NOT IN (
            SELECT t.schedule_id FROM transfers t
            WHERE t.booking_date=? AND t.old_room_id=?
        )
    """, (room_id, wd, wt, e, s, str(sel_date), room_id)).fetchone()
    if r2["cnt"] > 0:
        c.close()
        return True
    r3 = c.execute("""
        SELECT COUNT(*) as cnt FROM transfers
        WHERE new_room_id=? AND booking_date=?
        AND substr(start,12,5) < ? AND substr(end,12,5) > ?
    """, (room_id, str(sel_date), e, s)).fetchone()
    c.close()
    return r3["cnt"] > 0


def save_transfers(assignments, date_map, sd, ed, excluded_room_ids=None, current_room_overrides=None):
    _room_overrides = current_room_overrides or {}
    date_groups = {}
    d = sd
    while d <= ed:
        key = (d2wd(d), d2wt(d))
        date_groups.setdefault(key, []).append(d)
        d += timedelta(days=1)

    c = gc()
    saved_count = 0
    for sid, sr in assignments.items():
        info = get_lesson_info(sid)
        key = (info["weekday"], info["week_type"])
        dates_for_this = date_groups.get(key, [])
        override = _room_overrides.get(sid)
        old_room_id = override["room_id"] if override else info["room_id"]
        for bdate in dates_for_this:
            if override:
                c.execute(
                    "DELETE FROM transfers WHERE schedule_id=? AND booking_date=? AND weekday=? AND start=?",
                    (sid, str(bdate), info["weekday"], info["start"]),
                )
            c.execute(
                "INSERT INTO transfers(schedule_id,old_room_id,new_room_id,weekday,start,end,week_type,lesson_id,group_id,reason,booking_date) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (sid, old_room_id, sr.room_id, info["weekday"], info["start"], info["end"],
                 info["week_type"], info["lesson_id"], info["group_id"], "Инцидент", str(bdate)),
            )
            saved_count += 1

    if excluded_room_ids:
        c.execute("INSERT INTO incidents(start_date, end_date) VALUES(?, ?)", (str(sd), str(ed)))
        incident_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        for rid in excluded_room_ids:
            c.execute("INSERT INTO incident_rooms(incident_id, room_id) VALUES(?, ?)", (incident_id, rid))

    c.commit()
    c.close()
    return saved_count


def save_booking(room, name, org, att, sel_date, s, e, p, co):
    wd = d2wd(sel_date)
    wt = d2wt(sel_date)
    c = gc()
    c.execute(
        "INSERT INTO event_bookings(room_id,weekday,start,end,week_type,event_name,organizer,attendees_count,needs_projector,needs_computers,booking_date) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (room["id"], wd, to_iso(s, sel_date), to_iso(e, sel_date), wt, name, org, att, p, co, str(sel_date)),
    )
    c.commit()
    c.close()


def del_transfer(tid):
    c = gc()
    c.execute("DELETE FROM transfers WHERE id=?", (tid,))
    c.commit()
    c.close()


def del_booking(bid):
    c = gc()
    c.execute("DELETE FROM event_bookings WHERE id=?", (bid,))
    c.commit()
    c.close()
