from app import db
from datetime import datetime

class Blog:
    def __init__(self):
        now = datetime.now()
        self.html_title = None
        self.title = None
        self.content = None
        self.year = str(now.year)
        self.month = str(now.month)
        self.date = now.strftime('%Y-%m-%d')
        self.time = now.strftime('%H:%M:%S')

class BlogDB:
    def __init__(self):
        self.blog_table = db.table('blogs')

    def get_all_blogs(self):
        """
        获取所有博客

        :return: 所有博客列表
        """
        return self.blog_table.all()
    
    def get_recent_blogs(self, default_days=7):
        """
        获取最近的博客

        :param rule: default_days: 默认天数
        :return: 最近的博客列表
        """
        # 获取最近记录，默认为7
        return self.get_all_blogs()[-7:]
    
    def insert_blog(self, blog: Blog):
        """
        插入博客到数据库
        """
        all_blogs = self.get_all_blogs()
        # 如果数据库为空，初始化数据库结构
        if not all_blogs:
            all_blogs = []
        
        # 按年、月插入博客
        if blog.year not in all_blogs:
            all_blogs[blog.year] = {}
        if blog.month not in all_blogs[blog.year]:
            all_blogs[blog.year][blog.month] = []
        all_blogs[blog.year][blog.month].append(blog)

        # 更新数据库
        self.blog_table.insert()

    def get_blogs_by_year(self, year):
        """
        获取所有博客按年分组

        :return: 按年分组的博客列表
        """
        all_blogs = self.get_all_blogs()
        return all_blogs.get(str(year), {})
    
    def get_blogs_by_month(self, year, month):
        """
        获取所有博客按月分组

        :return: 按月分组的博客列表
        """
        year_blogs = self.get_blogs_by_year(year)
        return year_blogs.get(str(month), {})
    
    def get_blog_by_html_title(self, year, month, html_title):
        """
        根据html标题获取博客

        :return: blog
        """
        month_blogs = self.get_blogs_by_month(year, month)
        for blog in month_blogs:
            if blog['html_title'] == html_title:
                return blog
        return None