import sqlite3
import time
import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

API_URL = "https://kenkoooo.com/atcoder/resources/merged-problems.json"
DB_NAME = "atcoder_problems.db"
SLEEP_INTERVAL = 1.8  # サーバー負荷軽減用

def setup_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS problems (
        id TEXT PRIMARY KEY,
        contest_id TEXT,
        title TEXT,
        score INTEGER,
        url TEXT,
        content TEXT,
        editorial_url TEXT,
        editorial_content TEXT
    )
    """)
    
    # 既存DBへのカラム追加対応
    cursor.execute("PRAGMA table_info(problems)")
    columns = [col[1] for col in cursor.fetchall()]
    if "editorial_url" not in columns:
        cursor.execute("ALTER TABLE problems ADD COLUMN editorial_url TEXT")
    if "editorial_content" not in columns:
        cursor.execute("ALTER TABLE problems ADD COLUMN editorial_content TEXT")
        
    conn.commit()
    return conn

def sync_metadata_from_api(conn):
    print("=== Step 1: APIから基本データを取得中 ===")
    try:
        response = requests.get(API_URL, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"[エラー] APIの取得に失敗しました: {e}")
        return

    problems_data = response.json()
    print(f"全 {len(problems_data)} 件の問題基本情報を取得しました。")

    cursor = conn.cursor()
    records = []
    for problem in problems_data:
        problem_id = problem.get("id", "")
        contest_id = problem.get("contest_id", "")
        title = problem.get("title", problem_id)
        
        raw_score = problem.get("point")
        score = int(raw_score) if raw_score is not None else 0
        url = f"https://atcoder.jp/contests/{contest_id}/tasks/{problem_id}"

        records.append((problem_id, contest_id, title, score, url))

    cursor.executemany("""
    INSERT INTO problems (id, contest_id, title, score, url, content, editorial_url, editorial_content)
    VALUES (?, ?, ?, ?, ?, '', '', '')
    ON CONFLICT(id) DO UPDATE SET
        contest_id = excluded.contest_id,
        title = excluded.title,
        score = excluded.score,
        url = excluded.url
    """, records)

    conn.commit()
    print("基本データの同期完了。\n")

def get_editorial_url_and_content(contest_id, problem_id, session, headers):
    """
    1. コンテストの解説一覧ページ、または問題ページから解説リンクを探す
    2. 解説本文を取得する
    """
    editorial_page_url = f"https://atcoder.jp/contests/{contest_id}/editorial"
    
    target_editorial_url = ""
    editorial_text = ""

    try:
        # コンテストの解説一覧を取得
        resp = session.get(editorial_page_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # 各問題への解説リンクを探す
            # 例: /contests/abc300/editorial/6273 や /tasks/abc300_a に対応するリンク
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if f"/tasks/{problem_id}" in href or f"editorial/{problem_id}" in href or f"editorial/" in href:
                    # 問題IDに該当する解説リンクかを判定
                    if problem_id in href or problem_id.replace("_", "-") in href:
                        target_editorial_url = urljoin(editorial_page_url, href)
                        break

        # 個別解説ページから文章を取得
        if target_editorial_url:
            time.sleep(SLEEP_INTERVAL)
            ed_resp = session.get(target_editorial_url, headers=headers, timeout=10)
            if ed_resp.status_code == 200:
                ed_soup = BeautifulSoup(ed_resp.text, "html.parser")
                # AtCoderのWeb解説本文
                main_content = ed_soup.find("div", id="main-container") or ed_soup.find("div", class_="blog-post")
                if main_content:
                    editorial_text = main_content.text.strip()
                else:
                    editorial_text = ed_soup.text.strip()
        else:
            target_editorial_url = editorial_page_url  # 個別解説がない場合は一覧ページをリンクとする
            editorial_text = "（Web解説テキスト未発見）"

    except Exception as e:
        editorial_text = f"（取得失敗: {e}）"

    return target_editorial_url, editorial_text

def fetch_missing_contents(conn):
    print("=== Step 2: 問題文・解説文のスクレイピング開始 ===")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, contest_id, url, content, editorial_content 
        FROM problems 
        WHERE content IS NULL OR content = '' 
           OR editorial_content IS NULL OR editorial_content = ''
    """)
    missing_rows = cursor.fetchall()
    total = len(missing_rows)

    if total == 0:
        print("すべての問題文・解説文が取得済みです。")
        return

    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    for i, (problem_id, contest_id, url, content, editorial) in enumerate(missing_rows, 1):
        print(f"[{i}/{total}] 処理中: {problem_id} ... ", end="", flush=True)

        updated_content = content
        editorial_url = ""
        updated_editorial = editorial

        # 1. 問題文を取得
        if not content:
            try:
                resp = session.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    task_stmt = soup.find("div", id="task-statement")
                    updated_content = task_stmt.text.strip() if task_stmt else "（問題文取得不可）"
                time.sleep(SLEEP_INTERVAL)
            except Exception:
                updated_content = "（エラー）"

        # 2. 解説URLと解説文を取得
        if not editorial:
            editorial_url, updated_editorial = get_editorial_url_and_content(
                contest_id, problem_id, session, headers
            )
            time.sleep(SLEEP_INTERVAL)

        # DB書き込み
        cursor.execute("""
            UPDATE problems 
            SET content = ?, editorial_url = ?, editorial_content = ? 
            WHERE id = ?
        """, (updated_content or "", editorial_url or "", updated_editorial or "", problem_id))
        conn.commit()

        print("成功")

if __name__ == "__main__":
    conn = setup_db()
    sync_metadata_from_api(conn)
    fetch_missing_contents(conn)
    conn.close()
