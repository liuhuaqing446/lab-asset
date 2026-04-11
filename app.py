from flask import Flask, render_template, request, flash, redirect, session, jsonify
import pymysql
from datetime import datetime, timedelta
import os
import requests
import threading
import time

# 数据库配置（无需修改）
DB_CONFIG = {
    "host": "rm-bp1084h4bg6153o8veo.mysql.rds.aliyuncs.com",
    "port": 60030,
    "user": "amsaccount",
    "password": "123Qwe$$",
    "db": "amsdb",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

# 系统配置
ADMIN_USER = "lab429"
ADMIN_PWD = "123456"
SYSTEM_NAME = "AEIM实验室管理系统"
CATEGORIES = ["机械类", "电气类", "其他类"]
SOURCES = ["自购", "企业", "学校"]
DEFAULT_RETURN_DAYS = 1
# 定时唤醒配置
WAKE_UP_INTERVAL = 300
SELF_URL = os.environ.get('SELF_URL', 'https://lab-asset-2.onrender.com')

app = Flask(__name__)
app.secret_key = "lab_asset_2026_final_secure"

# 定时唤醒服务（Render防休眠，本地不启动）
def wake_up_service():
    while True:
        try:
            response = requests.get(f"{SELF_URL}/health", timeout=5)
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 唤醒成功，状态码：{response.status_code}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 唤醒异常：{str(e)}")
        time.sleep(WAKE_UP_INTERVAL)
if os.environ.get('PORT'):
    threading.Thread(target=wake_up_service, daemon=True).start()
    print(f"✅ 定时唤醒服务启动，间隔{WAKE_UP_INTERVAL/60}分钟，目标：{SELF_URL}")

# 基础工具函数
@app.route('/health')
def health_check():
    return 'OK', 200
def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)
def format_beijing_time(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")
def get_db():
    return pymysql.connect(**DB_CONFIG)

# 登录校验
@app.before_request
def check_login():
    if request.path in ["/login", "/health"]:
        return
    if not session.get("login"):
        return redirect("/login")

# 登录/登出
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        if username == ADMIN_USER and password == ADMIN_PWD:
            session["login"] = True
            return redirect("/")
        flash("⚠️ 账号或密码错误")
    return render_template("login.html", system_name=SYSTEM_NAME)
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# 资产列表（核心：采购时间无占位符）
@app.route("/")
def index():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM asset_info ORDER BY asset_id")
    assets = cur.fetchall()
    db.close()
    return render_template("index.html", assets=assets, system_name=SYSTEM_NAME, categories=CATEGORIES, sources=SOURCES)

# 新增资产（采购时间无占位符，未选则留空）
@app.route("/add_asset", methods=["POST"])
def add_asset():
    form_data = request.form
    if not form_data.get("asset_id") or not form_data.get("name") or not form_data.get("category") or not form_data.get("source"):
        flash("⚠️ 资产编号、名称、分类、来源为必填项！")
        return redirect("/")
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT asset_id FROM asset_info WHERE asset_id=%s", (form_data["asset_id"],))
        if cur.fetchone():
            flash("⚠️ 该资产编号已存在！")
            return redirect("/")
        model_origin = form_data.get("model", "")
        model_with_ext = f"{model_origin}|{form_data['category']}-{form_data['source']}" if model_origin else f"{form_data['category']}-{form_data['source']}"
        # 采购时间：用户未选则留空，无占位符
        purchase_time = form_data.get("purchase_time", "")
        cur.execute("""
            INSERT INTO asset_info (asset_id, name, model, purchase_time, location, total_quantity, current_quantity, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            form_data["asset_id"], form_data["name"], model_with_ext, purchase_time,
            form_data.get("location", ""), int(form_data.get("total_quantity", 1)),
            int(form_data.get("total_quantity", 1)), "在库"
        ))
        db.commit()
        flash("✅ 资产添加成功！")
    except Exception as e:
        print(f"添加资产失败: {e}")
        flash("❌ 资产添加失败，请检查数据！")
    finally:
        db.close()
    return redirect("/")

# 删除资产
@app.route("/delete_asset", methods=["POST"])
def delete_asset():
    asset_id = request.form["asset_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("DELETE FROM record_info WHERE asset_id=%s", (asset_id,))
        cur.execute("DELETE FROM asset_info WHERE asset_id=%s", (asset_id,))
        db.commit()
        flash("✅ 资产删除成功！")
    except Exception as e:
        print(f"删除资产失败: {e}")
        flash("❌ 资产删除失败！")
    finally:
        db.close()
    return redirect("/")
# 出入记录页面路由（GET请求，展示记录和表单）
@app.route('/record')
def record():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    # 1. 查询所有资产数据，用于模板匹配名称/型号
    cursor = db.cursor()
    cursor.execute("SELECT asset_id, name, model FROM assets")
    assets_data = cursor.fetchall()
    
    # 格式化资产列表，统一ID为字符串，避免类型不匹配
    assets = []
    for asset in assets_data:
        model_str = asset[2] or ''
        model_origin = model_str
        # 解析型号中的分类/来源（和资产列表页逻辑保持一致）
        if '|' in model_str:
            parts = model_str.split('|', 1)
            model_origin = parts[0]
        elif '-' in model_str:
            model_origin = model_str.split('-')[0]
        assets.append({
            'asset_id': str(asset[0]),  # 强制转字符串，确保匹配
            'name': asset[1],
            'model_origin': model_origin or '无'
        })
    
    # 2. 查询所有出入记录
    cursor.execute("SELECT id, asset_id, person, type, quantity, time, purpose FROM records ORDER BY id DESC")
    records_data = cursor.fetchall()
    
    # 格式化记录列表，统一ID为字符串
    records = []
    for r in records_data:
        records.append({
            'id': r[0],
            'asset_id': str(r[1]),  # 强制转字符串，和资产ID匹配
            'person': r[2],
            'type': r[3],
            'quantity': r[4],
            'time': r[5],
            'purpose': r[6]
        })
    
    # 3. 渲染模板，传递资产列表和记录列表
    return render_template('record.html', system_name=SYSTEM_NAME, records=records, assets=assets)

# 提交出入记录路由（POST请求，处理表单提交）
@app.route('/do_record', methods=['POST'])
def do_record():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    asset_id = request.form['asset_id']
    person = request.form['person']
    op_type = request.form['type']
    quantity = int(request.form['quantity'])
    
    cursor = db.cursor()
    # 校验资产是否存在
    cursor.execute("SELECT current_quantity, total_quantity FROM assets WHERE asset_id = %s", (asset_id,))
    asset = cursor.fetchone()
    if not asset:
        flash('资产不存在！')
        return redirect(url_for('record'))
    
    current_qty, total_qty = asset[0], asset[1]
    
    # 处理领用/归还逻辑
    if op_type == '领用':
        if current_qty < quantity:
            flash('库存不足，无法领用！')
            return redirect(url_for('record'))
        return_days = int(request.form['return_days'])
        purpose = request.form['purpose'] or '未填写'
        # 计算预计归还时间
        return_time = (datetime.now() + timedelta(days=return_days)).strftime('%Y-%m-%d %H:%M:%S')
        # 保存记录：用途+预计归还时间
        purpose_str = f"{purpose}|预计归还：{return_time}"
        # 更新库存
        cursor.execute("UPDATE assets SET current_quantity = current_quantity - %s WHERE asset_id = %s", (quantity, asset_id))
    else:
        # 归还操作
        device_status = request.form['device_status']
        purpose_str = f"设备状态：{device_status}"
        # 更新库存
        cursor.execute("UPDATE assets SET current_quantity = current_quantity + %s WHERE asset_id = %s", (quantity, asset_id))
    
    # 插入记录
    now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute(
        "INSERT INTO records (asset_id, person, type, quantity, time, purpose) VALUES (%s, %s, %s, %s, %s, %s)",
        (asset_id, person, op_type, quantity, now_time, purpose_str)
    )
    db.commit()
    flash('操作成功！')
    return redirect(url_for('record'))

# 查询页
@app.route("/query")
def query():
    return render_template("query.html", system_name=SYSTEM_NAME, categories=CATEGORIES)

# 查询API（单输入框：编号/名称通用，保留分类筛选）
@app.route("/api/asset", methods=["POST"])
def api_asset():
    req_data = request.json
    search_key = req_data.get("search_key", "").strip()
    cate_filter = req_data.get("category", "").strip()
    db = get_db()
    cur = db.cursor()
    query_sql = "SELECT * FROM asset_info WHERE 1=1"
    params = []
    # 单输入框模糊查询：资产编号 + 资产名称
    if search_key:
        query_sql += " AND (asset_id LIKE %s OR name LIKE %s)"
        params.append(f"%{search_key}%")
        params.append(f"%{search_key}%")
    # 分类筛选
    if cate_filter:
        query_sql += " AND (model LIKE %s OR model LIKE %s)"
        params.append(f"%|{cate_filter}-%")
        params.append(f"{cate_filter}-%")
    query_sql += " ORDER BY asset_id"
    cur.execute(query_sql, params)
    assets = cur.fetchall()
    if not assets:
        db.close()
        return jsonify(ok=False, msg="未查询到符合条件的资产")
    # 解析资产信息
    asset_list = []
    for asset in assets:
        model_str = asset.get("model", "")
        asset_category, asset_source, model_origin = "未分类", "未知来源", model_str
        if "|" in model_str:
            model_origin, ext = model_str.split("|", 1)
            if "-" in ext:
                asset_category, asset_source = ext.split("-", 1)
        elif "-" in model_str:
            model_origin = "无"
            asset_category, asset_source = model_str.split("-", 1)
        asset["model_origin"] = model_origin
        asset["category"] = asset_category
        asset["source"] = asset_source
        asset_list.append(asset)
    # 组装未归还记录
    result = []
    for asset in asset_list:
        cur.execute("""
            SELECT person, SUM(CASE WHEN type='领用' THEN quantity ELSE 0 END) as total_borrowed,
                   SUM(CASE WHEN type='归还' THEN quantity ELSE 0 END) as total_returned,
                   GROUP_CONCAT(time ORDER BY time DESC) as times,
                   GROUP_CONCAT(purpose ORDER BY time DESC) as purposes
            FROM record_info WHERE asset_id=%s GROUP BY person HAVING (total_borrowed - total_returned) > 0
        """, (asset["asset_id"],))
        unreturned_list = cur.fetchall()
        unreturned = []
        for item in unreturned_list:
            person, borrowed, returned = item["person"], item["total_borrowed"], item["total_returned"]
            times, purposes = item["times"].split(","), item["purposes"].split(",")
            latest_time, latest_purpose, expected_return = times[0], purposes[0] or "未填写", "无"
            if "预计归还：" in latest_purpose:
                if "|" in latest_purpose:
                    latest_purpose, return_part = latest_purpose.split("|", 1)
                    expected_return = return_part.replace("预计归还：", "")
                else:
                    expected_return = latest_purpose.replace("预计归还：", "")
                    latest_purpose = "领用"
            unreturned.append({
                "person": person, "quantity": borrowed - returned,
                "time": latest_time, "purpose": latest_purpose, "expected_return": expected_return
            })
        result.append({"asset": asset, "unreturned": unreturned})
    db.close()
    return jsonify(ok=True, data=result)

# 启动服务
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
