from flask import Flask, render_template, request, redirect, url_for, session, flash
import pymysql
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # 请替换为自己的密钥

# 数据库配置（请根据你的实际数据库信息修改）
db = pymysql.connect(
    host='localhost',
    user='root',
    password='your_password',
    database='lab_asset',
    charset='utf8mb4'
)

SYSTEM_NAME = "AEIM实验室管理系统"

# ========== 登录相关 ==========
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # 简单验证（可替换为数据库验证）
        if username == 'admin' and password == 'admin':
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误')
    return render_template('login.html', system_name=SYSTEM_NAME)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# ========== 资产列表页 ==========
@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    cursor = db.cursor()
    # 查询资产
    cursor.execute("SELECT asset_id, name, model, category, source, purchase_time, location, total_quantity, current_quantity, status FROM assets")
    assets_data = cursor.fetchall()
    assets = []
    for asset in assets_data:
        model_str = asset[2] or ''
        model_origin = model_str
        cate = asset[3] or '未分类'
        src = asset[4] or '未知来源'
        # 兼容旧数据格式
        if '|' in model_str:
            parts = model_str.split('|', 1)
            model_origin = parts[0]
            if '-' in parts[1]:
                cate, src = parts[1].split('-', 1)
        elif '-' in model_str:
            cate, src = model_str.split('-', 1)
            model_origin = '无'
        assets.append({
            'asset_id': asset[0],
            'name': asset[1],
            'model': model_str,
            'model_origin': model_origin,
            'category': cate,
            'source': src,
            'purchase_time': asset[5],
            'location': asset[6],
            'total_quantity': asset[7],
            'current_quantity': asset[8],
            'status': asset[9]
        })
    # 查询分类和来源
    cursor.execute("SELECT DISTINCT category FROM assets")
    categories = [row[0] for row in cursor.fetchall() if row[0]]
    if not categories:
        categories = ['机械类', '电气类', '其他类']
    cursor.execute("SELECT DISTINCT source FROM assets")
    sources = [row[0] for row in cursor.fetchall() if row[0]]
    if not sources:
        sources = ['自购', '企业', '学校']
    return render_template('index.html', system_name=SYSTEM_NAME, assets=assets, categories=categories, sources=sources)

@app.route('/add_asset', methods=['POST'])
def add_asset():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    asset_id = request.form['asset_id']
    name = request.form['name']
    model = request.form['model']
    category = request.form['category']
    source = request.form['source']
    purchase_time = request.form['purchase_time'] or None
    location = request.form['location']
    total_quantity = int(request.form['total_quantity'])
    
    cursor = db.cursor()
    # 检查资产编号是否已存在
    cursor.execute("SELECT asset_id FROM assets WHERE asset_id = %s", (asset_id,))
    if cursor.fetchone():
        flash('资产编号已存在！')
        return redirect(url_for('index'))
    # 插入新资产
    cursor.execute(
        "INSERT INTO assets (asset_id, name, model, category, source, purchase_time, location, total_quantity, current_quantity, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (asset_id, name, model, category, source, purchase_time, location, total_quantity, total_quantity, '在库')
    )
    db.commit()
    flash('资产新增成功！')
    return redirect(url_for('index'))

@app.route('/delete_asset', methods=['POST'])
def delete_asset():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    asset_id = request.form['asset_id']
    cursor = db.cursor()
    # 删除资产相关记录
    cursor.execute("DELETE FROM records WHERE asset_id = %s", (asset_id,))
    # 删除资产
    cursor.execute("DELETE FROM assets WHERE asset_id = %s", (asset_id,))
    db.commit()
    flash('资产删除成功！')
    return redirect(url_for('index'))

# ========== 出入记录页（核心修复） ==========
@app.route('/record')
def record():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    cursor = db.cursor()
    # 1. 查询所有资产，用于模板匹配
    cursor.execute("SELECT asset_id, name, model FROM assets")
    assets_data = cursor.fetchall()
    assets = []
    for asset in assets_data:
        model_str = asset[2] or ''
        model_origin = model_str
        if '|' in model_str:
            parts = model_str.split('|', 1)
            model_origin = parts[0]
        elif '-' in model_str:
            model_origin = model_str.split('-')[0]
        assets.append({
            'asset_id': str(asset[0]),  # 统一字符串，避免类型不匹配
            'name': asset[1],
            'model_origin': model_origin or '无'
        })
    
    # 2. 查询所有出入记录
    cursor.execute("SELECT id, asset_id, person, type, quantity, time, purpose FROM records ORDER BY id DESC")
    records_data = cursor.fetchall()
    records = []
    for r in records_data:
        records.append({
            'id': r[0],
            'asset_id': str(r[1]),  # 统一字符串
            'person': r[2],
            'type': r[3],
            'quantity': r[4],
            'time': r[5],
            'purpose': r[6]
        })
    
    return render_template('record.html', system_name=SYSTEM_NAME, records=records, assets=assets)

