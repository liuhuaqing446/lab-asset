from flask import Flask, render_template, request, flash, redirect, session, jsonify
import pymysql
from datetime import datetime, timedelta
import os

# 数据库配置
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

app = Flask(__name__)
app.secret_key = "lab_asset_2026_secure_v2"

# 获取北京时间（UTC+8）
def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

# 格式化北京时间为字符串
def format_beijing_time(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# 数据库连接
def get_db():
    return pymysql.connect(**DB_CONFIG)

# 登录校验
@app.before_request
def check_login():
    if request.path in ["/login"]:
        return
    if not session.get("login"):
        return redirect("/login")

# 登录页
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]
        if u == ADMIN_USER and p == ADMIN_PWD:
            session["login"] = True
            return redirect("/")
        flash("账号密码错误")
    return render_template("login.html", system_name=SYSTEM_NAME)

# 退出登录
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# 资产列表页
@app.route("/")
def index():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM asset_info ORDER BY asset_id")
    assets = cur.fetchall()
    db.close()
    return render_template("index.html", assets=assets, system_name=SYSTEM_NAME)

# 新增资产
@app.route("/add_asset", methods=["POST"])
def add_asset():
    d = request.form
    if not d.get("asset_id") or not d.get("name"):
        flash("资产编号和名称为必填项！")
        return redirect("/")
    
    db = get_db()
    try:
        cur = db.cursor()
        # 检查编号是否重复
        cur.execute("SELECT asset_id FROM asset_info WHERE asset_id=%s", (d["asset_id"],))
        if cur.fetchone():
            flash("资产编号已存在！")
            return redirect("/")
        
        # 插入新资产
        cur.execute("""
            INSERT INTO asset_info (asset_id,name,model,purchase_time,location,total_quantity,current_quantity,status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            d["asset_id"], d["name"], d.get("model",""),
            d.get("purchase_time", get_beijing_time().strftime("%Y-%m-%d")),
            d.get("location",""),
            int(d.get("total_quantity",1)),
            int(d.get("total_quantity",1)),
            "在库"
        ))
        db.commit()
        flash("添加成功")
    except Exception as e:
        print(f"添加失败: {e}")
        flash("添加失败")
    finally:
        db.close()
    return redirect("/")

# 删除资产
@app.route("/delete_asset", methods=["POST"])
def delete_asset():
    aid = request.form["asset_id"]
    db = get_db()
    try:
        cur = db.cursor()
        # 先删除关联记录，再删除资产
        cur.execute("DELETE FROM record_info WHERE asset_id=%s", (aid,))
        cur.execute("DELETE FROM asset_info WHERE asset_id=%s", (aid,))
        db.commit()
        flash("删除成功")
    except Exception as e:
        print(f"删除失败: {e}")
        flash("删除失败")
    finally:
        db.close()
    return redirect("/")

# 出入记录页
@app.route("/record")
def record():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM record_info ORDER BY time DESC")
    records = cur.fetchall()
    db.close()
    return render_template("record.html", records=records, system_name=SYSTEM_NAME)

# 提交出入记录（核心逻辑：多用户独立+数量校验+北京时间）
@app.route("/do_record", methods=["POST"])
def do_record():
    d = request.form
    # 基础校验
    if not d.get("asset_id") or not d.get("person") or not d.get("quantity"):
        flash("必填项不能为空")
        return redirect("/record")
    
    asset_id = d["asset_id"]
    person = d["person"].strip()
    op_type = d["type"]
    quantity = int(d["quantity"])
    
    db = get_db()
    try:
        cur = db.cursor()
        # 1. 检查资产是否存在
        cur.execute("SELECT * FROM asset_info WHERE asset_id=%s", (asset_id,))
        asset = cur.fetchone()
        if not asset:
            flash("资产不存在")
            return redirect("/record")
        
        current_qty = asset["current_quantity"]
        total_qty = asset["total_quantity"]
        
        # 2. 领用/归还逻辑校验（多用户独立）
        if op_type == "领用":
            # 领用：校验资产总库存是否充足
            if current_qty < quantity:
                flash("库存不足，无法领用")
                return redirect("/record")
            new_qty = current_qty - quantity
        else:
            # 归还：校验该用户的未归还数量，禁止超还
            # 计算该用户累计领用数量
            cur.execute("""
                SELECT COALESCE(SUM(quantity), 0) as total_borrowed 
                FROM record_info 
                WHERE asset_id=%s AND person=%s AND type='领用'
            """, (asset_id, person))
            total_borrowed = cur.fetchone()["total_borrowed"]
            
            # 计算该用户累计归还数量
            cur.execute("""
                SELECT COALESCE(SUM(quantity), 0) as total_returned 
                FROM record_info 
                WHERE asset_id=%s AND person=%s AND type='归还'
            """, (asset_id, person))
            total_returned = cur.fetchone()["total_returned"]
            
            # 计算可归还数量
            available_return = total_borrowed - total_returned
            if available_return < quantity:
                flash(f"您当前仅可归还 {available_return} 件，无法超还")
                return redirect("/record")
            
            # 校验归还后资产总库存不超过总数量
            new_qty = current_qty + quantity
            if new_qty > total_qty:
                flash("归还数量超过资产总数量，无法操作")
                return redirect("/record")
        
        # 3. 更新资产库存和状态
        new_status = "借出" if new_qty == 0 else "在库"
        cur.execute("""
            UPDATE asset_info 
            SET current_quantity=%s, status=%s 
            WHERE asset_id=%s
        """, (new_qty, new_status, asset_id))
        
        # 4. 插入操作记录（北京时间）
        cur.execute("""
            INSERT INTO record_info (asset_id,person,type,quantity,time,purpose,handler)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            asset_id, person, op_type, quantity,
            format_beijing_time(get_beijing_time()),
            d.get("purpose",""), d.get("handler","")
        ))
        db.commit()
        flash("操作成功")
    except Exception as e:
        print(f"操作失败: {e}")
        flash("操作失败")
    finally:
        db.close()
    return redirect("/record")

