from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from app.database import DatabaseHelper, Blog, normalize_cover_url
from app.auth import admin_logout, current_admin_authenticated, login_required, validate_csrf_token
from app.view_filter import (
    EFFECTIVE_VIEW_SECONDS,
    READING_HEARTBEAT_SECONDS,
    is_crawler_user_agent,
    is_effective_reading_seconds,
    normalize_reading_seconds,
)
from datetime import datetime
import json
import os
import secrets

main = Blueprint('main', __name__)
dbHelper = DatabaseHelper()
SITE_NAME = "Silver's Blog"
PERSONAL_INTRO = "人事匆匆，或许有些可以留在这里。"
SUPPORTED_COVER_EXTENSIONS = {
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".png": "png",
    ".webp": "webp",
}
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

def _cover_upload_error(message, status_code=400):
    return jsonify({"status": "error", "message": message}), status_code


def _detect_cover_image_type(payload):
    if payload.startswith(b"\xff\xd8\xff"):
        return "jpg"

    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "webp"

    return None


def _allowed_cover_extension(filename):
    _, extension = os.path.splitext(filename or "")
    return SUPPORTED_COVER_EXTENSIONS.get(extension.lower())


def _cover_size_message(max_bytes):
    return "封面图片不能超过 {0}MB。".format(max_bytes // (1024 * 1024))


# =========================== 路由 ===========================
@main.route('/')
def index():
    return init_index_with_blogs(dbHelper.get_recent_blogs())

@main.route('/media/covers/<path:filename>')
def media_cover(filename):
    return send_from_directory(current_app.config["BLOG_COVER_UPLOAD_DIR"], filename)

@main.route('/edit/cover', methods=['POST'])
@login_required
def upload_cover_image():
    validate_csrf_token()

    cover_file = request.files.get("cover-image")
    if cover_file is None:
        return _cover_upload_error("请选择要上传的封面图片。")

    expected_type = _allowed_cover_extension(cover_file.filename)
    if expected_type is None:
        return _cover_upload_error("封面图片仅支持 JPG、PNG 或 WebP。")

    max_bytes = int(current_app.config.get("BLOG_COVER_MAX_BYTES", 5 * 1024 * 1024))
    payload = cover_file.stream.read(max_bytes + 1)

    if len(payload) > max_bytes:
        return _cover_upload_error(_cover_size_message(max_bytes), 413)

    if not payload:
        return _cover_upload_error("封面图片不能为空。")

    detected_type = _detect_cover_image_type(payload)
    if detected_type is None:
        return _cover_upload_error("封面图片格式无法识别。")

    if detected_type != expected_type:
        return _cover_upload_error("封面图片扩展名与实际格式不一致。")

    now = datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    filename = "{0}.{1}".format(secrets.token_urlsafe(16), detected_type)
    upload_dir = current_app.config["BLOG_COVER_UPLOAD_DIR"]
    target_dir = os.path.join(upload_dir, year, month)
    os.makedirs(target_dir, exist_ok=True)

    target_path = os.path.join(target_dir, filename)
    with open(target_path, "wb") as image_file:
        image_file.write(payload)

    cover_url = "/media/covers/{0}/{1}/{2}".format(year, month, filename)
    return jsonify({"status": "success", "cover_url": cover_url})

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
    
    if not blog:
        return render_template('404.html', **get_site_context()), 404

    article_view_tracking = _article_view_tracking_config(blog)
    return render_template(
        'blog_detail.html',
        blog=blog,
        article_view_tracking=article_view_tracking,
        **get_site_context(),
    )


@main.route('/track/article-view', methods=['POST'])
def track_article_view():
    validate_csrf_token()

    if current_admin_authenticated():
        return jsonify({"status": "ignored", "reason": "admin"})

    if is_crawler_user_agent(request.headers.get("User-Agent", "")):
        return jsonify({"status": "ignored", "reason": "crawler"})

    payload = request.get_json(silent=True) or {}
    reading_seconds = normalize_reading_seconds(payload.get("reading_seconds"))
    if not is_effective_reading_seconds(reading_seconds):
        return jsonify({"status": "ignored", "reason": "short_view"})

    view_session_id = str(payload.get("view_session_id") or "").strip()
    if not view_session_id:
        return jsonify({"status": "error", "message": "missing view_session_id"}), 400

    year = str(payload.get("year") or "").strip()
    month = str(payload.get("month") or "").strip()
    html_title = str(payload.get("html_title") or "").strip()
    blog = dbHelper.get_specify_blog(year, month, html_title)
    if blog is None:
        return jsonify({"status": "error", "message": "article not found"}), 404

    path = url_for(
        "main.blog_detail",
        year=int(blog.year),
        month=int(blog.month),
        html_title=blog.html_title,
    )

    try:
        view_record = dbHelper.record_or_update_article_view_session(
            blog,
            _get_client_ip(),
            path,
            view_session_id,
            reading_seconds,
        )
    except Exception as exc:
        print("article view record failed: {0}".format(exc))
        return jsonify({"status": "error", "message": "record failed"}), 500

    return jsonify(
        {
            "status": "recorded",
            "reading_seconds": view_record.get("reading_seconds", 0),
            "reading_time_label": view_record.get("reading_time_label", "未记录"),
        }
    )

@main.route('/manage')
@login_required
def blog_manage():
    """
    博客管理页面
    """
    blogs = dbHelper.get_all_blogs()
    return render_template('manage.html', blogs=blogs, **get_site_context())

@main.route('/manage/views')
@login_required
def article_view_manage():
    """
    文章浏览量统计页面
    """
    view_dashboard = dbHelper.get_article_view_dashboard(recent_limit=100)
    return render_template(
        'view_stats.html',
        view_dashboard=view_dashboard,
        **get_site_context(),
    )

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


def _article_view_tracking_config(blog):
    if current_admin_authenticated():
        return None

    if is_crawler_user_agent(request.headers.get("User-Agent", "")):
        return None

    return {
        "endpoint": url_for("main.track_article_view"),
        "year": blog.year,
        "month": blog.month,
        "html_title": blog.html_title,
        "minimum_seconds": EFFECTIVE_VIEW_SECONDS,
        "heartbeat_seconds": READING_HEARTBEAT_SECONDS,
    }


def _get_client_ip():
    if current_app.config.get("BLOG_TRUST_PROXY_HEADERS"):
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        forwarded_ip = forwarded_for.split(",", 1)[0].strip()
        if forwarded_ip:
            return forwarded_ip

        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip

    return request.remote_addr or ""
