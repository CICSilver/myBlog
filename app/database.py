from app import db
from tinydb import Query
from tinydb.table import Document
from datetime import datetime

class Blog:
    def __init__(self):
        now = datetime.now()
        self.html_title = None
        self.title = None
        self.content = None
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
        self.year = data.get('year')
        self.month = data.get('month')
        self.date = data.get('date')
        self.time = data.get('time')

class BlogDB:
    def __init__(self):
        self.all_year_table = db.table('years')

    def get_all_blogs(self):
        """
        获取所有博客列表
        """
        blogs = []
        years = self.all_year_table.all()
        for year in years:
            year_table = db.table(year['year'])
            month_data = year_table.all()
            for month in month_data:
                blogs.extend(month['blogs'])
        
        return blogs

    def get_year_table(self, year):
        if year is None:
            raise ValueError("year cannot be None")
        return db.table(year)

    def get_recent_blogs(self, default_days=7):
        """
        获取最近的博客

        :param rule: default_days: 默认天数
        :return: 最近的博客列表
        """
        # 获取最近记录，默认为7
        now = datetime.now()
        recent_data = []
        
        years = self.all_year_table.all() # 所有有记录的年份
        year = str(now.year)
        month = str(now.month)
        year_table = self.get_year_table(year)

        i = len(years) - 1  # 从最新的年份开始
        while len(recent_data) < default_days:
            month_data = year_table.get(Query().month == month)
            if month_data is not None:
                blogs = month_data['blogs'][-default_days:]
                recent_data.extend(blogs)
            
            # 向前推移一个月
            if month == "1":
                month = "12"
                i -= 1
                if i < 0:
                    break
                year = years[i]['year']
                year_table = self.get_year_table(year)
            else:
                month = str(int(month) - 1)

        return recent_data[:default_days]
    
    def insert_blog(self, blog: Blog):
        """
        插入博客到数据库
        """
        if blog is None:
            raise ValueError("Blog cannot be None")
        if not isinstance(blog, Blog):
            raise TypeError("Expected a Blog instance")
        

        year_table = self.get_year_table(blog.year)
        
        if len(year_table) == 0:
            # 新年份表，记录年份
            self.all_year_table.insert({"year": blog.year})

        month_data = self.get_month_blogs(blog.year, blog.month)
        if month_data is None:
            month_data = {"month": blog.month, "blogs": []}
            year_table.insert(month_data)  # 插入新的月份数据
        
        # 检查html_title重复情况，若存在则编号增加
        existing_blog = year_table.get(Query().month == blog.month and Query().html_title == blog.html_title)
        if existing_blog:
            blog.html_title = f"{blog.html_title}_{len(existing_blog['blogs']) + 1}"
        month_data["blogs"].append(blog.to_dict())
        year_table.update(month_data, Query().month == blog.month)  # 更新月份数据

        


    def get_month_blogs(self, year, month):
        """
        获取指定年月的博客列表
        """
        if month is None:
            raise ValueError("month cannot be None")
        
        year_table = self.get_year_table(year)
        month_data = year_table.get(Query().month == month)
        return month_data
    
    def get_blog_by_html_title(self, year, month, html_title):
        """
        根据年月和标题获取博客内容，返回应为唯一值
        """
        if html_title is None:
            raise ValueError("html_title cannot be None")
        year_table = self.get_year_table(year)
        blogs_data = year_table.get(Query().month == month)['blogs']
        for blog_data in blogs_data:
            if blog_data['html_title'] == html_title:
                blog = Blog()
                blog.from_dict(blog_data)
                return blog

        return None

        