from scoring import calculate_penalty

p1 = calculate_penalty('Л', 5, 'Л', 5, 35, 34,
    needs_projector=False, needs_computers=False,
    alt_has_projector=False, alt_has_computers=False)
print(f'Без доп. оборудования: penalty={p1}')

p2 = calculate_penalty('Л', 5, 'Л', 5, 35, 34,
    needs_projector=False, needs_computers=False,
    alt_has_projector=True, alt_has_computers=False)
print(f'С проектором (не нужен): penalty={p2}  (delta=+{p2-p1})')

p3 = calculate_penalty('Л', 5, 'Л', 5, 35, 34,
    needs_projector=False, needs_computers=False,
    alt_has_projector=True, alt_has_computers=True)
print(f'С ПК+проектор (не нужны): penalty={p3}  (delta=+{p3-p1})')

p4 = calculate_penalty('Г', 5, 'Г', 5, 35, 34,
    needs_projector=True, needs_computers=True,
    alt_has_projector=True, alt_has_computers=True)
print(f'Лабораторной нужны ПК → penalty={p4} (без штрафа за оборудование)')
