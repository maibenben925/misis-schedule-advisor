import sqlite3
conn = sqlite3.connect("d:/misis/8-semester/diploma/schedule.db")
c = conn.cursor()
c.execute("SELECT count(*) FROM transfers")
print("transfers:", c.fetchone()[0])
c.execute("SELECT count(*) FROM event_bookings")
print("event_bookings:", c.fetchone()[0])
conn.close()
