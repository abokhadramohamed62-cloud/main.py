from flask import Flask, request
import sqlite3

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Online"

@app.route("/verify/<int:user_id>")
def verify(user_id):
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)

    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS ip_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        ip TEXT
    )
    """)

    c.execute("SELECT user_id FROM ip_logs WHERE ip=?", (ip,))
    row = c.fetchone()

    if row and row[0] != user_id:
        conn.close()
        return "❌ تم اكتشاف حساب آخر يستخدم نفس IP"

    c.execute(
        "INSERT INTO ip_logs (user_id, ip) VALUES (?, ?)",
        (user_id, ip)
    )

    conn.commit()
    conn.close()

    return "✅ تم التحقق بنجاح"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
