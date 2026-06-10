# Тополь — Table Sync Engine
# Автоматизация цепочки движения между Google Sheets

SHEETS = {
    # Таблица 1: Номос Сценарии
    "nomos_scenarios": {
        "id": "1zVNwBX7e8FIZ-0bP7qU2UTbueXrukoev0NbSCS9EwHQ",
        "description": "Номос Сценарии — основной хаб",
        "tabs": {
            "main": "Номос",                    # Сценарии, столбцы A-AB
            "scenarios_collection": "СценарииСбор",
            "test": "тест3",                    # Конкуренты
            "archive": "Архив",
        }
    },
    # Таблица 2: Спр_Монтаж
    "montage_reference": {
        "id": "1paHyEIxdB2tojNPRfTF58DFirMOYROcwtJNQeM3J5y4",
        "description": "Спр_Монтаж — сценарии, монтажёры, клиенты",
        "tabs": {
            "scenarios": "СценарииСбор",        # Основная: сценарий → монтаж
            "clients": "СпрКлиент",             # Клиенты
            "client_scen": "СпрКлиентСцен",     # Клиентские сценарии
            "montagers": "МонтжерыV2М",         # База монтажёров
            "nomos": "Номос",                   # Проект Номос
            "scenarios_v2m": "СценарииV2М",     # Сценарии v2
        }
    },
    # Таблица 3: AI4 отчёт Номос
    "ai4_report": {
        "id": "1txbhJZiYuwVBtP7Cuo_tdoMDEL2dlib-gGCI2ltRFyI",
        "description": "AI4 отчет Номос — отчётность",
        "tabs": {
            "access": "Доступы",
            "scenarios": "Сценарии",
            "scenarios_v2": "СценарийV2",
            "stats": "Статистика",
            "reporting": "Отчетность",
            "export_v2": "ВыгрузкаV2",
            "export_montage_v2": "ВыгрузМонтажV2",
        }
    },
    # Таблица 4: Монтажёр Михаил
    "montager_mikhail": {
        "id": "1qn3iBKsfZnEW7MYRK7gxcU4kq44rrbN9CaV5w_Em-CQ",
        "description": "Монтажер_МихаилШашков — задания монтажёру",
        "tabs": {
            "tasks": "Задания",
            "tasks_v2": "ЗаданияV2",
            "payment": "Оплата",
            "export_v2": "ВыгрузкаV2",
        }
    },
}

# Цепочка движения (из инструкции)
WORKFLOW = {
    "steps": [
        {
            "id": 1,
            "name": "Одобрение → клиентская таблица",
            "trigger": {"source_tab": "nomos_scenarios/main", "status_col": "Одобрение клиента", "value": "Одобрено"},
            "action": "copy_to_client",
            "target": "montage_reference/clients",
        },
        {
            "id": 2,
            "name": "Пинг-понг сценарист ↔ клиент",
            "trigger": {"source_tab": "nomos_scenarios/main", "fields": ["Статус Сценариста", "Комментарий Сценариста"]},
            "action": "sync_bidirectional",
            "target": "montage_reference/client_scen",
        },
        {
            "id": 3,
            "name": "Дедлайн + исходник + готово → менеджер монтажа",
            "trigger": {
                "source_tab": "montage_reference/scenarios",
                "conditions": "ALL",
                "fields": {"Дата дедлайна": "filled", "Ссылка с исходником": "filled", "Статус Сценариста": "Готово"}
            },
            "action": "notify_manager",
            "target": "montage_reference/scenarios",
        },
        {
            "id": 4,
            "name": "Пинг-понг менеджер ↔ сценарист",
            "trigger": {"source_tab": "montage_reference/scenarios", "fields": ["Одобрение исходника", "Комментарий"]},
            "action": "sync_bidirectional",
            "target": "nomos_scenarios/main",
        },
        {
            "id": 5,
            "name": "Выбор монтажёра → табличка монтажёра",
            "trigger": {"source_tab": "montage_reference/scenarios", "status_col": "Выбор монтажера", "value": "filled"},
            "action": "assign_to_montager",
            "target": "montager_mikhail/tasks_v2",
        },
        {
            "id": 6,
            "name": "Пинг-понг монтажёр ↔ менеджер",
            "trigger": {"source_tab": "montager_mikhail/tasks_v2", "fields": ["Статус монтажера", "Комментарий"]},
            "action": "sync_bidirectional",
            "target": "montage_reference/scenarios",
        },
        {
            "id": 7,
            "name": "Одобрение монтажа → клиенту",
            "trigger": {"source_tab": "montage_reference/scenarios", "status_col": "Одобрение", "value": "Одобрено"},
            "action": "send_to_client",
            "target": "nomos_scenarios/main",
        },
        {
            "id": 8,
            "name": "Клиент одобрил монтаж → ссылка сценаристу",
            "trigger": {"source_tab": "nomos_scenarios/main", "status_col": "Одобрение клиента", "value": "Одобрено"},
            "action": "send_to_scenarist",
            "target": "montage_reference/scenarios",
        },
        {
            "id": 9,
            "name": "Сценарист: описание + дата → клиентская таблица",
            "trigger": {"source_tab": "montage_reference/scenarios", "fields": ["Дата Готового монтажа", "Описание"]},
            "action": "update_client_table",
            "target": "nomos_scenarios/main",
        },
    ]
}