# 删除记录（逻辑修复：反向恢复库存+多用户校验）
@app.route("/delete_record", methods=["POST"])
def delete_record():
    rid = request.form["record_id"]
    db = get_db()
    try:
        cur = db.cursor()
        # 1. 获取记录信息
        cur.execute("SELECT * FROM record_info WHERE id=%s", (rid,))
        r = cur.fetchone()
        if not r:
            flash("记录不存在")
            return redirect("/record")
        
        asset_id = r["asset_id"]
        op_type = r["type"]
        quantity = r["quantity"]
        person = r["person"]
        
        # 2. 反向恢复库存
        cur.execute("SELECT * FROM asset_info WHERE asset_id=%s", (asset_id,))
        asset = cur.fetchone()
        if not asset:
            flash("资产不存在")
            return redirect("/record")
        
        current_qty = asset["current_quantity"]
        total_qty = asset["total_quantity"]
        
        if op_type == "领用":
            # 删除领用记录：恢复库存
            new_qty = current_qty + quantity
        else:
            # 删除归还记录：扣减库存
            new_qty = current_qty - quantity
            if new_qty < 0:
                flash("删除后库存为负，无法操作")
                return redirect("/record")
        
        # 3. 更新资产状态
        new_status = "借出" if new_qty == 0 else "在库"
        cur.execute("""
            UPDATE asset_info 
            SET current_quantity=%s, status=%s 
            WHERE asset_id=%s
        """, (new_qty, new_status, asset_id))
        
        # 4. 删除记录
        cur.execute("DELETE FROM record_info WHERE id=%s", (rid,))
        db.commit()
        flash("记录已删除，库存已恢复")
    except Exception as e:
        print(f"删除失败: {e}")
        flash("删除失败")
    finally:
        db.close()
    return redirect("/record")

# 资产查询页
@app.route("/query")
def query():
    return render_template("query.html", system_name=SYSTEM_NAME)

# 资产查询API（核心逻辑：多用户未归还计算+北京时间）
@app.route("/api/asset", methods=["POST"])
def api_asset():
    aid = request.json["asset_id"]
    db = get_db()
    cur = db.cursor()
    
    # 1. 获取资产信息
    cur.execute("SELECT * FROM asset_info WHERE asset_id=%s", (aid,))
    asset = cur.fetchone()
    if not asset:
        db.close()
        return jsonify(ok=False)
    
    # 2. 计算每个用户的未归还记录（多用户独立）
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
    """, (aid,))
    unreturned_list = cur.fetchall()
    
    # 3. 格式化未归还记录（北京时间，按用户分组）
    unreturned = []
    for item in unreturned_list:
        person = item["person"]
        borrowed = item["total_borrowed"]
        returned = item["total_returned"]
        times = item["times"].split(",")
        purposes = item["purposes"].split(",")
        
        # 直接使用存储的北京时间
        latest_time = times[0]
        
        unreturned.append({
            "person": person,
            "quantity": borrowed - returned,
            "time": latest_time,
            "purpose": purposes[0] if purposes[0] else "未填写"
        })
    
    db.close()
    return jsonify(
        ok=True,
        asset=asset,
        unreturned=unreturned
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
