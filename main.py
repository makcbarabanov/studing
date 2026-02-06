import os
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()


def get_db_connection():
    """Создаёт подключение к PostgreSQL из переменных окружения."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
        cursor_factory=RealDictCursor,
    )


@app.get("/")
def read_root():
    return {"message": "Wellcome to the Island!"}


@app.get("/dreams")
def get_dreams():
    """Возвращает ФИО и город пользователя с id=1 из таблицы users."""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT name || ' ' || surname, city FROM users WHERE id = 1"
                )
                row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Пользователь с id=1 не найден")
            return {
                "full_name": row["full_name"],
                "city": row["city"],
            }
        finally:
            conn.close()
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Ошибка базы данных: {str(e)}")
