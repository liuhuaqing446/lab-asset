from flask import Flask, render_template, request, flash, redirect, url_for, session, jsonify
import pymysql
from datetime import datetime

# 完全按张部长给的信息修正，100%正确
DB_CONFIG = {
    "host": "rm-bp1084h4bg6153o8veo.mysql.rds.aliyuncs.com",
    "port": 60030,  # 修正端口！
    "user": "amsaccount",
    "password": "123Qwe$$",
    "db": "amsdb",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

ADMIN_USER = "admin"
ADMIN_PWD = "lab123456"

app = Flask(__name__)
app.secret_key = "lab_asset_2026"

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
    return render_template("login.html")

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
    return render_template("index.html", assets=assets)

@app.route("/add_asset", methods=["POST"])
def add_asset():
    d = request.form
    db = get_db()
    try:
        db.cursor().execute("""
            INSERT INTO asset_info (asset_id,name,model,purchase_time,location,total_quantity,current_quantity)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (d["asset_id"],d["name"],d.get("model"),d.get("purchase_time"),d.get("location"),int(d.get("total_quantity",1)),int(d.get("total_quantity",1))))
        db.commit()
    except Exception as e:
        print(f"Add asset error: {e}")
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
    return render_template("record.html", records=records)

@app.route("/do_record", methods=["POST"])
def do_record():
    d = request.form
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT current_quantity FROM asset_info WHERE asset_id=%s", (d["asset_id"],))
        asset = cur.fetchone()
        if not asset:
            return redirect("/record")
        qty = int(d["quantity"])
        current = asset["current_quantity"]
        if d["type"]=="领用":
            if current < qty:
                return redirect("/record")
            new_q = current - qty
        else:
            new_q = current + qty
        cur.execute("UPDATE asset_info SET current_quantity=%s, status=%s WHERE asset_id=%s",
                    (new_q, "借出" if new_q == 0 else "在库", d["asset_id"]))
        cur.execute("""
            INSERT INTO record_info (asset_id,person,type,quantity,time,purpose,handler)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (d["asset_id"],d["person"],d["type"],qty,datetime.now().strftime("%Y-%m-%d %H:%M:%S"),d.get("purpose"),d.get("handler")))
        db.commit()
    except Exception as e:
        print(f"Do record error: {e}")
    finally:
        db.close()
    return redirect("/record")

@app.route("/query")
def query():
    return render_template("query.html")

@app.route("/api/asset", methods=["POST"])
def api_asset():
    aid = request.json["asset_id"]
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM asset_info WHERE asset_id=%s", (aid,))
    asset = cur.fetchone()
    if not asset:
        return jsonify({"ok":False})
    cur.execute("SELECT * FROM record_info WHERE asset_id=%s AND type='领用'", (aid,))
    unreturned = cur.fetchall()
    db.close()
    return jsonify({"ok":True, asset=asset, unreturned=unreturned})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=False)