import os
from datetime import date

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "schedule.db")

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

WD_R = {0: "Понедельник", 1: "Вторник", 2: "Среда", 3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"}

SLOTS = [
    {"name": "1-я пара", "start": "09:00", "end": "10:35"},
    {"name": "2-я пара", "start": "10:50", "end": "12:25"},
    {"name": "3-я пара", "start": "12:40", "end": "14:15"},
    {"name": "4-я пара", "start": "14:30", "end": "16:05"},
    {"name": "5-я пара", "start": "16:20", "end": "17:55"},
    {"name": "6-я пара", "start": "18:00", "end": "19:25"},
    {"name": "7-я пара", "start": "19:35", "end": "21:00"},
]

BASE_MONDAY = date(2026, 1, 12)

EXCLUDED_BUILDINGS = ("Онлайн", "Каф. ИЯКТ", "Спортивный комплекс Беляево")
