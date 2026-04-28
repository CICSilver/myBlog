from flask import Blueprint, Flask, render_template, redirect, url_for, request, make_response, jsonify
from datetime import datetime
from app.database import DatabaseHelper, Blog
import json
import hashlib
# from app import db

admin_device_id = set()
main = Blueprint('main', __name__)
dbHelper = DatabaseHelper()
SITE_NAME = "Silver's Blog"
PERSONAL_INTRO = "人事匆匆，或许有些可以留在这里。"
# ========================= 辅助函数 =========================
def hash_string(input: str):
    sha256 = hashlib.sha256()
    sha256.update(input.encode('utf-8'))
    return sha256.hexdigest() # 返回十六进制哈希值

def get_site_context():
    return {
        "site_name": SITE_NAME,
        "personal_intro": PERSONAL_INTRO,
    }

def init_index_with_blogs(_blogs):
    categories = dbHelper.get_all_categories()
    dateList = dbHelper.get_all_date()
    return render_template(
        'index.html',
        blogs=_blogs,
        categories=categories,
        dateList=dateList,
        **get_site_context(),
    )

# =========================== 路由 ===========================
@main.route('/')
def index():
    return init_index_with_blogs(dbHelper.get_recent_blogs())

@main.route('/edit', methods=['GET', 'POST'])
def edit_blog():
    if request.method == 'POST':
        blog = Blog()
        blog.html_title = request.form['html-title']
        blog.title = request.form['title']
        blog.content = request.form['content']
        blog.category = request.form['category']
        if request.form['month'] != '':
            blog.month = request.form['month']
        if request.form['year'] != '':
            blog.year = request.form['year']
        if request.form['date'] != '':
            blog.date = request.form['date']
        if request.form['time'] != '':
            blog.time = request.form['time']

        action = request.form.get('action')

        response = {"status":"default_failed", "message":"操作失败"}
        if action == "update":
            # 更新博客
            response = dbHelper.update_blog(blog)
        elif action == "insert":
            # 插入新博客
            response = dbHelper.insert_blog(blog)
        elif action == "insert_new":
            # 有重复情况，修改html_title后插入新博客
            index = blog.html_title.rfind('_')
            index = 1 if index == -1 else index + 1
            blog.html_title = f"{blog.html_title}_{index}"
            response = dbHelper.insert_blog(blog)

        return response
    
    categories = dbHelper.get_all_categories()
    return render_template(
        'edit.html',
        blog=None,
        blog_content=None,
        categories=categories,
        **get_site_context(),
    )

@main.route('/<int:year>/<int:month>/<string:html_title>')
def blog_detail(year, month, html_title):
    # 根据年月和标题获取博客内容
    blog = dbHelper.get_specify_blog(str(year), str(month), html_title)
    
    if blog:
        return render_template('blog_detail.html', blog=blog, **get_site_context())
    else:
        return render_template('404.html', **get_site_context()), 404

@main.route('/manage')
def blog_manage():
    """
    博客管理页面
    """
    blogs = dbHelper.get_all_blogs()
    return render_template('manage.html', blogs=blogs, **get_site_context())

@main.route('/edit/<string:year>/<string:month>/<string:html_title>')
def manage_edit_blog(year, month, html_title):
    blog = dbHelper.get_specify_blog(year, month, html_title)
    if blog is None:
        return render_template('404.html', **get_site_context()), 404
    
    blog_content = json.dumps(blog.content)
    categories = dbHelper.get_all_categories()
    return render_template(
        'edit.html',
        blog=blog,
        blog_content=blog_content,
        categories=categories,
        **get_site_context(),
    )

@main.route('/delete/<string:year>/<string:month>/<string:html_title>')
def manage_delete_blog(year, month, html_title):
    blog = dbHelper.get_specify_blog(year, month, html_title)
    if blog is None:
        return render_template('404.html', **get_site_context()), 404
    
    return dbHelper.delete_blog(blog)  # 删除博客

@main.route('/register')
def register():
    return render_template('register.html', **get_site_context())

@main.route('/register_device', methods=['GET', 'POST'])
def register_device():
    """
    管理员设备注册
    """
    data = request.get_json()
    device_id = data.get('device_id')
    print(device_id)
    if not device_id:
        return jsonify({"status": "error", "message": "缺少设备ID"}), 400
    response = dbHelper.insert_device_id(device_id)
    return response

@main.route('/verify_device', methods=['POST'])
def admin_verify():
    """
    机器验证
    """
    data = request.get_json()
    device_id = data.get('device_id')

    if not device_id:
        return jsonify({"status": "error", "message": "缺少设备ID"}), 400
    
    response = dbHelper.check_device_id(device_id)
    if response:
        return jsonify({"status": "success", "message": "设备验证成功"})
    else:
        return jsonify({"status": "failed", "message": "设备验证失败"})
    
@main.route('/logout', methods=['POST'])
def logout():
    """
    注销设备
    """
    data = request.get_json()
    device_id = data.get('device_id')
    
    if not device_id:
        return jsonify({"status": "error", "message": "缺少设备ID"}), 400
    
    return dbHelper.delete_device_id(device_id)

    

@main.route('/categorized_blogs/<string:categoryName>')
def categorized_blogs(categoryName):
    blogs = dbHelper.get_blogs_by_category(categoryName)
    # 按最新时间排序blogs
    blogs.reverse()    
    return init_index_with_blogs(blogs)

@main.route('/date_blogs/<string:year>/<string:month>')
def archived_blogs(year, month):
    blogs = dbHelper.get_blogs_by_date(year, month)
    blogs.reverse()  # 按最新时间排序blogs
    return init_index_with_blogs(blogs)

# 添加评论
def add_comment(blog_id, comment):
    pass
