# Применённые миграции (справочник)

Миграции выполняются через `run_migrate.py`; после успешного выполнения файл из `_sql/` удаляется.  
Для новых инсталляций или восстановления БД — SQL ниже можно выполнить вручную.

---

## mig_showcase_tables (витрина: просмотры, избранное, контакты)

```sql
-- Контакты автора для модалки «Хочу помочь»
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS vk VARCHAR(255);

-- Просмотры мечт
CREATE TABLE IF NOT EXISTS user_dream_views (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    viewed_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, dream_id)
);
CREATE INDEX IF NOT EXISTS idx_user_dream_views_user ON user_dream_views(user_id);
CREATE INDEX IF NOT EXISTS idx_user_dream_views_dream ON user_dream_views(dream_id);

-- Избранные мечты
CREATE TABLE IF NOT EXISTS user_dream_favorites (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, dream_id)
);
CREATE INDEX IF NOT EXISTS idx_user_dream_favorites_user ON user_dream_favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_user_dream_favorites_dream ON user_dream_favorites(dream_id);

-- Намерение помочь (нажал «Хочу помочь»)
CREATE TABLE IF NOT EXISTS user_dream_help_intent (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, dream_id)
);
CREATE INDEX IF NOT EXISTS idx_user_dream_help_intent_user ON user_dream_help_intent(user_id);
CREATE INDEX IF NOT EXISTS idx_user_dream_help_intent_dream ON user_dream_help_intent(dream_id);
```

## mig_completion_request (запрос «Готово!» от помощника)

```sql
CREATE TABLE IF NOT EXISTS user_dream_completion_request (
    id SERIAL PRIMARY KEY,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    helper_user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(dream_id, helper_user_id)
);
CREATE INDEX IF NOT EXISTS idx_completion_request_dream ON user_dream_completion_request(dream_id);
CREATE INDEX IF NOT EXISTS idx_completion_request_helper ON user_dream_completion_request(helper_user_id);
```

## mig_favorite_notifications (уведомления «добавили в избранное»)

```sql
CREATE TABLE IF NOT EXISTS dream_favorite_notifications (
    id SERIAL PRIMARY KEY,
    owner_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dream_favorite_notif_owner ON dream_favorite_notifications(owner_id);
CREATE INDEX IF NOT EXISTS idx_dream_favorite_notif_dream ON dream_favorite_notifications(dream_id);
```

## mig_users_gender (пол для фильтра поиска бадди)

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS gender VARCHAR(1) NULL;
-- Допустимые значения: 'm' (мальчик), 'f' (девочка). NULL — не указан.
```

## mig_dreams_user_cascade (удаление пользователя удаляет его мечты)

```sql
ALTER TABLE dreams
  DROP CONSTRAINT IF EXISTS dreams_user_id_fkey,
  ADD CONSTRAINT dreams_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
```
