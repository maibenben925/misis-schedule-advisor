import sqlite3
conn = sqlite3.connect(r'd:\misis\8-semester\diploma\schedule.db')
c = conn.cursor()

print('=== Schedule samples ===')
for r in c.execute('SELECT * FROM schedule LIMIT 5'):
    print(r)

print('\n=== Unique weekdays ===')
for r in c.execute('SELECT DISTINCT weekday FROM schedule'):
    print(repr(r[0]))

print('\n=== Unique week_types ===')
for r in c.execute('SELECT DISTINCT week_type FROM schedule'):
    print(repr(r[0]))

print('\n=== Time slots (start->end) ===')
for r in c.execute('SELECT DISTINCT substr(start,12,5), substr(end,12,5) FROM schedule ORDER BY start LIMIT 10'):
    print(f'{r[0]} -> {r[1]}')

conn.close()
