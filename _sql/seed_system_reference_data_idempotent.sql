-- Идемпотентные справочники: sandbox → прод (ON CONFLICT DO NOTHING).
-- Не трогает users / dreams / dreams_steps / roadmap.
-- Выполнять на целевой БД после того, как схема таблиц совпадает.

-- dreams_statuses (UNIQUE: code)
INSERT INTO dreams_statuses (code, label_ru, icon) VALUES
  ('planned', 'Запланировано', '💡'),
  ('in_progress', 'В работе', '☭'),
  ('done', 'Выполнено', '✅')
ON CONFLICT (code) DO NOTHING;

-- dreams_categories (UNIQUE: code)
INSERT INTO dreams_categories (code, label_ru, icon) VALUES
  ('health', 'Здоровье', '❤️'),
  ('finance', 'Финансы', '💰'),
  ('relations', 'Отношения', '💑'),
  ('charity', 'Благотворительность', '🤝'),
  ('projects', 'Проекты', '📋'),
  ('development', 'Развитие', '📚'),
  ('family', 'Семья', '🏠'),
  ('other', 'Прочее', '📦'),
  ('sport', 'Спорт', '⚽'),
  ('spirituality', 'Духовность', '🙏'),
  ('achievements', 'Достижения', '🏆')
ON CONFLICT (code) DO NOTHING;

-- steps_rules (UNIQUE: category_code, rule_code)
INSERT INTO steps_rules (category_code, rule_code, rules, comment) VALUES
  (
    'finance',
    'yearly_amount_by_month_equal',
    '{"unit": "RUB", "period": "year", "calendar": "year_2026", "plan_round": "thousands", "description": "Равномерное разбиение годовой суммы по месяцам календарного года", "distribution": "equal_by_month", "target_field": "target_amount", "period_months": 12}'::jsonb,
    'Финансовая цель на год: взять целевую сумму и разбить её на 12 равных ежемесячных шагов (январь–декабрь).'
  ),
  (
    'development',
    'books_reading',
    '{"minutes_per_day": 15, "schedule_label_read": "Читать", "schedule_label_listen": "Слушать"}'::jsonb,
    'Чтение книг: список книг, минуты в день, виртуальные строки расписания'
  )
ON CONFLICT (category_code, rule_code) DO NOTHING;
