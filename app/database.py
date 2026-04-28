from app import blog_db
from tinydb import Query
from tinydb.table import Document
from datetime import datetime
from pypinyin import lazy_pinyin

class Comment:
    def __init__(self, name=None, content=None, date=None, time=None):
        self.name = name
        self.content = content
        self.date = date
        self.time = time

class Category:
    def __init__(self, html_title=None, name=None, num=0, init_dict=[]):
        if isinstance(init_dict, dict) and len(init_dict) > 0:
            self.html_title = init_dict.get('html_title')
            self.name = init_dict.get('name')
            self.num = init_dict.get('num')
        else:
            self.html_title = html_title
            self.name = name
            self.num = num

    def to_dict(self):
        return {
            'html_title': self.html_title,
            'name': self.name,
            'num': self.num
        }
    def from_dict(self, data):
        self.html_title = data.get('html_title')
        self.name = data.get('name')
        self.num = data.get('num')
    
    def generate_html_title(self):
        """
        根据分类名称生成html标题，无返回值，直接修改自身属性
        """
        if not self.name:
            raise ValueError("分类名称不能为空")
        # 中文名称转为拼音
        self.html_title = "_".join(lazy_pinyin(self.name))


class Blog:
    def __init__(self, html_title=None, title=None, content=None, category=None):
        now = datetime.now()
        self.html_title = html_title
        self.title = title
        self.content = content
        self.category = category
        self.year = str(now.year)   # 默认当前年份
        self.month = str(now.month)
        self.date = now.strftime('%Y-%m-%d')
        self.time = now.strftime('%H:%M:%S')
    
    def to_dict(self):
        """
        将博客对象转换为字典
        """
        return {
            'html_title': self.html_title,
            'title': self.title,
            'content': self.content,
            'category': self.category,
            'year': self.year,
            'month': self.month,
            'date': self.date,
            'time': self.time
        }
    
    def from_dict(self, data):
        """
        从字典中加载博客数据
        """
        self.html_title = data.get('html_title')
        self.title = data.get('title')
        self.content = data.get('content')
        self.category = data.get('category')
        self.year = data.get('year')
        self.month = data.get('month')
        self.date = data.get('date')
        self.time = data.get('time')

