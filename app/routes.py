from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from app.database import DatabaseHelper, Blog, normalize_cover_url
from app.auth import admin_logout, login_required, validate_csrf_token
import json

main = Blueprint('main', __name__)
dbHelper = DatabaseHelper()
SITE_NAME = "Silver's Blog"
PERSONAL_INTRO = "人事匆匆，或许有些可以留在这里。"
# ========================= 辅助函数 =========================
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
@login_required
def edit_blog():
    if request.method == 'POST':
        validate_csrf_token()
        blog = Blog()
        blog.html_title = request.form.get('html-title', '')
        blog.title = request.form['title']
        blog.content = request.form['content']
        blog.category = request.form['category']
        try:
            blog.cover_url = normalize_cover_url(request.form.get('cover-url', ''))
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
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
            original_key = (
                request.form.get('original-year') or blog.year,
                request.form.get('original-month') or blog.month,
                request.form.get('original-html-title') or blog.html_title,
            )
            response = dbHelper.update_blog(blog, original_key=original_key)
        elif action == "insert":
            # 插入新博客
            response = dbHelper.insert_blog(blog)
        elif action == "insert_new":
            # 兼容旧前端动作，具体去重交给数据库层统一处理
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
@login_required
def blog_manage():
    """
    博客管理页面
    """
    blogs = dbHelper.get_all_blogs()
    return render_template('manage.html', blogs=blogs, **get_site_context())

@main.route('/edit/<string:year>/<string:month>/<string:html_title>')
@login_required
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

@main.route('/delete/<string:year>/<string:month>/<string:html_title>', methods=['POST'])
@login_required
def manage_delete_blog(year, month, html_title):
    validate_csrf_token()
    blog = dbHelper.get_specify_blog(year, month, html_title)
    if blog is None:
        return jsonify({"status": "error", "message": "指定的博客不存在。"}), 404
    
    return dbHelper.delete_blog(blog)  # 删除博客

@main.route('/register')
def register():
    return redirect(url_for('main.index'))
    
@main.route('/logout', methods=['POST'])
@login_required
def logout():
    return admin_logout()

    

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
