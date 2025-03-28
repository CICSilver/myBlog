from flask import Flask
from tinydb import TinyDB
import os

# 数据库文件路径
db_path = './db/blog_db.json'

# 确保父目录存在
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# 初始化 TinyDB
blog_db = TinyDB(db_path)  # 基础数据库

def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="../templates")

    from app.routes import main
    app.register_blueprint(main)

    return app