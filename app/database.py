from app import blog_db
from tinydb import Query
from tinydb.table import Document
from datetime import datetime

class Category:
    def __init__(self):
        self.name = None
        self.reference = None
    def to_dict(self):
        return {
            'name': self.name,
            'reference': self.reference
        }
    def from_dict(self, data):
        self.name = data.get('name')
        self.reference = data.get('reference')

class Blog:
    def __init__(self):
        now = datetime.now()
        self.html_title = None
        self.title = None
        self.content = None
        self.category = None
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
    
    def __insert_category(self, category: str):
        """
        插入分类到数据库
        若分类已经存在则不插入
        """
        if category is None:
            raise ValueError("Category cannot be None")
        
        # 检查是否已存在
        existing_category = self.category_table.search(Query().category == category)
        if existing_category is not None:
            return {"status": "duplicate", "message": "分类已存在，请选择其他分类。"}
        
        self.category_table.insert({"name": category})
        return {"status": "success", "message": "分类插入成功。"}

    def __insert_date(self, blog: Blog):
        """
        插入博客日期到数据库
        无返回
        """
        date = {
            "year": blog.year,
            "month": blog.month
        }
        # 检查日期是否已存在
        res = self.date_table.search((Query().year == blog.year) & (Query().month == blog.month))
        if not res:
            # 插入新的日期数据
            self.date_table.insert(date)

    def get_all_blogs(self):
        """
        获取所有博客列表
        """
        return self.blog_table.all()

    def get_recent_blogs(self, default_days=7):
        """
        获取最近的博客

        :param rule: default_days: 默认天数
        :return: 最近的博客列表
        """
        return self.blog_table.all()[-default_days:]
    
    def insert_blog(self, blog: Blog):
        """
        插入博客到数据库
        """
        if blog is None:
            raise ValueError("Blog cannot be None")
        if not isinstance(blog, Blog):
            raise TypeError("Expected a Blog instance")
        

        self.__insert_category(blog.category)  # 确保分类存在
        
        # 检查html_title重复情况，若存在则编号增加
        blog_in_db = self.get_specify_blog(blog.year, blog.month, blog.html_title)
        if blog_in_db:
            return {"status": "duplicate", "message": "html标题重复，请选择处理方式。"}
        
        # 更新月份数据
        self.__insert_date(blog) 
        # 插入博客数据
        self.blog_table.insert(blog.to_dict()) 
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

        res = self.get_specify_blog(blog.year, blog.month, blog.html_title)

        if res is None:
            return {"status": "error", "message": "指定的博客不存在。"}
        else:
            # 更新博客数据
            operation(blog)
            return {"status": "success", "message": "博客数据更新成功。"}

    def update_blog(self, blog: Blog):
        """
        更新博客数据
        """
        def update_opera(blog):
            self.blog_table.update(blog.to_dict(), (Query().year == blog.year) & (Query().month == blog.month) & (Query().html_title == blog.html_title))
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
        
        
        


# class BlogDB:
#     def __init__(self):
#         self.all_year_table = blog_db.table('years')
#         self.category_table = blog_db.table('categories')

#     def get_all_categories(self):
#         """
#         获取所有分类列表
#         """
#         categories = self.category_table.all()
#         return categories
    
#     def insert_category(self, category: str):
#         """
#         插入分类到数据库
#         若分类已经存在则不插入
#         """
#         if category is None:
#             raise ValueError("Category cannot be None")
        
#         # 检查是否已存在
#         existing_category = self.category_table.get(Query().category == category)
#         if existing_category is not None:
#             return {"status": "duplicate", "message": "分类已存在，请选择其他分类。"}
        
#         self.category_table.insert({"name": category})
#         return {"status": "success", "message": "分类插入成功。"}

#     def get_all_blogs(self):
#         """
#         获取所有博客列表
#         """
#         blogs = []
#         years = self.all_year_table.all()
#         for year in years:
#             year_table = blog_db.table(year['year'])
#             month_data = year_table.all()
#             for month in month_data:
#                 blogs.extend(month['blogs'])
        
#         return blogs

#     def get_year_table(self, year):
#         if year is None:
#             raise ValueError("year cannot be None")
#         return blog_db.table(year)

#     def get_recent_blogs(self, default_days=7):
#         """
#         获取最近的博客

#         :param rule: default_days: 默认天数
#         :return: 最近的博客列表
#         """
#         # 获取最近记录，默认为7
#         now = datetime.now()
#         recent_data = []
        
