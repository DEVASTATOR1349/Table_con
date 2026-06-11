# Тополь — Table Sync Engine
# Автоматизация цепочки движения между Google Sheets
# Колонки нормализованы под реальные заголовки (без trailing numbers, collapsed whitespace)

SHEETS = {
    "nomos_scenarios": {
        "id": "1zVNwBX7e8FIZ-0bP7qU2UTbueXrukoev0NbSCS9EwHQ",
        "description": "Номос Сценарии — основной хаб",
        "tabs": {
            "main": "Номос",
            "scenarios_collection": "СценарииСбор",
            "test": "тест3",
            "archive": "Архив",
        }
    },
    "montage_reference": {
        "id": "1paHyEIxdB2tojNPRfTF58DFirMOYROcwtJNQeM3J5y4",
        "description": "Спр_Монтаж — сценарии, монтажёры, клиенты",
        "tabs": {
            "scenarios": "СценарииСбор",
            "clients": "СпрКлиент",
            "client_scen": "СпрКлиентСцен",
            "montagers": "МонтжерыV2М",
            "nomos": "Номос",
            "scenarios_v2m": "СценарииV2М",
            "montager_collector": "МонтажерыРаспределение",
            "montager_db": "БазаДанных",
        }
    },
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
    "montager_mikhail": {
        "id": "1qn3iBKsfZnEW7MYRK7gxcU4kq44rrbN9CaV5w_Em-CQ",
        "description": "Монтажер_МихаилШашков — задания монтажёру",
        "tabs": {
            "tasks_v2": "ЗаданияV2",
            "tasks": "Задания",
            "payment": "Оплата",
            "export_v2": "ВыгрузкаV2",
        }
    },
}

MONTAGER_SHEETS = {
    "АлександраДоронина": {"access": True, "id": "1qijk5q_JehY5WvFnrJPlU-dpjTXMRV1vBy4Dt6F6an8"},
    "АлексейПьянников": {"access": True, "id": "1iPeSA72WOSJ8BXwRODsMbdFEs8BQ5HLaT58maFgpDXI"},
    "АллаГорбань": {"access": True, "id": "1-NOixuy4uFJQCEXdFDaKP0BiE45XXmiOTZMKR3Zd0nU"},
    "АлисаБолдырева": {"access": True, "id": "11zMcjX6Ae68B2J6aJJwEAJIKBTq1eH-mkytLEl6p2sc"},
    "АмираАбдукадырова": {"access": True, "id": "1jnQSR4cqC-JEEV_k_58x6uK5yJRvOLgm1AsuZ2aTpRY"},
    "АннаЛесько": {"access": True, "id": "1CyB5Vuz80UFyG9QPu0bN8jHYClesVZW2I-nRylbOzR8"},
    "АртемЗдорик": {"access": True, "id": "1as6phB-5P5y6mMemhZvk02Q19nLnPm_Ziv8F1rJIzYg"},
    "АтлуханАсадов": {"access": True, "id": "1l5u7uD8UrhVEsBGWzOMQFx59htln5ftZUjh0fQ2s-YE"},
    "ВикторияМуравьева": {"access": True, "id": "1J5nci2Oq-De23bvYTWtUWzUjvupRMhXBf5nDgCkkmQA"},
    "ДариюшГайдуцкий": {"access": True, "id": "1qbN1Ll8bnFO97RN0ZQojHYbGS0w_0dKh9OB5G3mp51o"},
    "ДарьяЗаболотная": {"access": True, "id": "1f1nTbyQwRmebGWkl8Y4eRJIPxvXj-CKqIpwIxvWz3oo"},
    "ЕкатеринаСивухина": {"access": True, "id": "1kVIt2qk6BEowp_OYzQ5ETdDVkSRcveFMRI48x-nPtcY"},
    "ЕленаИстомина": {"access": True, "id": "1uCZvmPt4A0WU5rLMTvAoaYL9d6bqAr5jUcLxLv6mYLw"},
    "ЕлизаветаЛукьяненко": {"access": True, "id": "1jUL1IVsHLOskkDB68DGYE4YZPzKGNZe3qHJ0RsK0Zno"},
    "КристинаГорелова": {"access": True, "id": "1nRPmNLff2EJK83h0ljOvm6jghPkYDwP05_IFyRL4JiU"},
    "МихаилШашков": {"access": True, "id": "1qn3iBKsfZnEW7MYRK7gxcU4kq44rrbN9CaV5w_Em-CQ"},
    "НадеждаГордеева": {"access": True, "id": "1Xrf3GpvMH_1es8nYhc3g3gk8yJh8ShHq0nsR2Y9Bpdo"},
    "НикитаДенисов": {"access": True, "id": "1haEu5UqA_L4w41uFPC5A0G4NWctLoG6bq90YSUFb4rQ"},
    "НикитаКозлов": {"access": True, "id": "1V-4QAfBddu98d8zh4v315ThOp9yN723wZbX145nPf-o"},
    "НикитаЛевченко": {"access": True, "id": "1W6GCIDBBflAxWeZQP4tXAHFUNf3BDNGcH-y7ttMbnaM"},
    "НикитаУльянов": {"access": True, "id": "1W2jKnUGtMqJBGW1Sl5gzm38mHtFmi9u_TcQ3S6tSruU"},
    "ПавелКоваленко": {"access": True, "id": "1ehjP_D_Fn6v9sTwkbnKW6dX4oWpGL9pRlyLYQ0FT2OQ"},
    "СофьяМагурина": {"access": True, "id": "12WCrQG38xgo9gaqFBexqZS4nOTYgud4HfUYjKTXZESE"},
    "ТемирханКонурбаев": {"access": True, "id": "1YDi5jaIPcM9WBGKSEABks1bq5VJxNy96HRZCuMqbByQ"},
    "УльянаГрехова": {"access": True, "id": "1-udQBdpJAWbw5HKRovXEUx4T_Br0a7xnv4D3sMHtDXk"},
    "ЭдуардХаматгалимов": {"access": True, "id": "1T8v-agmqQ6b_hxWdldlCsILpBC9n-GMuiNbsMwi0VXU"},
}

