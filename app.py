import sqlite3
import sys,os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from flask import Flask, render_template, request

app = Flask(__name__)

def get_db_connection():
    conn = sqlite3.connect("atcoder_problems.db")
    conn.row_factory = sqlite3.Row
    return conn

@app.route("/", methods=["GET","POST"])
def index():
    keyword = request.args.get("keyword", "").strip()
    contest_type = request.args.get("contest_type", "").strip()
    min_score = request.args.get("min_score", "")
    max_score = request.args.get("max_score", "")

    query = "SELECT * FROM problems WHERE 1=1"
    params = []

    # キーワード検索（タイトル、問題文、解説文を対象に検索）
    if keyword:
        query += " AND (title LIKE ? OR content LIKE ? OR editorial_content LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])

    # コンテスト種別絞り込み
    if contest_type:
        query += " AND contest_id LIKE ?"
        params.append(f"{contest_type.lower()}%")

    # 配点絞り込み
    if min_score.isdigit():
        query += " AND score >= ?"
        params.append(int(min_score))
    if max_score.isdigit():
        query += " AND score <= ?"
        params.append(int(max_score))

    query += " LIMIT 100"

    conn = get_db_connection()
    results = conn.execute(query, params).fetchall()
    conn.close()

    return render_template(
        "index.html",
        results=results,
        keyword=keyword,
        contest_type=contest_type,
        min_score=min_score,
        max_score=max_score
    )

if __name__ == "__main__":
    app.run(debug=True)