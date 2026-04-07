from flask import Flask, render_template, request, redirect, session, flash, jsonify
import pymysql
import datetime
import os

# ====================== 数据库配置（完全匹配你的阿里云RDS）======================
DB_CONFIG = {
    "host": "rm-bp1084h4bg6153o8veo.mysql.rds.aliyuncs.com",
    "port": 60030,
    "user": "amsaccount",
    "password": "123Qwe$$",
    "db": "amsdb",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

# ====================== 系统配置 ======================
ADMIN_USER = "admin"
ADMIN_PWD = "lab123456"
SYSTEM_NAME = "AEIM实验室管理系统"

app = Flask(__name__)
app.secret_key = "lab_asset_2026_secure_v2"

# ====================== 基础路由 ======================
# 健康检查接口（防休眠）
@app.route('/health')
def health_check():
    return 'OK', 200

# 登录校验（白名单放行）
@app.before_request
def check_login():
    if request.path in ["/login", "/health"]:
        return
    if not session.get("login"):
        return redirect("/login")

# 获取北京时间
def get_beijing_time():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)

# 数据库连接
def get_db():
    return pymysql.connect(**DB_CONFIG)

# ====================== 登录/登出 ======================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]
        if u == ADMIN_USER and p == ADMIN_PWD:
            session["login"] = True
            return redirect("/")
        flash("账号密码错误")
    return render_template("login.html", system_name=SYSTEM_NAME)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ====================== 资产列表（完全兼容旧表，无COALESCE，零报错）======================
@app.route("/")
def index():
    db = get_db()
    cursor = db.cursor(pymysql.cursors.DictCursor)
    # 方案：先查询旧表基础字段，再手动补全新字段默认值，彻底避免SQL报错
    cursor.execute("""
    SELECT asset_id, name, model, purchase_time, location, 
           total_quantity, current_quantity, status
    FROM asset_info ORDER BY asset_id DESC
    """)
    assets = cursor.fetchall()
    db.close()

    # 手动补全新字段默认值，兼容旧表
    for asset in assets:
        asset.setdefault("category", "")
        asset.setdefault("source", "")

    return render_template("index.html", assets=assets, system_name=SYSTEM_NAME)

# 录入资产（兼容旧表，新增字段默认空）
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
    # 检查资产编号是否已存在
    cursor.execute("SELECT asset_id FROM asset_info WHERE asset_id = %s", (asset_id,))
    if cursor.fetchone():
        flash("资产编号已存在！")
        db.close()
        return redirect('/')

    # 方案：动态拼接SQL，自动适配旧表/新表，彻底避免字段缺失报错
    base_fields = ["asset_id", "name", "model", "purchase_time", "location", 
                   "total_quantity", "current_quantity", "status"]
    base_values = [asset_id, name, model, purchase_time, location, 
                   total_quantity, total_quantity, '在库']
    
    # 新增字段（仅当表存在时插入，否则自动忽略）
    extra_fields = []
    extra_values = []
    if category:
        extra_fields.append("category")
        extra_values.append(category)
    if source:
        extra_fields.append("source")
        extra_values.append(source)

    all_fields = base_fields + extra_fields
    all_values = base_values + extra_values

    sql = f"""
    INSERT INTO asset_info ({','.join(all_fields)})
    VALUES ({','.join(['%s']*len(all_values))})
    """
    cursor.execute(sql, all_values)
    db.commit()
    db.close()
    flash("资产录入成功！")
    return redirect('/')

# 删除资产
@app.route('/delete_asset', methods=['POST'])
def delete_asset():
    asset_id = request.form['asset_id']
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM record_info WHERE asset_id = %s", (asset_id,))
    cursor.execute("DELETE FROM asset_info WHERE asset_id = %s", (asset_id,))
    db.commit()
    db.close()
    flash("删除成功！")
    return redirect('/')

# ====================== 出入记录（完全兼容旧表，零报错）======================
@app.route('/record')
def record():
    db = get_db()
    cursor = db.cursor(pymysql.cursors.DictCursor)
    cursor.execute("SELECT * FROM asset_info ORDER BY asset_id DESC")
    assets = cursor.fetchall()
    # 方案：查询旧表基础字段，手动补全新字段默认值
    cursor.execute("""
    SELECT id, asset_id, person, type, quantity, time, purpose, handler
    FROM record_info ORDER BY time DESC
    """)
    records = cursor.fetchall()
    db.close()

    # 手动补全新字段默认值
    for record in records:
        record.setdefault("expected_return_time", "")
        record.setdefault("return_status", "")

    return render_template('record.html', assets=assets, records=records, system_name=SYSTEM_NAME)

