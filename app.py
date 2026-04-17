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
ADMIN_USER = "admin"
ADMIN_PWD = "lab123456"
SYSTEM_NAME = "AEIM实验室管理系统"
CATEGORIES = ["机械类", "电气类", "其他类"]
SOURCES = ["自购", "企业", "学校"]
DEFAULT_RETURN_DAYS = 1
# 定时唤醒配置
WAKE_UP_INTERVAL = 600
SELF_URL = os.environ.get('SELF_URL', 'https://lab-asset.onrender.com')

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
            VALUES (%s, %s, %s, %s, %s, %s, %s, '在库')
        """, (
            form_data["asset_id"], form_data["name"], model_with_ext, purchase_time,
            form_data.get("location", ""), int(form_data.get("total_quantity", 1)),
            int(form_data.get("total_quantity", 1))
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

# ==============================
# ✅ 核心修复：统一资产ID类型，彻底解决未知资产
# ==============================
@app.route("/record")
def record():
    db = get_db()
    cur = db.cursor()
    
    # 1. 加载资产，统一asset_id为字符串，解析型号
    cur.execute("SELECT asset_id, name, model FROM asset_info ORDER BY name")
    assets = cur.fetchall()
    # 用字典存储，key统一为字符串，方便匹配
    asset_map = {}
    for asset in assets:
        # 统一asset_id为字符串，解决数字/字符串不匹配问题
        aid = str(asset["asset_id"])
        model_str = asset.get("model", "")
        # 解析原始型号
        if "|" in model_str:
            model_origin = model_str.split("|")[0]
        elif "-" in model_str:
            model_origin = "无"
        else:
            model_origin = model_str
        asset_map[aid] = {
            "name": asset["name"],
            "model_origin": model_origin
        }
        # 同时保留数组，用于前端搜索
        asset["asset_id"] = aid
        asset["model_origin"] = model_origin

    # 2. 加载记录，统一asset_id为字符串
    cur.execute("SELECT * FROM record_info ORDER BY time DESC")
    records = cur.fetchall()
    for record in records:
        # 统一record的asset_id为字符串，和asset_map匹配
        record["asset_id"] = str(record["asset_id"])

    db.close()
    # 传递asset_map给模板，直接匹配，100%成功
    return render_template("record.html", records=records, system_name=SYSTEM_NAME, assets=assets, asset_map=asset_map)

# 提交出入记录（完全不动）
@app.route("/do_record", methods=["POST"])
def do_record():
    form_data = request.form
    required = ["asset_id", "person", "quantity", "type"]
    if form_data.get("type") == "领用" and not form_data.get("return_days"):
        form_data["return_days"] = str(DEFAULT_RETURN_DAYS)
    for key in required:
        if not form_data.get(key):
            flash(f"⚠️ {key}为必填项！")
            return redirect("/record")
    asset_id = form_data["asset_id"]
    person = form_data["person"].strip()
    op_type = form_data["type"]
    quantity = int(form_data["quantity"])
    return_days = int(form_data.get("return_days", DEFAULT_RETURN_DAYS)) if op_type == "领用" else 0
    purpose_origin = form_data.get("purpose", "")
    device_status = form_data.get("device_status", "正常") if op_type == "归还" else ""
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT * FROM asset_info WHERE asset_id=%s", (asset_id,))
        asset = cur.fetchone()
        if not asset:
            flash("⚠️ 资产不存在！")
            return redirect("/record")
        current_qty, total_qty = asset["current_quantity"], asset["total_quantity"]
        if op_type == "领用":
            if current_qty < quantity:
                flash(f"⚠️ 库存不足！当前剩余 {current_qty} 件，无法领用 {quantity} 件")
                return redirect("/record")
            new_qty = current_qty - quantity
            expected_return = format_beijing_time(get_beijing_time() + timedelta(days=return_days))
            purpose_with_return = f"{purpose_origin}|预计归还：{expected_return}" if purpose_origin else f"预计归还：{expected_return}"
        else:
            cur.execute("SELECT COALESCE(SUM(quantity),0) as total_borrowed FROM record_info WHERE asset_id=%s AND person=%s AND type='领用'", (asset_id, person))
            total_borrowed = cur.fetchone()["total_borrowed"]
            cur.execute("SELECT COALESCE(SUM(quantity),0) as total_returned FROM record_info WHERE asset_id=%s AND person=%s AND type='归还'", (asset_id, person))
            total_returned = cur.fetchone()["total_returned"]
            if (total_borrowed - total_returned) < quantity:
                flash(f"⚠️ 仅可归还 {total_borrowed - total_returned} 件，无法超还！")
                return redirect("/record")
            new_qty = current_qty + quantity
            if new_qty > total_qty:
                flash(f"⚠️ 归还后库存({new_qty})超过总数量({total_qty})！")
                return redirect("/record")
            purpose_with_return = f"设备状态：{device_status}"
        new_status = "借出" if new_qty == 0 else "在库"
        cur.execute("UPDATE asset_info SET current_quantity=%s, status=%s WHERE asset_id=%s", (new_qty, new_status, asset_id))
        cur.execute("""
            INSERT INTO record_info (asset_id, person, type, quantity, time, purpose, handler)
            VALUES (%s, %s, %s, %s, %s, %s, '')
        """, (asset_id, person, op_type, quantity, format_beijing_time(get_beijing_time()), purpose_with_return))
        db.commit()
        flash("✅ 操作成功！")
    except Exception as e:
        print(f"操作记录失败: {e}")
        flash("❌ 操作失败，请检查数据！")
    finally:
        db.close()
    return redirect("/record")

# 删除出入记录（完全不动）
@app.route("/delete_record", methods=["POST"])
def delete_record():
    record_id = request.form["record_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT * FROM record_info WHERE id=%s", (record_id,))
        record = cur.fetchone()
        if not record:
            flash("⚠️ 记录不存在！")
            return redirect("/record")
        asset_id, op_type, quantity = record["asset_id"], record["type"], record["quantity"]
        cur.execute("SELECT * FROM asset_info WHERE asset_id=%s", (asset_id,))
        asset = cur.fetchone()
        if not asset:
            flash("⚠️ 资产不存在！")
            return redirect("/record")
        current_qty = asset["current_quantity"]
        new_qty = current_qty + quantity if op_type == "领用" else current_qty - quantity
        if new_qty < 0:
            flash("⚠️ 删除后库存为负，无法操作！")
            return redirect("/record")
        new_status = "借出" if new_qty == 0 else "在库"
        cur.execute("UPDATE asset_info SET current_quantity=%s, status=%s WHERE asset_id=%s", (new_qty, new_status, asset_id))
        cur.execute("DELETE FROM record_info WHERE id=%s", (record_id,))
        db.commit()
        flash("✅ 记录删除成功，库存已恢复！")
    except Exception as e:
        print(f"删除记录失败: {e}")
        flash("❌ 记录删除失败！")
    finally:
        db.close()
    return redirect("/record")

# 查询页（完全不动）
@app.route("/query")
def query():
    return render_template("query.html", system_name=SYSTEM_NAME, categories=CATEGORIES)

# 查询API（完全不动）
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

# ==============================
# 新增功能：Excel 导入 / 导出（只新增，不修改任何代码）
# ==============================
import pandas as pd
from flask import send_file
import io

# 一键导入资产 Excel
@app.route("/import_assets", methods=["POST"])
def import_assets():
    if not session.get("login"):
        return redirect("/login")
    try:
        file = request.files["file"]
        df = pd.read_excel(file)

        # 🔴 关键修复：强制保留 Excel 原顺序，不被 pandas 打乱
        df = df.reset_index(drop=True)

        db = get_db()
        cur = db.cursor()

        for _, row in df.iterrows():
            asset_id = str(row["资产编号"]).strip()
            name = str(row["资产名称"]).strip()
            model = str(row["设备型号"]).strip()
            category = str(row["设备分类"]).strip()
            source = str(row["设备来源"]).strip()
            purchase_time = str(row["采购时间"]).strip() if not pd.isna(row["采购时间"]) else ""
            location = str(row["存放位置"]).strip() if not pd.isna(row["存放位置"]) else ""
            total_quantity = int(row["总数量"])

            cur.execute("SELECT asset_id FROM asset_info WHERE asset_id = %s", (asset_id,))
            if cur.fetchone():
                continue

            model_ext = f"{model}|{category}-{source}" if model else f"{category}-{source}"
            cur.execute("""
                INSERT INTO asset_info (asset_id, name, model, purchase_time, location, total_quantity, current_quantity, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, '在库')
            """, (asset_id, name, model_ext, purchase_time, location, total_quantity, total_quantity))

        db.commit()
        flash("✅ 一键导入完成！")
    except Exception as e:
        print("导入错误：", e)
        flash("❌ 导入失败，请检查Excel格式")
    return redirect("/")

# 一键导出资产 + 出入记录
@app.route("/export_all")
def export_all():
    if not session.get("login"):
        return redirect("/login")
    try:
        db = get_db()
        cur = db.cursor()

        cur.execute("SELECT * FROM asset_info")
        assets = cur.fetchall()
        asset_df = pd.DataFrame(assets)

        cur.execute("SELECT * FROM record_info")
        records = cur.fetchall()
        record_df = pd.DataFrame(records)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            asset_df.to_excel(writer, sheet_name="资产列表", index=False)
            record_df.to_excel(writer, sheet_name="出入记录", index=False)
        output.seek(0)

        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            download_name="实验室资产_出入记录.xlsx"
        )
    except Exception as e:
        print("导出错误：", e)
        flash("❌ 导出失败")
        return redirect("/query")

# 启动服务
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
