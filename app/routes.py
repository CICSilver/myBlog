from flask import Blueprint, Flask, render_template, redirect, url_for, request
from datetime import datetime
from app.database import BlogDB, Blog
# from app import db

main = Blueprint('main', __name__)
blog_db = BlogDB()

# =========================== 路由 ===========================
@main.route('/')
def index():
    return render_template('index.html', blogs=blog_db.get_recent_blogs())

@main.route('/edit', methods=['GET', 'POST'])
def edit_blog():
    if request.method == 'POST':
        blog = Blog()
        blog.html_title = request.form['html-title']
        blog.title = request.form['title']
        blog.content = request.form['content']
        blog_db.insert_blog(blog)
        
        return redirect(url_for('main.index'))
    return render_template('edit.html')

@main.route('/blog')
def get_blog():
    
    pass

@main.route('/<int:year>/<int:month>/<string:html_title>')
def blog_detail(year, month, html_title):
    # 根据年月和标题获取博客内容

    pass

def load_blogs():
    # 从数据库中获取最近7条记录
    blog_table = db.table('blogs')
    last_blogs = blog_table.all()[-7:]
    return last_blogs