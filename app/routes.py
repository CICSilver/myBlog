from flask import Blueprint, Flask, render_template, redirect, url_for, request
from datetime import datetime
from app.database import BlogDB, Blog
import json
# from app import db

main = Blueprint('main', __name__)
blog_db = BlogDB()
# =========================== 路由 ===========================
@main.route('/')
def index():
    site_name = "Silver's Blog"
    personal_intro = "人事匆匆，或许有些可以留在这里。"
    return render_template('index.html', blogs=blog_db.get_recent_blogs(), site_name=site_name, personal_intro=personal_intro)

@main.route('/edit', methods=['GET', 'POST'])
def edit_blog():
    if request.method == 'POST':
        blog = Blog()
        blog.html_title = request.form['html-title']
        blog.title = request.form['title']
        blog.content = request.form['content']
        blog_db.insert_blog(blog)
        
        return redirect(url_for('main.index'))
    return render_template('edit.html', blog=None, blog_content=None)

@main.route('/<int:year>/<int:month>/<string:html_title>')
def blog_detail(year, month, html_title):
    # 根据年月和标题获取博客内容
    blog = blog_db.get_blog_by_html_title(str(year), str(month), html_title)
    
    if blog:
        return render_template('blog_detail.html', blog=blog)
    else:
        return render_template('404.html'), 404

@main.route('/manage')
def blog_manage():
    """
    博客管理页面
    """
    blogs = blog_db.get_all_blogs()
    return render_template('manage.html', blogs=blogs)

@main.route('/edit/<string:year>/<string:month>/<string:html_title>')
def manage_edit_blog(year, month, html_title):
    blog = blog_db.get_blog_by_html_title(year, month, html_title)
    if blog is None:
        return render_template('404.html'), 404
    
    blog_content = json.dumps(blog.content)
    return render_template('edit.html', blog=blog, blog_content=blog_content)

@main.route('/delete/<string:year>/<string:month>/<string:html_title>')
def manage_delete_blog(year, month, html_title):

    pass