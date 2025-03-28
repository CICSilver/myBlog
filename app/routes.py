from flask import Blueprint, Flask, render_template, redirect, url_for, request, make_response
from datetime import datetime
from app.database import DatabaseHelper, Blog
import json
import hashlib
# from app import db

admin_key = "XYR_ADMIN_208236" # 管理员密钥
main = Blueprint('main', __name__)
dbHelper = DatabaseHelper()
# ========================= 辅助函数 =========================
def hash_string(input: str):
    sha256 = hashlib.sha256()
    sha256.update(input.encode('utf-8'))
    return sha256.hexdigest() # 返回十六进制哈希值

# =========================== 路由 ===========================
@main.route('/')
def index():
    site_name = "Silver's Blog"
    personal_intro = "人事匆匆，或许有些可以留在这里。"
    categories = dbHelper.get_all_categories()
    return render_template('index.html', blogs=dbHelper.get_recent_blogs(), site_name=site_name, personal_intro=personal_intro, categories=categories)

@main.route('/edit', methods=['GET', 'POST'])
def edit_blog():
    if request.method == 'POST':
        blog = Blog()
        blog.html_title = request.form['html-title']
        blog.title = request.form['title']
        blog.content = request.form['content']
        blog.category = request.form['category']

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
    return render_template('edit.html', blog=None, blog_content=None, categories=categories)

@main.route('/<int:year>/<int:month>/<string:html_title>')
def blog_detail(year, month, html_title):
    # 根据年月和标题获取博客内容
    blog = dbHelper.get_specify_blog(str(year), str(month), html_title)
    
    if blog:
        return render_template('blog_detail.html', blog=blog)
    else:
        return render_template('404.html'), 404

@main.route('/manage')
def blog_manage():
    """
    博客管理页面
    """
    blogs = dbHelper.get_all_blogs()
    return render_template('manage.html', blogs=blogs)

@main.route('/edit/<string:year>/<string:month>/<string:html_title>')
def manage_edit_blog(year, month, html_title):
    blog = dbHelper.get_specify_blog(year, month, html_title)
    if blog is None:
        return render_template('404.html'), 404
    
    blog_content = json.dumps(blog.content)
    categories = dbHelper.get_all_categories()
    return render_template('edit.html', blog=blog, blog_content=blog_content, categories=categories)

@main.route('/delete/<string:year>/<string:month>/<string:html_title>')
def manage_delete_blog(year, month, html_title):
    blog = dbHelper.get_specify_blog(year, month, html_title)
    if blog is None:
        return render_template('404.html'), 404
    
    return dbHelper.delete_blog(blog)  # 删除博客
    

@main.route('/admin_verify', methods=['POST'])
def admin_verify():
    """
    管理员验证
    """
    key = request.json.get("key")
    if key == admin_key:  # 验证密钥是否正确
        # 验证成功，设置 Cookie
        response = make_response({"status": "success", "message": "验证成功"})
        response.set_cookie("is_admin", "true", max_age=3600 * 24 * 14)  # 设置有效期为 14 天
        return response
    else:
        # 验证失败
        return {"status": "error", "message": "密钥错误"}, 401

@main.route('/categorized_blogs')
def categorized_blogs():
    pass