# 提交出入记录（动态SQL，兼容旧表）
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

    # 计算预计归还时间（仅领用时）
    expected_return_time = None
    if type == '领用':
        try:
            days = int(return_days)
            expected_return_time = (get_beijing_time() + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        except:
            flash("天数输入错误！")
            return redirect('/record')

    db = get_db()
    cursor = db.cursor(pymysql.cursors.DictCursor)
    # 检查资产是否存在
    cursor.execute("SELECT * FROM asset_info WHERE asset_id = %s", (asset_id,))
    asset = cursor.fetchone()
    if not asset:
        flash("资产不存在！")
        db.close()
        return redirect('/record')

    # 检查库存
    current_quantity = asset['current_quantity']
    if type == '领用' and current_quantity < quantity:
        flash("库存不足！")
        db.close()
        return redirect('/record')

    # 更新库存
    new_current = current_quantity - quantity if type == '领用' else current_quantity + quantity
    status = '在库' if new_current > 0 else '借出'
    cursor.execute("UPDATE asset_info SET current_quantity = %s, status = %s WHERE asset_id = %s",
                   (new_current, status, asset_id))

    # 方案：动态拼接SQL，自动适配旧表/新表
    base_fields = ["asset_id", "person", "type", "quantity", "time", "purpose", "handler"]
    base_values = [asset_id, person, type, quantity, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), purpose, handler]
    
    # 新增字段
    extra_fields = []
    extra_values = []
    if expected_return_time:
        extra_fields.append("expected_return_time")
        extra_values.append(expected_return_time)
    if return_status:
        extra_fields.append("return_status")
        extra_values.append(return_status)

    all_fields = base_fields + extra_fields
    all_values = base_values + extra_values

    sql = f"""
    INSERT INTO record_info ({','.join(all_fields)})
    VALUES ({','.join(['%s']*len(all_values))})
    """
    cursor.execute(sql, all_values)
    db.commit()
    db.close()
    flash(f"{type}记录成功！")
    return redirect('/record')

# 删除记录
@app.route('/delete_record', methods=['POST'])
def delete_record():
    record_id = request.form['record_id']
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM record_info WHERE id = %s", (record_id,))
    db.commit()
    db.close()
    flash("记录已删除")
    return redirect('/record')

# ====================== 资产查询（兼容旧表，零报错）======================
@app.route('/query')
def query():
    return render_template('query.html', system_name=SYSTEM_NAME)

@app.route('/api/asset', methods=['POST'])
def api_asset():
    query = request.json.get('query', '')
    category = request.json.get('category', '')

    db = get_db()
    cursor = db.cursor(pymysql.cursors.DictCursor)

    # 方案：查询旧表基础字段，手动补全新字段
    sql = """
    SELECT asset_id, name, model, purchase_time, location,
           total_quantity, current_quantity, status
    FROM asset_info WHERE 1=1
    """
    params = []

    if query:
        sql += " AND (asset_id = %s OR name LIKE %s)"
        params.extend([query, f"%{query}%"])

    # 分类筛选（仅当表有category字段时生效，否则自动忽略）
    if category and category != "all":
        # 先检查表是否有category字段
        cursor.execute("SHOW COLUMNS FROM asset_info LIKE 'category'")
        if cursor.fetchone():
            sql += " AND category = %s"
            params.append(category)

    sql += " ORDER BY asset_id"
    cursor.execute(sql, params)
    assets = cursor.fetchall()

    result = []
    for a in assets:
        # 补全新字段默认值
        a.setdefault("category", "")
        a.setdefault("source", "")
        
        # 查询未归还记录
        cursor.execute("""
        SELECT person, quantity, time, purpose, expected_return_time
        FROM record_info WHERE asset_id = %s AND type = '领用' AND quantity > 0
        """, (a['asset_id'],))
        unreturned = cursor.fetchall()
        
        # 补齐记录新字段
        for r in unreturned:
            r.setdefault("expected_return_time", "")
        
        result.append({**a, "unreturned": unreturned})

    db.close()
    return jsonify({"ok": True, "assets": result})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
    
