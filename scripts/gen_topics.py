# scripts/gen_topics.py
from __future__ import annotations
from pathlib import Path
import csv

ROOT = "/Теплица/Досветка"

# ФИЗИЧЕСКИЕ линии по щитам (итого 286)
CABINET_COUNTS = {
    1: 6,
    **{i: 8 for i in range(2, 28)},   # 2..27 (26 щитов)
    **{i: 12 for i in range(28, 34)}, # 28..33 (6 щитов)
}

CABINET_COMMON_PARAMS = [
    "Авто_режим",
    "Напряжение_L1",
    "Напряжение_L2",
    "Напряжение_L3",
    "Частота",
    "Освещённость",
    "Температура",
    "Влажность",
    "ИБП_Состояние_батареи",
    "ИБП_Заряд_проц",
]

# Параметры на контур (и для LED, и для HPS)
CONTOUR_CONTROL = {
    "LED": ["Включено", "ШИМ_A", "ШИМ_B"],
    "HPS": ["Включено", "ШИМ"],
}

CONTOUR_POWER = ["Вт"]

CONTOUR_ELECTRICS = [
    ("Электрика", "Ток_L1"),
    ("Электрика", "Ток_L2"),
    ("Электрика", "Ток_L3"),
    ("Электрика", "Коэффициент_мощности"),
    ("Энергия", "Прямая_активная_кВтч"),
]

def z2(n: int) -> str:
    return f"{n:02d}"

def z3(n: int) -> str:
    return f"{n:03d}"

def build_topics() -> tuple[list[dict], int, int]:
    rows: list[dict] = []
    total_physical_lines = 0
    card_id = 0

    for cab in range(1, 34):
        cab_id = z2(cab)

        # общие по щиту
        for p in CABINET_COMMON_PARAMS:
            topic = f"{ROOT}/ЩД/{cab_id}/Общее/{p}"
            rows.append({
                "scope": "cabinet",
                "cabinet": cab_id,
                "card": "",
                "contour": "",
                "group": "Общее",
                "param": p,
                "topic": topic,
            })

        # линии в щите: каждые 2 физлинии = 1 карточка (LED+HPS)
        lines = CABINET_COUNTS.get(cab, 0)
        if lines % 2 != 0:
            raise SystemExit(f"ЩД {cab_id}: число линий должно быть чётным (LED+HPS), а сейчас {lines}")

        total_physical_lines += lines
        cards_in_cabinet = lines // 2

        for _ in range(cards_in_cabinet):
            card_id += 1
            card = z3(card_id)

            # LED/HPS контуры
            for contour in ("LED", "HPS"):
                # управление
                for p in CONTOUR_CONTROL[contour]:
                    topic = f"{ROOT}/Карта/{card}/Контур/{contour}/Управление/{p}"
                    rows.append({
                        "scope": "card",
                        "cabinet": cab_id,
                        "card": card,
                        "contour": contour,
                        "group": "Управление",
                        "param": p,
                        "topic": topic,
                    })

                # мощность
                for p in CONTOUR_POWER:
                    topic = f"{ROOT}/Карта/{card}/Контур/{contour}/Мощность/{p}"
                    rows.append({
                        "scope": "card",
                        "cabinet": cab_id,
                        "card": card,
                        "contour": contour,
                        "group": "Мощность",
                        "param": p,
                        "topic": topic,
                    })

                # электрика/энергия
                for grp, p in CONTOUR_ELECTRICS:
                    topic = f"{ROOT}/Карта/{card}/Контур/{contour}/{grp}/{p}"
                    rows.append({
                        "scope": "card",
                        "cabinet": cab_id,
                        "card": card,
                        "contour": contour,
                        "group": grp,
                        "param": p,
                        "topic": topic,
                    })

    return rows, card_id, total_physical_lines

def main():
    rows, cards, phys = build_topics()

    Path("topics.txt").write_text("\n".join(r["topic"] for r in rows), encoding="utf-8")

    with open("topics.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["scope", "cabinet", "card", "contour", "group", "param", "topic"]
        )
        w.writeheader()
        w.writerows(rows)

    cabinet_topics = sum(1 for r in rows if r["scope"] == "cabinet")
    card_topics = sum(1 for r in rows if r["scope"] == "card")

    print(f"OK: записано {len(rows)} топиков -> topics.txt, topics.csv")
    print(f"Щитов: 33")
    print(f"Физических линий: {phys} (должно быть 286)")
    print(f"Карточек: {cards} (должно быть 143)")
    print(f"Топиков общих по щиту: {cabinet_topics}")
    print(f"Топиков по карточкам (LED+HPS): {card_topics}")

    if phys != 286:
        print("⚠️ ВНИМАНИЕ: физические линии != 286, проверь CABINET_COUNTS")
    if cards != 143:
        print("⚠️ ВНИМАНИЕ: карточки != 143, проверь CABINET_COUNTS")

if __name__ == "__main__":
    main()
