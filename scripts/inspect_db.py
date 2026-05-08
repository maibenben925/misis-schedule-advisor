import sqlite3

conn = sqlite3.connect(r'D:\misis\8-semester\diploma-transfer\schedule.db')
cursor = conn.cursor()

print('=== Unique lesson types ===')
cursor.execute('SELECT DISTINCT lesson_type FROM lessons')
for r in cursor.fetchall():
    print(repr(r[0]))

print('\n=== Unique buildings ===')
cursor.execute('SELECT DISTINCT building FROM rooms')
for r in cursor.fetchall():
    print(repr(r[0]))

print('\n=== Rooms per building ===')
cursor.execute('SELECT building, COUNT(*) FROM rooms GROUP BY building')
for r in cursor.fetchall():
    print(f'{r[0]}: {r[1]} rooms')

print('\n=== Rooms per building/floor ===')
cursor.execute('SELECT building, floor, COUNT(*) FROM rooms GROUP BY building, floor ORDER BY building, floor')
for r in cursor.fetchall():
    print(f'{r[0]} floor {r[1]}: {r[2]} rooms')

print('\n=== Sample lesson titles with types ===')
cursor.execute('SELECT title, lesson_type FROM lessons LIMIT 20')
for r in cursor.fetchall():
    print(f'{r[1]:20s} | {r[0]}')

print('\n=== Groups sample ===')
cursor.execute('SELECT name FROM groups LIMIT 30')
for r in cursor.fetchall():
    print(r[0])

print('\n=== Schedule: lessons per weekday ===')
cursor.execute('SELECT weekday, COUNT(*) FROM schedule GROUP BY weekday')
for r in cursor.fetchall():
    print(f'{r[0]}: {r[1]}')

print('\n=== Unique week_types ===')
cursor.execute('SELECT DISTINCT week_type FROM schedule')
for r in cursor.fetchall():
    print(repr(r[0]))

conn.close()
