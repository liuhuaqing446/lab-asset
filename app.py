from flask import Flask, render_template, request, redirect, session, flash, jsonify
import mysql.connector
import datetime
import os

app = Flask(__name__)
app.secret_key = 'lab_asset_2026'
app.config['SESSION_PERMANENT'] = False

def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        charset='utf8mb4',
        autocommit=True
    )

@app.route('/health')
def health_check():
    return 'OK', 200

@app.before_request
def check_login():
    if request.path in ['/login', '/do_login', '/health']:
        return
    if not session.get("login"):
        return redirect('/login')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/do_login', methods=['POST'])
def do_login():
    username = request.form['username']
    password = request.form['password']
    if username == 'admin' and password == '123456':
        session['login'] = True
        return redirect('/')
    flash('账号或密码错误')
    return redirect('/login')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/')
def index():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM assets ORDER BY asset_id DESC")
    assets = cursor.fetchall()
    db.close()
    return render_template('index.html', assets=assets)

@app.route('/add_asset', methods=['POST'])
def add_asset():
    asset_id = request.form['asset_id']
    name = request.form['name']
    model = request.form.get('model', '')
    purchase_time = request.form.get('purchase_time', '')
    location = request.form.get('location', '')
    total_quantity = int(request.form['total_quantity'])
    category = request.form.get('category', '')
    source = request.form.get('source', '学校')

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT asset_id FROM assets WHERE asset_id = %s", (asset_id,))
    if cursor.fetchone():
        flash("资产编号已存在！")
        db.close()
        return redirect('/')

    sql = """
    INSERT INTO assets (asset_id, name, model, purchase_time, location, total_quantity, current_quantity, status, category, source)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    cursor.execute(sql, (
        asset_id, name, model, purchase_time, location,
        total_quantity, total_quantity, '在库', category, source
    ))
    db.commit()
    db.close()
    flash("资产录入成功！")
    return redirect('/')

@app.route('/delete_asset', methods=['POST'])
def delete_asset():
    asset_id = request.form['asset_id']
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM records WHERE asset_id = %s", (asset_id,))
    cursor.execute("DELETE FROM assets WHERE asset_id = %s", (asset_id,))
    db.commit()
    db.close()
    flash("删除成功！")
    return redirect('/')

@app.route('/record')
def record():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM assets ORDER BY asset_id DESC")
    assets = cursor.fetchall()
    cursor.execute("SELECT * FROM records ORDER BY time DESC")
    records = cursor.fetchall()
    db.close()
    return render_template('record.html', assets=assets, records=records)

@app.route('/do_record', methods=['POST'])
def do_record():
    asset_id = request.form['asset_id']
    person = request.form['person']
    type = request.form['type']
    quantity = int(request.form['quantity'])
    purpose = request.form.get('purpose', '')
    handler = request.form.get('handler', '')
    return_days = request.form.get('return_days', 7)
    return_status = request.form.get('return_status', '正常')

    expected_return_time = None
    if type == '领用':
        try:
            days = int(return_days)
            expected_return_time = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        except:
            flash("天数输入错误！")
            return redirect('/record')

    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM assets WHERE asset_id = %s", (asset_id,))
    asset = cursor.fetchone()
    if not asset:
        flash("资产不存在！")
        db.close()
        return redirect('/record')

    current = asset['current_quantity']
    if type == '领用' and current < quantity:
        flash("库存不足！")
        db.close()
        return redirect('/record')

    new_current = current - quantity if type == '领用' else current + quantity
    status = '在库' if new_current > 0 else '借出'
    cursor.execute("UPDATE assets SET current_quantity = %s, status = %s WHERE asset_id = %s",
                   (new_current, status, asset_id))

    sql = """
    INSERT INTO records (asset_id, person, type, quantity, time, purpose, handler, expected_return_time, return_status)
    VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s)
    """
    cursor.execute(sql, (
        asset_id, person, type, quantity, purpose, handler, expected_return_time, return_status
    ))
    db.commit()
    db.close()
    flash(f"{type}记录成功！")
    return redirect('/record')

@app.route('/delete_record', methods=['POST'])
def delete_record():
    record_id = request.form['record_id']
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM records WHERE id = %s", (record_id,))
    db.commit()
    db.close()
    flash("记录已删除")
    return redirect('/record')

@app.route('/query')
def query():
    return render_template('query.html')

@app.route('/api/asset', methods=['POST'])
def api_asset():
    query = request.json.get('query', '')
    category = request.json.get('category', '')

    db = get_db()
    cursor = db.cursor(dictionary=True)

    sql = """
    SELECT asset_id, name, model, category, source, purchase_time, location,
           total_quantity, current_quantity, status
    FROM assets WHERE 1=1
    """
    params = []

    if query:
        sql += " AND (asset_id = %s OR name LIKE %s)"
        params.extend([query, f"%{query}%"])

    if category and category != "all":
        sql += " AND category = %s"
        params.append(category)

    sql += " ORDER BY asset_id"
    cursor.execute(sql, params)
    assets = cursor.fetchall()

    result = []
    for a in assets:
        cursor.execute("""
        SELECT person, quantity, time, purpose, expected_return_time
        FROM records WHERE asset_id = %s AND type = '领用' AND quantity > 0
        """, (a['asset_id'],))
        unreturned = cursor.fetchall()
        result.append({
            **a,
            'unreturned': unreturned
        })

    db.close()
    return jsonify({"ok": True, "assets": result})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