class DatabaseHelper:
    """
    数据库模板：
    {
        # 年月表
        "date": {
            "1": {
                "year":"2025",
                "month": "3"
            },
            ...
        },
        # 分类表
        "categories": {
            "1": {
                "name": "分类1"
            },
            ....
        },
        # 博客表, html_title作为当年月都相同时的区分元素
        "blogs": {
            "1": {
                "html_title": "...",
                "title": "...",
                "content": "...",
                "year": "2025",
                "month": "3",
                "date": "2025-03-24",
                "time": "13:20:18"
            },
            ....
        }
    }
    """
    def __init__(self):
        # 年表，存储全部有博客的年份+月份
        self.date_table = blog_db.table('date')
        # 分类表，存储分类
        self.category_table = blog_db.table('categories')
        # 博客表，存储全部博客
        self.blog_table = blog_db.table('blogs')

    def get_all_categories(self):
        """
        获取所有分类列表
        """
        categories = self.category_table.all()
        return categories
    
    def get_all_date(self):
        """
        获取所有日期列表
        """
        dates = self.date_table.all()
        dates.reverse()  # 反转列表，最新的在前面
        return dates

    def clear_empty_categories(self):
        """
        清空无用分类
        """
        categories = self.category_table.all()
        for category in categories:
            if category['num'] == 0:
                self.category_table.remove(Query().name == category['name'])

    def __insert_category(self, categoryName: str):
        """
        插入分类到数据库
        若分类已经存在则不插入
        """
        if categoryName is None:
            raise ValueError("Category cannot be None")
        
        # 检查是否已存在
        existing_category = self.category_table.search(Query().name == categoryName)
        if len(existing_category) > 0:
            category_data = existing_category[0]
            category_data['num'] += 1
            # 更新分类数量
            self.category_table.update(category_data, Query().name == categoryName)
            return {"status": "duplicate", "message": "分类已存在，增加分类所属博客数量。"}
        
        category = Category()
        category.name = categoryName
        category.num = 1
        category.generate_html_title()
        self.category_table.insert(category.to_dict())
        return {"status": "success", "message": "分类插入成功。"}
    
    def __update_category(self, category: Category):
        """
        更新分类到数据库
        无返回
        """
        if category is None:
            raise ValueError("Category cannot be None")
        
        if category.num <= 0:
            # 删除分类
            self.category_table.remove(Query().name == category.name)
        else:
            self.category_table.update(category.to_dict(), Query().name == category.name)


    def __insert_date(self, blog: Blog):
        """
        插入博客日期到数据库
        无返回
        """
        date = {
            "year": blog.year,
            "month": blog.month,
            "num": 1
        }
        # 检查日期是否已存在
        res = self.date_table.search((Query().year == blog.year) & (Query().month == blog.month))
        if len(res) == 0:
            # 插入新的日期数据
            self.date_table.insert(date)

    def __update_blog_num_in_date(self, year, month):
        """
        更新日期表中的博客数量
        """
        if year is None:
            raise ValueError("year cannot be None")
        if month is None:
            raise ValueError("month cannot be None")
        
        # 确保date中有num字段
        res = self.date_table.search((Query().year == year) & (Query().month == month))
        date_dict = res[0]
        if "num" not in date_dict:
            date_dict["num"] = 0
        
        blogs = self.blog_table.search((Query().year == year) & (Query().month == month))
        date_dict["num"] = len(blogs)
        self.date_table.update(date_dict, (Query().year == year) & (Query().month == month))
        
        
    def get_all_blogs(self):
        """
        获取所有博客列表
        """
        return self.blog_table.all()

    def get_recent_blogs(self, default_days=10):
        """
        获取最近的博客

        :param rule: default_days: 默认天数
        :return: 最近的博客列表
        """
        recent_blogs = self.blog_table.all()[-default_days:]
        recent_blogs.reverse()  # 反转列表，最新的在前面
        return recent_blogs
    
    def get_blogs_by_category(self, category_name: str):
        """
        根据分类名称获取博客列表
        """
        if category_name is None:
            raise ValueError("category_name cannot be None")
        
        blogs = self.blog_table.search(Query().category == category_name)
        return blogs
    
    def get_blogs_by_date(self, year: str, month: str):
        """
        根据年月获取博客列表
        """
        if year is None:
            raise ValueError("year cannot be None")
        if month is None:
            raise ValueError("month cannot be None")
        
        blogs = self.blog_table.search((Query().year == year) & (Query().month == month))
        return blogs
    
    def insert_blog(self, blog: Blog):
        """
        插入博客到数据库
        """
        if blog is None:
            raise ValueError("Blog cannot be None")
        if not isinstance(blog, Blog):
            raise TypeError("Expected a Blog instance")
        

        
        # 检查html_title重复情况，若存在则编号增加
        blog_in_db = self.get_specify_blog(blog.year, blog.month, blog.html_title)
        if blog_in_db:
            return {"status": "duplicate", "message": "html标题重复，请选择处理方式。"}
        
        self.__insert_category(blog.category)  # 确保分类存在
        # 更新月份数据
        self.__insert_date(blog)
        # 插入博客数据
        self.blog_table.insert(blog.to_dict()) 
        self.__update_blog_num_in_date(blog.year, blog.month)
        return {"status": "success", "message": "博客数据插入成功。"}
    
    def __process_blog(self, blog: Blog, operation):
        """
        私有函数，修改/删除博客的通用逻辑

        :param blog: Blog对象
        :param operation: 操作类型，insert/update/delete
        """
        if blog is None:
            raise ValueError("Blog cannot be None")
        if not isinstance(blog, Blog):
            raise TypeError("Expected a Blog instance")

        # 更新博客数据
        operation(blog)
        return {"status": "success", "message": "博客数据更新成功。"}

    def update_blog(self, blog: Blog):
        """
        更新博客数据
        """
        def update_opera(blog):
            self.blog_table.update(blog.to_dict(), (Query().year == blog.year) & (Query().month == blog.month) & (Query().html_title == blog.html_title))
        
        # 更新分类信息
        old_blog_data = self.get_specify_blog_o(blog)
        if old_blog_data is None:
            return {"status": "error", "message": "指定的博客不存在。"}
        if old_blog_data.category != blog.category:
            # 分类发生变化，更新分类数量
            res = self.category_table.search(Query().name == old_blog_data.category)
            old_category_data = res[0]
            old_category_data['num'] -= 1
            self.__update_category(Category(init_dict=old_category_data))
            # 更新新分类数量
            res = self.category_table.search(Query().name == blog.category)
            if len(res) == 0:
                self.__insert_category(blog.category)
            else:
                new_category_data = res[0]
                new_category_data['num'] += 1
                self.__update_category(Category(init_dict=new_category_data))

        return self.__process_blog(blog, update_opera)



    def delete_blog(self, blog: Blog):
        """
        删除博客数据

        :param blog: 指定博客
        :return response: {"status": "error", "message": "指定的博客不存在。"}

        {"status": "success", "message": "博客数据删除成功。"}
        """
        def del_opear(blog):
            self.blog_table.remove((Query().year == blog.year) & (Query().month == blog.month) & (Query().html_title == blog.html_title))
            # 删除博客后，更新日期信息
            self.__update_blog_num_in_date(blog.year, blog.month)
            
        # 更新分类信息
        res = self.category_table.search(Query().name == blog.category)
        if len(res) == 0:
            raise ValueError("分类不存在")
        category_data = res[0]
        category_data['num'] -= 1
        if category_data['num'] <= 0:
            self.category_table.remove(Query().name == blog.category)
        else:
            self.category_table.update(category_data, Query().name == blog.category)
        
        return self.__process_blog(blog, del_opear)
    
    def get_specify_blog(self, year, month, html_title) -> Blog | None:
        """
        根据年月和标题获取博客内容，返回应为唯一值
        """
        if html_title is None:
            raise ValueError("html_title cannot be None")
        if year is None:
            raise ValueError("year cannot be None")
        if month is None:
            raise ValueError("month cannot be None")
        
        blog_data = self.blog_table.search((Query().html_title == html_title) & (Query().year == year) & (Query().month == month))

        if len(blog_data) == 1:
            blog = Blog()
            blog.from_dict(blog_data[0])
            return blog
        else:
            return None
    
    def get_specify_blog_o(self, blog:Blog):
        if blog is None:
            raise ValueError("blog cannot be None")
        if not isinstance(blog, Blog):
            raise TypeError("Expected a Blog instance")
        
        return self.get_specify_blog(blog.year, blog.month, blog.html_title)
        
