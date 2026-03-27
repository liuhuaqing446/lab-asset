from flask import Flask, render_template, request, flash, redirect, session, jsonify
import pymysql
from datetime import datetime, timedelta
import os

DB_CONFIG = {
    "host": "rm-bp1084h4bg6153o8veo.mysql.rds.aliyuncs.com",
    "port": 60030,
    "user": "amsaccount",
    "password": "123Qwe$$",
    "db": "amsdb",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

ADMIN_USER = "admin"
ADMIN_PWD = "lab123456"
SYSTEM_NAME = "AEIM实验室管理系统"

app = Flask(__name__)
app.secret_key = "lab_asset_2026"

def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

def get_db():
    return pymysql.connect(**DB_CONFIG)

@app.before_request
def check_login():
    if request.path in ["/login"]:
        return
    if not session.get("login"):
        return redirect("/login")

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

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/")
def index():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM asset_info ORDER BY asset_id")
    assets = cur.fetchall()
    db.close()
    return render_template("index.html", assets=assets, system_name=SYSTEM_NAME)

@app.route("/add_asset", methods=["POST"])
def add_asset():
    d = request.form
    if not d.get("asset_id") or not d.get("name"):
        flash("资产编号和名称为必填项！")
        return redirect("/")
    
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT asset_id FROM asset_info WHERE asset_id=%s", (d["asset_id"],))
        if cur.fetchone():
            flash("资产编号已存在！")
            return redirect("/")
        
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
    except:
        flash("添加失败")
    finally:
        db.close()
    return redirect("/")

@app.route("/delete_asset", methods=["POST"])
def delete_asset():
    aid = request.form["asset_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("DELETE FROM record_info WHERE asset_id=%s", (aid,))
        cur.execute("DELETE FROM asset_info WHERE asset_id=%s", (aid,))
        db.commit()
        flash("删除成功")
    except:
        flash("删除失败")
    finally:
        db.close()
    return redirect("/")

@app.route("/record")
def record():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM record_info ORDER BY time DESC")
    records = cur.fetchall()
    db.close()
    return render_template("record.html", records=records, system_name=SYSTEM_NAME)

@app.route("/do_record", methods=["POST"])
def do_record():
    d = request.form
    if not d.get("asset_id") or not d.get("person") or not d.get("quantity"):
        flash("必填项不能为空")
        return redirect("/record")
    
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT current_quantity FROM asset_info WHERE asset_id=%s", (d["asset_id"],))
        asset = cur.fetchone()
        if not asset:
            flash("资产不存在")
            return redirect("/record")
        
        qty = int(d["quantity"])
        current = asset["current_quantity"]
        op = d["type"]
        
        if op == "领用":
            if current < qty:
                flash("库存不足")
                return redirect("/record")
            new_q = current - qty
        else:
            new_q = current + qty
        
        cur.execute("UPDATE asset_info SET current_quantity=%s, status=%s WHERE asset_id=%s",
                    (new_q, "借出" if new_q == 0 else "在库", d["asset_id"]))
        
        cur.execute("""
            INSERT INTO record_info (asset_id,person,type,quantity,time,purpose,handler)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            d["asset_id"], d["person"], op, qty,
            get_beijing_time().strftime("%Y-%m-%d %H:%M:%S"),
            d.get("purpose",""), d.get("handler","")
        ))
        db.commit()
        flash("操作成功")
    except:
        flash("操作失败")
    finally:
        db.close()
    return redirect("/record")

@app.route("/delete_record", methods=["POST"])
def delete_record():
    rid = request.form["record_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT * FROM record_info WHERE id=%s", (rid,))
        r = cur.fetchone()
        if r:
            if r["type"] == "领用":
                cur.execute("UPDATE asset_info SET current_quantity = current_quantity + %s WHERE asset_id=%s",
                            (r["quantity"], r["asset_id"]))
            else:
                cur.execute("UPDATE asset_info SET current_quantity = current_quantity - %s WHERE asset_id=%s",
                            (r["quantity"], r["asset_id"]))
            cur.execute("DELETE FROM record_info WHERE id=%s", (rid,))
            db.commit()
            flash("记录已删除，库存已恢复")
    except:
        flash("删除失败")
    finally:
        db.close()
    return redirect("/record")

@app.route("/query")
def query():
    return render_template("query.html", system_name=SYSTEM_NAME)

@app.route("/api/asset", methods=["POST"])
def api_asset():
    aid = request.json["asset_id"]
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM asset_info WHERE asset_id=%s", (aid,))
    asset = cur.fetchone()
    if not asset:
        return jsonify(ok=False)
    cur.execute("SELECT * FROM record_info WHERE asset_id=%s ORDER BY time DESC", (aid,))
    records = cur.fetchall()
    db.close()
    return jsonify(ok=True, asset=asset, unreturned=records)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