@app.route('/do_record', methods=['POST'])
def do_record():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    asset_id = request.form['asset_id']
    person = request.form['person']
    op_type = request.form['type']
    quantity = int(request.form['quantity'])
    
    cursor = db.cursor()
    # 校验资产存在
    cursor.execute("SELECT current_quantity, total_quantity FROM assets WHERE asset_id = %s", (asset_id,))
    asset = cursor.fetchone()
    if not asset:
        flash('资产不存在！')
        return redirect(url_for('record'))
    
    current_qty, total_qty = asset[0], asset[1]
    
    if op_type == '领用':
        if current_qty < quantity:
            flash('库存不足，无法领用！')
            return redirect(url_for('record'))
        return_days = int(request.form['return_days'])
        purpose = request.form['purpose'] or '未填写'
        # 计算预计归还时间
        return_time = (datetime.now() + timedelta(days=return_days)).strftime('%Y-%m-%d %H:%M:%S')
        purpose_str = f"{purpose}|预计归还：{return_time}"
        # 更新库存和状态
        new_qty = current_qty - quantity
        new_status = '借出' if new_qty == 0 else '在库'
        cursor.execute("UPDATE assets SET current_quantity = %s, status = %s WHERE asset_id = %s", (new_qty, new_status, asset_id))
    else:
        # 归还操作
        device_status = request.form['device_status']
        purpose_str = f"设备状态：{device_status}"
        # 更新库存和状态
        new_qty = current_qty + quantity
        new_status = '在库'
        cursor.execute("UPDATE assets SET current_quantity = %s, status = %s WHERE asset_id = %s", (new_qty, new_status, asset_id))
    
    # 插入记录
    now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute(
        "INSERT INTO records (asset_id, person, type, quantity, time, purpose) VALUES (%s, %s, %s, %s, %s, %s)",
        (asset_id, person, op_type, quantity, now_time, purpose_str)
    )
    db.commit()
    flash('操作成功！')
    return redirect(url_for('record'))

@app.route('/delete_record', methods=['POST'])
def delete_record():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    record_id = request.form['record_id']
    
    cursor = db.cursor()
    # 查询记录信息，恢复库存
    cursor.execute("SELECT asset_id, type, quantity FROM records WHERE id = %s", (record_id,))
    record = cursor.fetchone()
    if not record:
        flash('记录不存在！')
        return redirect(url_for('record'))
    
    asset_id, op_type, quantity = record[0], record[1], record[2]
    cursor.execute("SELECT current_quantity, total_quantity FROM assets WHERE asset_id = %s", (asset_id,))
    asset = cursor.fetchone()
    if asset:
        current_qty, total_qty = asset[0], asset[1]
        if op_type == '领用':
            # 领用记录删除，恢复库存
            new_qty = current_qty + quantity
        else:
            # 归还记录删除，扣回库存
            new_qty = current_qty - quantity
        new_status = '在库' if new_qty > 0 else '借出'
        cursor.execute("UPDATE assets SET current_quantity = %s, status = %s WHERE asset_id = %s", (new_qty, new_status, asset_id))
    
    # 删除记录
    cursor.execute("DELETE FROM records WHERE id = %s", (record_id,))
    db.commit()
    flash('记录删除成功！')
    return redirect(url_for('record'))

# ========== 资产查询页 ==========
@app.route('/query')
def query():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    cursor = db.cursor()
    cursor.execute("SELECT DISTINCT category FROM assets")
    categories = [row[0] for row in cursor.fetchall() if row[0]]
    return render_template('query.html', system_name=SYSTEM_NAME, categories=categories)

@app.route('/api/asset', methods=['POST'])
def api_asset():
    if not session.get('logged_in'):
        return {'error': '未登录'}, 401
    search_key = request.json.get('search_key', '')
    category = request.json.get('category', '')
    
    cursor = db.cursor()
    sql = "SELECT asset_id, name, model, category, source, purchase_time, location, total_quantity, current_quantity, status FROM assets WHERE 1=1"
    params = []
    if search_key:
        sql += " AND (asset_id LIKE %s OR name LIKE %s)"
        params.extend([f"%{search_key}%", f"%{search_key}%"])
    if category:
        sql += " AND category = %s"
        params.append(category)
    
    cursor.execute(sql, params)
    assets_data = cursor.fetchall()
    assets = []
    for asset in assets_data:
        model_str = asset[2] or ''
        model_origin = model_str
        if '|' in model_str:
            parts = model_str.split('|', 1)
            model_origin = parts[0]
        elif '-' in model_str:
            model_origin = model_str.split('-')[0]
        # 查询未归还记录
        cursor.execute("SELECT person, quantity, time, purpose FROM records WHERE asset_id = %s AND type = '领用' AND purpose LIKE '%|预计归还%' ORDER BY time DESC", (asset[0],))
        unreturned = []
        for r in cursor.fetchall():
            purpose = r[3]
            if '|' in purpose:
                parts = purpose.split('|', 1)
                return_time = parts[1].replace('预计归还：', '').strip()
                unreturned.append({
                    'person': r[0],
                    'quantity': r[1],
                    'time': r[2],
                    'purpose': parts[0].strip(),
                    'expected_return': return_time
                })
        assets.append({
            'asset_id': asset[0],
            'name': asset[1],
            'model_origin': model_origin or '无',
            'category': asset[3],
            'source': asset[4],
            'purchase_time': asset[5],
            'location': asset[6],
            'total_quantity': asset[7],
            'current_quantity': asset[8],
            'status': asset[9],
            'unreturned': unreturned
        })
    return {'data': assets}, 200

if __name__ == '__main__':
    app.run(debug=True)
