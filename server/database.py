import os
import pathlib

import mysql.connector

def all_migrations() -> list[str]:
    root = pathlib.Path(__file__).parent.parent
    migrations_dir = root / 'migrations'

    migration_files = sorted(migrations_dir.glob('*.sql'))

    return [str(migration.relative_to(root)) for migration in migration_files]

def execute_migrations() -> None:
    conn = mysql.connector.connect(
        host=os.getenv('MYSQL_HOST', 'localhost'),
        port=int(os.getenv('MYSQL_PORT', '3306')),
        user=os.getenv('MYSQL_USER', 'root'),
        password=os.getenv('MYSQL_PASSWORD', ''),
        database=os.getenv('MYSQL_DATABASE', 'chat'),
    )

    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS migrations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
        )
    ''')

    cur.execute('SELECT name FROM migrations')
    applied_migrations = set()

    for (name,) in cur.fetchall():
        applied_migrations.add(name)

    for migration in all_migrations():
        if migration in applied_migrations:
            continue

        with open(pathlib.Path(__file__).parent.parent / migration, 'r') as f:
            sql = f.read()

        cur.execute(sql)
        cur.execute('INSERT INTO migrations (name) VALUES (%s)', (migration,))
        conn.commit()