MONTAGER_ALIASES = {
    "АллаГорбань": "АллаГорбань",
}

ACTIVE_MONTAGER_SHEETS = {k: v for k, v in MONTAGER_SHEETS.items() if v.get('access', False)}

WORKFLOW = {
  "steps": [
    {
      "id": 1,
      "name": "Одобрение → клиентская таблица",
      "trigger": {
        "source_tab": "nomos_scenarios/main",
        "status_col": "Монтаж",
        "value": "Одобрено"
      },
      "action": "copy_to_client",
      "target": "montage_reference/clients"
    },
    {
      "id": 2,
      "name": "Пинг-понг сценарист ↔ клиент",
      "trigger": {
        "source_tab": "nomos_scenarios/main",
        "fields": [
          "Анализ материала",
          "Аудит Сценария"
        ]
      },
      "action": "sync_bidirectional",
      "target": "montage_reference/client_scen"
    },
    {
      "id": 3,
      "name": "Дедлайн + исходник + готово → менеджер монтажа",
      "trigger": {
        "source_tab": "montage_reference/scenarios",
        "conditions": "ALL",
        "fields": {
          "Дата дедлайна": "filled",
          "Ссылка с исходником и обложкой": "filled",
          "Статус Сценариста": "Готово"
        }
      },
      "action": "notify_manager",
      "target": "montage_reference/scenarios"
    },
    {
      "id": 4,
      "name": "Пинг-понг менеджер ↔ сценарист",
      "trigger": {
        "source_tab": "montage_reference/scenarios",
        "fields": [
          "Одобрение исходника",
          "Комментарий"
        ]
      },
      "action": "sync_bidirectional",
      "target": "nomos_scenarios/main"
    },
    {
      "id": 5,
      "name": "Выбор монтажёра → табличка монтажёра",
      "trigger": {
        "source_tab": "montage_reference/scenarios",
        "status_col": "Выбор монтажера",
        "value": "filled"
      },
      "action": "assign_to_montager",
      "target": "montage_reference/scenarios"
    },
    {
      "id": 6,
      "name": "Пинг-понг монтажёр ↔ менеджер (все таблицы)",
      "trigger": {
        "source_tab": "montage_reference/scenarios",
        "fields": [
          "Статус Монтажа",
          "Комментарий Монтажёра"
        ]
      },
      "action": "sync_montager_bidirectional",
      "target": "montage_reference/scenarios"
    },
    {
      "id": 7,
      "name": "Одобрение монтажа → клиенту",
      "trigger": {
        "source_tab": "montage_reference/scenarios",
        "status_col": "Одобрение",
        "value": "Одобрено"
      },
      "action": "send_to_client",
      "target": "nomos_scenarios/main"
    },
    {
      "id": 8,
      "name": "Клиент одобрил монтаж → ссылка сценаристу",
      "trigger": {
        "source_tab": "nomos_scenarios/main",
        "status_col": "Публикация",
        "value": "Одобрено"
      },
      "action": "send_to_scenarist",
      "target": "montage_reference/scenarios"
    },
    {
      "id": 9,
      "name": "Сценарист: описание + дата → клиентская таблица",
      "trigger": {
        "source_tab": "montage_reference/scenarios",
        "fields": [
          "Дата Готового монтажа",
          "Описание"
        ]
      },
      "action": "update_client_table",
      "target": "nomos_scenarios/main"
    }
  ]
}
