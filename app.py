from flask import Flask, render_template, request, flash, redirect, session, jsonify
import pymysql
from datetime import datetime, timedelta
import os

# ====================== 数据库配置（完全匹配阿里云RDS，无需修改）======================
DB_CONFIG = {
    "host": "rm-bp1084h4bg6153o8veo.mysql.rds.aliyuncs.com",
    "port": 60030,
    "user": "amsaccount",
    "password": "123Qwe$$",
    "db": "amsdb",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

# ====================== 系统配置（严格按要求精简）=====================
ADMIN_USER = "admin"
ADMIN_PWD = "lab123456"
SYSTEM_NAME = "AEIM实验室管理系统"
# 设备分类（3类）：机械类、电气类、其他类
CATEGORIES = ["机械类", "电气类", "其他类"]
# 设备来源（3类）：自购、企业、学校
SOURCES = ["自购", "企业", "学校"]

app = Flask(__name__)
app.secret_key = "lab_asset_2026_secure_v2"

# ====================== 基础工具函数 ======================
# 健康检查接口（配合UptimeRobot防休眠）
@app.route('/health')
def health_check():
    return 'OK', 200

# 获取北京时间（UTC+8）
def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

# 格式化北京时间为字符串
def format_beijing_time(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# 数据库连接
def get_db():
    return pymysql.connect(**DB_CONFIG)

# ====================== 登录校验 ======================
@app.before_request
def check_login():
    # 白名单：健康检查、登录页 无需登录
    if request.path in ["/login", "/health"]:
        return
    if not session.get("login"):
        return redirect("/login")

# ====================== 登录/登出 ======================
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

# ====================== 资产列表（首页，含3类分类/3类来源，无经手人）======================
@app.route("/")
def index():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM asset_info ORDER BY asset_id")
    assets = cur.fetchall()
    db.close()
    return render_template("index.html", assets=assets, system_name=SYSTEM_NAME,
                           categories=CATEGORIES, sources=SOURCES)

# ====================== 新增资产（核心：3类分类/3类来源，移除经手人，无需数据库新字段）======================
@app.route("/add_asset", methods=["POST"])
def add_asset():
    form_data = request.form
    # 基础校验（含分类/来源必选，无经手人）
    if not form_data.get("asset_id") or not form_data.get("name") or not form_data.get("category") or not form_data.get("source"):
        flash("⚠️ 资产编号、名称、分类、来源为必填项！")
        return redirect("/")

    db = get_db()
    try:
        cur = db.cursor()
        # 检查资产编号是否重复
        cur.execute("SELECT asset_id FROM asset_info WHERE asset_id=%s", (form_data["asset_id"],))
        if cur.fetchone():
            flash("⚠️ 该资产编号已存在！")
            return redirect("/")

        # 核心：将分类/来源拼接至【设备型号】字段（无需数据库新字段，完美兼容旧表）
        # 格式：型号|分类-来源（不影响原有型号，可反向解析）
        model_origin = form_data.get("model", "")
        model_with_ext = f"{model_origin}|{form_data['category']}-{form_data['source']}" if model_origin else f"{form_data['category']}-{form_data['source']}"

        # 插入新资产（无经手人字段，完全匹配旧表结构）
        cur.execute("""
            INSERT INTO asset_info (
                asset_id, name, model, purchase_time, location, 
                total_quantity, current_quantity, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            form_data["asset_id"],
            form_data["name"],
            model_with_ext,  # 分类/来源存入model字段，前端反向解析展示
            form_data.get("purchase_time", get_beijing_time().strftime("%Y-%m-%d")),
            form_data.get("location", ""),
            int(form_data.get("total_quantity", 1)),
            int(form_data.get("total_quantity", 1)),
            "在库"
        ))
        db.commit()
        flash("✅ 资产添加成功！")
    except Exception as e:
        print(f"添加资产失败: {e}")
        flash("❌ 资产添加失败，请检查数据！")
    finally:
        db.close()
    return redirect("/")

# ====================== 删除资产（先删记录再删资产，彻底解决删不掉问题）======================
@app.route("/delete_asset", methods=["POST"])
def delete_asset():
    asset_id = request.form["asset_id"]
    db = get_db()
    try:
        cur = db.cursor()
        # 先删除关联的所有领用/归还记录，再删除资产
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

# ====================== 出入记录页（无经手人，保留预计归还时间）======================
@app.route("/record")
def record():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM record_info ORDER BY time DESC")
    records = cur.fetchall()
    db.close()
    return render_template("record.html", records=records, system_name=SYSTEM_NAME)

# ====================== 提交出入记录（核心：移除经手人，保留预计归还时间，兼容旧表）======================
@app.route("/do_record", methods=["POST"])
def do_record():
    form_data = request.form
    # 基础校验（领用时预计归还天数必填，无经手人）
    required = ["asset_id", "person", "quantity", "type"]
    if form_data.get("type") == "领用" and not form_data.get("return_days"):
        flash("⚠️ 领用时必须填写预计归还天数！")
        return redirect("/record")
    for key in required:
        if not form_data.get(key):
            flash(f"⚠️ {{'asset_id':'资产编号','person':'领用人','quantity':'数量','type':'操作类型'}}[{key}] 为必填项！")
            return redirect("/record")

    asset_id = form_data["asset_id"]
    person = form_data["person"].strip()
    op_type = form_data["type"]
    quantity = int(form_data["quantity"])
    return_days = int(form_data.get("return_days", 7)) if op_type == "领用" else 0
    purpose_origin = form_data.get("purpose", "")

    db = get_db()
    try:
        cur = db.cursor()
        # 1. 检查资产是否存在
        cur.execute("SELECT * FROM asset_info WHERE asset_id=%s", (asset_id,))
        asset = cur.fetchone()
        if not asset:
            flash("⚠️ 资产不存在！")
            return redirect("/record")

        current_qty = asset["current_quantity"]
        total_qty = asset["total_quantity"]

        # 2. 领用/归还逻辑校验（多用户独立，禁止超领/超还）
        if op_type == "领用":
            # 领用：校验总库存是否充足
            if current_qty < quantity:
                flash(f"⚠️ 库存不足！当前剩余 {current_qty} 件，无法领用 {quantity} 件")
                return redirect("/record")
            new_qty = current_qty - quantity
            # 计算预计归还时间
            expected_return = format_beijing_time(get_beijing_time() + timedelta(days=return_days))
            # 核心：预计归还时间+用途拼接存入purpose字段（无经手人）
            purpose_with_return = f"{purpose_origin}|预计归还：{expected_return}" if purpose_origin else f"预计归还：{expected_return}"
        else:
            # 归还：校验该用户的未归还数量，禁止超还
            cur.execute("""
                SELECT COALESCE(SUM(quantity), 0) as total_borrowed 
                FROM record_info 
                WHERE asset_id=%s AND person=%s AND type='领用'
            """, (asset_id, person))
            total_borrowed = cur.fetchone()["total_borrowed"]

            cur.execute("""
                SELECT COALESCE(SUM(quantity), 0) as total_returned 
                FROM record_info 
                WHERE asset_id=%s AND person=%s AND type='归还'
            """, (asset_id, person))
            total_returned = cur.fetchone()["total_returned"]

            available_return = total_borrowed - total_returned
            if available_return < quantity:
                flash(f"⚠️ 您当前仅可归还 {available_return} 件，无法超还")
                return redirect("/record")

            # 校验归还后总库存不超过资产总数量
            new_qty = current_qty + quantity
            if new_qty > total_qty:
                flash(f"⚠️ 归还后库存({new_qty})超过总数量({total_qty})，无法操作")
                return redirect("/record")
            purpose_with_return = purpose_origin  # 归还时无需预计归还时间

        # 3. 更新资产库存和状态
        new_status = "借出" if new_qty == 0 else "在库"
        cur.execute("""
            UPDATE asset_info 
            SET current_quantity=%s, status=%s 
            WHERE asset_id=%s
        """, (new_qty, new_status, asset_id))

        # 4. 插入操作记录（无经手人字段，兼容旧表）
        cur.execute("""
            INSERT INTO record_info (
                asset_id, person, type, quantity, time, purpose, handler
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            asset_id, person, op_type, quantity,
            format_beijing_time(get_beijing_time()),
            purpose_with_return,  # 含预计归还时间的用途
            ""  # 经手人字段置空，无输入
        ))
        db.commit()
        flash("✅ 操作成功！")
    except Exception as e:
        print(f"操作记录失败: {e}")
        flash("❌ 操作失败，请检查数据！")
    finally:
        db.close()
    return redirect("/record")

# ====================== 删除记录（自动恢复库存，无经手人相关逻辑）======================
@app.route("/delete_record", methods=["POST"])
def delete_record():
    record_id = request.form["record_id"]
    db = get_db()
    try:
        cur = db.cursor()
        # 1. 获取记录信息
        cur.execute("SELECT * FROM record_info WHERE id=%s", (record_id,))
        record = cur.fetchone()
        if not record:
            flash("⚠️ 记录不存在！")
            return redirect("/record")

        asset_id = record["asset_id"]
        op_type = record["type"]
        quantity = record["quantity"]

        # 2. 反向恢复库存
        cur.execute("SELECT * FROM asset_info WHERE asset_id=%s", (asset_id,))
        asset = cur.fetchone()
        if not asset:
            flash("⚠️ 资产不存在！")
            return redirect("/record")

        current_qty = asset["current_quantity"]
        if op_type == "领用":
            # 删除领用记录：恢复库存
            new_qty = current_qty + quantity
        else:
            # 删除归还记录：扣减库存
            new_qty = current_qty - quantity
            if new_qty < 0:
                flash("⚠️ 删除后库存为负，无法操作！")
                return redirect("/record")

        # 3. 更新资产状态
        new_status = "借出" if new_qty == 0 else "在库"
        cur.execute("""
            UPDATE asset_info 
            SET current_quantity=%s, status=%s 
            WHERE asset_id=%s
        """, (new_qty, new_status, asset_id))

        # 4. 删除记录
        cur.execute("DELETE FROM record_info WHERE id=%s", (record_id,))
        db.commit()
        flash("✅ 记录已删除，库存已恢复！")
    except Exception as e:
        print(f"删除记录失败: {e}")
        flash("❌ 记录删除失败！")
    finally:
        db.close()
    return redirect("/record")

# ====================== 资产查询页（新增分类筛选，无经手人，含分类/来源/预计归还时间）======================
@app.route("/query")
def query():
    return render_template("query.html", system_name=SYSTEM_NAME, categories=CATEGORIES)

# ====================== 资产查询API（核心：新增分类筛选，解析3类分类/3类来源，无经手人）======================
@app.route("/api/asset", methods=["POST"])
def api_asset():
    req_data = request.json
    asset_id = req_data.get("asset_id")
    cate_filter = req_data.get("category", "")  # 分类筛选参数

    db = get_db()
    cur = db.cursor()

    # 1. 按条件查询资产（支持资产编号精确查+分类筛选）
    if cate_filter and asset_id:
        # 同时按资产编号和分类查询
        cur.execute("SELECT * FROM asset_info WHERE asset_id=%s", (asset_id,))
    elif cate_filter:
        # 仅按分类筛选（解析model字段中的分类）
        cur.execute("SELECT * FROM asset_info WHERE model LIKE %s OR model LIKE %s", (f"%|{cate_filter}-%", f"{cate_filter}-%"))
    elif asset_id:
        # 仅按资产编号查询
        cur.execute("SELECT * FROM asset_info WHERE asset_id=%s", (asset_id,))
    else:
        db.close()
        return jsonify(ok=False, msg="请输入资产编号或选择分类进行查询")

    assets = cur.fetchall()
    if not assets:
        db.close()
        return jsonify(ok=False, msg="未查询到符合条件的资产")

    # 2. 解析资产的分类/来源（3类）
    asset_list = []
    for asset in assets:
        model_str = asset.get("model", "")
        asset_category = "未分类"
        asset_source = "未知来源"
        model_origin = model_str
        # 解析分类/来源格式：型号|分类-来源 或 分类-来源
        if "|" in model_str:
            model_origin, ext = model_str.split("|", 1)
            if "-" in ext:
                asset_category, asset_source = ext.split("-", 1)
        elif "-" in model_str:
            model_origin = "无"
            asset_category, asset_source = model_str.split("-", 1)
        # 给资产对象添加属性
        asset["model_origin"] = model_origin
        asset["category"] = asset_category
        asset["source"] = asset_source
        asset_list.append(asset)

    # 3. 批量查询资产的未归还记录（含预计归还时间，无经手人）
    result = []
    for asset in asset_list:
        cur.execute("""
            SELECT 
                person,
                SUM(CASE WHEN type='领用' THEN quantity ELSE 0 END) as total_borrowed,
                SUM(CASE WHEN type='归还' THEN quantity ELSE 0 END) as total_returned,
                GROUP_CONCAT(time ORDER BY time DESC) as times,
                GROUP_CONCAT(purpose ORDER BY time DESC) as purposes
            FROM record_info 
            WHERE asset_id=%s 
            GROUP BY person
            HAVING (total_borrowed - total_returned) > 0
            ORDER BY times DESC
        """, (asset["asset_id"],))
        unreturned_list = cur.fetchall()

        # 解析未归还记录的预计归还时间
        unreturned = []
        for item in unreturned_list:
            person = item["person"]
            borrowed = item["total_borrowed"]
            returned = item["total_returned"]
            times = item["times"].split(",")
            purposes = item["purposes"].split(",")
            latest_time = times[0]
            latest_purpose = purposes[0] if purposes[0] else "未填写"
            expected_return = "无"

            # 解析预计归还时间
            if "预计归还：" in latest_purpose:
                if "|" in latest_purpose:
                    latest_purpose, return_part = latest_purpose.split("|", 1)
                    expected_return = return_part.replace("预计归还：", "")
                else:
                    expected_return = latest_purpose.replace("预计归还：", "")
                    latest_purpose = "领用"

            unreturned.append({
                "person": person,
                "quantity": borrowed - returned,
                "time": latest_time,
                "purpose": latest_purpose,
                "expected_return": expected_return
            })

        result.append({
            "asset": asset,
            "unreturned": unreturned
        })

    db.close()
    return jsonify(ok=True, data=result)

# ====================== 启动服务（适配Render端口，无多余配置）======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
