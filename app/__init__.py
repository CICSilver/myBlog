from flask import Flask
from tinydb import TinyDB

blog_db = TinyDB('./db/blog_db.json')   # 基础数据库

def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="../templates")

    from app.routes import main
    app.register_blueprint(main)

    return app