#         years = self.all_year_table.all() # 所有有记录的年份
#         year = str(now.year)
#         month = str(now.month)
#         year_table = self.get_year_table(year)

#         i = len(years) - 1  # 从最新的年份开始
#         while len(recent_data) < default_days:
#             month_data = year_table.get(Query().month == month)
#             if month_data is not None:
#                 blogs = month_data['blogs'][-default_days:]
#                 recent_data.extend(blogs)
            
#             # 向前推移一个月
#             if month == "1":
#                 month = "12"
#                 i -= 1
#                 if i < 0:
#                     break
#                 year = years[i]['year']
#                 year_table = self.get_year_table(year)
#             else:
#                 month = str(int(month) - 1)

#         return recent_data[:default_days]
    
#     def insert_blog(self, blog: Blog):
#         """
#         插入博客到数据库
#         """
#         if blog is None:
#             raise ValueError("Blog cannot be None")
#         if not isinstance(blog, Blog):
#             raise TypeError("Expected a Blog instance")
        

#         year_table = self.get_year_table(blog.year)
#         self.insert_category(blog.category)  # 确保分类存在

#         if len(year_table) == 0:
#             # 新年份表，记录年份
#             self.all_year_table.insert({"year": blog.year})

#         month_data = self.get_month_blogs(blog.year, blog.month)
#         if month_data is None:
#             month_data = {"month": blog.month, "blogs": []}
#             year_table.insert(month_data)  # 插入新的月份数据
        
#         # 检查html_title重复情况，若存在则编号增加
#         blog_in_db = self.get_blog_by_html_title(blog.year, blog.month, blog.html_title)
#         if blog_in_db is not None:
#             return {"status": "duplicate", "message": "html标题重复，请选择处理方式。"}
        
#         # 插入博客数据
#         month_data["blogs"].append(blog.to_dict())
#         year_table.update(month_data, Query().month == blog.month)  # 更新月份数据
#         return {"status": "success", "message": "博客数据插入成功。"}
    
#     def __process_blog(self, blog: Blog, operation):
#         """
#         私有函数，修改/删除博客的通用逻辑

#         :param blog: Blog对象
#         :param operation: 操作类型，insert/update/delete
#         """
#         if blog is None:
#             raise ValueError("Blog cannot be None")
#         if not isinstance(blog, Blog):
#             raise TypeError("Expected a Blog instance")

#         year_table = self.get_year_table(blog.year)
#         month_data = year_table.get(Query().month == blog.month)
        
#         if month_data is None:
#             return {"status": "error", "message": "指定的年月不存在。"}
        
#         blogs = month_data["blogs"]
#         for i, existing_blog in enumerate(blogs):
#             if existing_blog["html_title"] == blog.html_title:
#                 operation(blogs, i)
#                 break
#         else:
#             return {"status": "error", "message": "指定的博客不存在。"}
        
#         year_table.update({"blogs": blogs}, Query().month == blog.month)
#         return {"status": "success", "message": "博客数据更新成功。"}

#     def update_blog(self, blog: Blog):
#         """
#         更新博客数据
#         """
#         def update_operation(blogs, index):
#             blogs[index] = blog.to_dict()
#         return self.__process_blog(blog, update_operation)

#     def delete_blog(self, blog: Blog):
#         """
#         删除博客数据

#         :param blog: 指定博客
#         :return response: {"status": "error", "message": "指定的博客不存在。"}

#         {"status": "success", "message": "博客数据删除成功。"}
#         """
#         def del_operation(blogs, index):
#             del blogs[index]
#         return self.__process_blog(blog, del_operation)

#     def get_month_blogs(self, year, month):
#         """
#         获取指定年月的博客列表
#         """
#         if month is None:
#             raise ValueError("month cannot be None")
        
#         year_table = self.get_year_table(year)
#         month_data = year_table.get(Query().month == month)
#         return month_data
    
#     def get_blog_by_html_title(self, year, month, html_title):
#         """
#         根据年月和标题获取博客内容，返回应为唯一值
#         """
#         if html_title is None:
#             raise ValueError("html_title cannot be None")
#         year_table = self.get_year_table(year)
#         blogs_data = year_table.get(Query().month == month)['blogs']
#         for blog_data in blogs_data:
#             if blog_data['html_title'] == html_title:
#                 blog = Blog()
#                 blog.from_dict(blog_data)
#                 return blog

#         return None

        