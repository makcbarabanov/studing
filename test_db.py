import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Параметры подключения
DB_PARAMS = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASS"),
    "dbname": os.getenv("DB_NAME")
}

def check_my_deeds():
    try:
        # Сдвиг 4 пробела
        print("🔍 Попытка подключения к удаленной базе...")
        connection = psycopg2.connect(**DB_PARAMS)
        
        # Сдвиг 8 пробелов
        cursor = connection.cursor()
        print("📈 Считаю добрые дела...")
        cursor.execute("SELECT count(*) FROM good_deeds;")
        
        # Получаем результат (это кортеж типа (103,))
        result = cursor.fetchone()
        count = result[0]
        
        print(f"✅ Успех! Найдено {count} добрых дел.")
        
        # Закрываем всё за собой
        cursor.close()
        connection.close()
        print("🚪 Соединение закрыто.")

    except Exception as error:
        print(f"❌ Ошибка: {error}")

if __name__ == "__main__":
    check_my_deeds()
