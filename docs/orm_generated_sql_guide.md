# 本项目中 ORM 生成 SQL 的完整说明

## 1. 这份文档的目的

这份文档专门回答三个问题：

1. 本项目里 ORM 代码具体长什么样
2. 这些 ORM 代码大致会生成什么 SQL
3. 这些 SQL 在项目中分别承担什么功能

这里的 ORM 主要指 `Flask-SQLAlchemy / SQLAlchemy ORM`。  
需要特别说明的是：

- ORM 生成出来的 SQL 会因为数据库类型不同而略有差异
- 本项目生产默认是 MySQL，测试时常用 SQLite
- 所以下文中的 SQL 以“典型形态”来写，重点是结构和功能，不强求每个占位符、别名、引号和方言细节完全一致

## 2. ORM 在本项目中的位置

### 2.1 入口

- `app/extensions.py`
  - `db = SQLAlchemy()`

这表示项目所有模型、会话、查询、事务提交，都是围绕这个 `db` 对象展开。

### 2.2 模型定义

- `app/models.py`

这里定义了 ORM 模型类，它们会映射成数据库表，例如：

- `User -> users`
- `Category -> categories`
- `Document -> documents`
- `Author -> authors`
- `Affiliation -> affiliations`
- `Keyword -> keywords`
- `Tag -> tags`
- `Source -> sources`
- `Publisher -> publishers`
- `File -> files`
- `AIAgentActivity -> ai_agent_activities`
- `AIAgentJournal -> ai_agent_journals`
- `MergeAudit -> merge_audits`

### 2.3 会话与事务

项目通过 `db.session` 统一管理：

- 查询
- 插入
- 更新
- 删除
- 提交
- 回滚
- flush

也就是说，ORM 不是简单“帮你写 SELECT”，而是完整接管了数据库交互生命周期。

## 3. ORM 模型如何映射成表

先看最典型的模型定义风格。

### 3.1 示例：普通实体表

代码形态：

```python
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(128), unique=True)
```

ORM 会把它映射成接近如下的 SQL 表结构：

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(128) UNIQUE
);

CREATE INDEX ix_users_username ON users (username);
```

功能：

- 定义一张用户表
- 定义主键
- 定义唯一约束
- 定义非空约束
- 定义索引

### 3.2 示例：带外键的实体表

代码形态：

```python
class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    source_id = db.Column(db.Integer, db.ForeignKey("sources.id"), nullable=True)
    title = db.Column(db.String(512), nullable=False)
```

典型 SQL 形态：

```sql
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    user_id INTEGER NOT NULL,
    category_id INTEGER NULL,
    source_id INTEGER NULL,
    title VARCHAR(512) NOT NULL,
    CONSTRAINT fk_documents_user_id FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT fk_documents_category_id FOREIGN KEY (category_id) REFERENCES categories (id),
    CONSTRAINT fk_documents_source_id FOREIGN KEY (source_id) REFERENCES sources (id)
);

CREATE INDEX ix_documents_user_id ON documents (user_id);
```

功能：

- 建立“文献属于哪个用户、哪个分类、哪个来源”的参照关系

### 3.3 示例：复合主键关联表

代码形态：

```python
class DocumentAuthor(db.Model):
    __tablename__ = "document_authors"

    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey("authors.id"), primary_key=True)
    author_order = db.Column(db.SmallInteger, nullable=False, default=1)
```

典型 SQL 形态：

```sql
CREATE TABLE document_authors (
    document_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    author_order SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (document_id, author_id),
    FOREIGN KEY (document_id) REFERENCES documents (id),
    FOREIGN KEY (author_id) REFERENCES authors (id)
);
```

功能：

- 表达文献和作者的多对多关系
- 额外保存作者顺序

### 3.4 示例：唯一约束

代码形态：

```python
__table_args__ = (
    db.UniqueConstraint("user_id", "name", name="uq_keyword_user_name"),
)
```

典型 SQL 形态：

```sql
ALTER TABLE keywords
ADD CONSTRAINT uq_keyword_user_name UNIQUE (user_id, name);
```

功能：

- 保证同一个用户的关键词名不重复

## 4. 本项目中最常见的 ORM 查询代码形态

下面按“代码形态 -> 典型 SQL -> 功能”逐类说明。

## 4.1 `filter_by(...).first()`

代码形态：

```python
user = User.query.filter_by(username=username).first()
```

典型 SQL：

```sql
SELECT users.id, users.username, users.password_hash, users.email, ...
FROM users
WHERE users.username = :username
LIMIT 1;
```

功能：

- 按唯一或准唯一条件取第一条记录
- 常用于登录、去重检查、配置读取

项目中的主要用途：

- 登录按用户名查用户
- 注册时检查用户名是否已存在
- 注册时检查邮箱是否已存在
- 文献导入时按 DOI 查重
- 文献导入时按 `title + publication_year` 查重

出现位置：

- `app/blueprints/auth.py`
- `app/blueprints/batch_bibtex.py`
- `app/__init__.py`
- `app/services/upsert.py`
- `app/services/ai_agent.py`

## 4.2 `filter_by(...).all()`

代码形态：

```python
categories = Category.query.filter_by(user_id=current_user.id).all()
```

典型 SQL：

```sql
SELECT categories.id, categories.user_id, categories.parent_id, categories.name, categories.created_at
FROM categories
WHERE categories.user_id = :user_id;
```

功能：

- 按条件取出一组记录
- 常用于列表展示、树结构构建、批量处理

项目用途：

- 分类列表
- 文献列表
- 标签、来源、作者、机构字典列表
- AI 日志按月列表

## 4.3 `order_by(...).all()`

代码形态：

```python
tags = Tag.query.filter_by(user_id=uid).order_by(Tag.name).all()
```

典型 SQL：

```sql
SELECT tags.id, tags.user_id, tags.name
FROM tags
WHERE tags.user_id = :user_id
ORDER BY tags.name ASC;
```

功能：

- 列表查询时保证展示顺序稳定

项目用途：

- 分类按名称排序
- 用户审批列表按创建时间排序
- 标签/来源/作者/机构自动补全按名称排序

## 4.4 `first_or_404()`

代码形态：

```python
doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first_or_404()
```

典型 SQL：

```sql
SELECT documents.id, documents.user_id, documents.category_id, documents.source_id, ...
FROM documents
WHERE documents.id = :doc_id
  AND documents.user_id = :user_id
LIMIT 1;
```

功能：

- 查询资源
- 如果没有记录，自动转成 Web 404

项目用途：

- 文献详情
- 文献编辑
- BibTeX 单篇导出
- 管理员加载目标用户
- 文件下载与删除前的归属校验

## 4.5 `db.session.get(Model, primary_key)`

代码形态：

```python
setting = db.session.get(UserSetting, user_id)
```

典型 SQL：

```sql
SELECT user_settings.user_id, user_settings.mineru_url
FROM user_settings
WHERE user_settings.user_id = :pk;
```

功能：

- 按主键直接查询
- 比 `filter_by(...).first()` 更适合主键查找

项目用途：

- 读取用户设置
- 读取作者编号计数器 `AuthorCode`
- 读取 AI Agent 设置
- 登录态加载用户

主要出现位置：

- `app/__init__.py`
- `app/blueprints/settings.py`
- `app/blueprints/documents.py`
- `app/blueprints/batch_bibtex.py`
- `app/services/upsert.py`
- `app/services/ai_agent.py`

## 4.6 `filter(...in_(...))`

代码形态：

```python
Document.query.filter(
    Document.user_id == current_user.id,
    Document.id.in_(doc_ids),
)
```

典型 SQL：

```sql
SELECT documents.id, documents.user_id, documents.title, ...
FROM documents
WHERE documents.user_id = :user_id
  AND documents.id IN (:id_1, :id_2, :id_3, ...);
```

功能：

- 批量按一组 id 取记录

项目用途：

- 批量删除文献
- 批量改分类
- 分类树展开后按多 id 查询文献

## 4.7 `paginate(...)`

代码形态：

```python
pagination = query.order_by(Document.updated_at.desc()).paginate(
    page=page,
    per_page=20,
    error_out=False,
)
```

典型 SQL：

```sql
SELECT documents.id, documents.user_id, documents.title, ...
FROM documents
WHERE documents.user_id = :user_id
ORDER BY documents.updated_at DESC
LIMIT :limit OFFSET :offset;
```

通常还会伴随一条总数统计 SQL：

```sql
SELECT COUNT(*) AS count_1
FROM documents
WHERE documents.user_id = :user_id;
```

功能：

- 分页查询
- 避免一次性加载全部记录

项目用途：

- 文献列表页

## 4.8 `filter(or_(...))`

代码形态：

```python
base = base.filter(
    or_(
        Document.title.ilike(like),
        Document.abstract.ilike(like),
        Document.doi.ilike(like),
        ...
    )
)
```

典型 SQL：

```sql
SELECT documents.id, documents.title, documents.abstract, documents.doi, ...
FROM documents
WHERE documents.user_id = :user_id
  AND (
        LOWER(documents.title) LIKE LOWER(:like_1)
     OR LOWER(documents.abstract) LIKE LOWER(:like_2)
     OR LOWER(documents.doi) LIKE LOWER(:like_3)
  );
```

功能：

- 多字段综合搜索

项目用途：

- 文献全文检索式搜索

## 4.9 `ilike(...)`

代码形态：

```python
Author.name.ilike(f"%{author}%")
```

典型 SQL：

```sql
LOWER(authors.name) LIKE LOWER(:author_pattern)
```

功能：

- 大小写不敏感的模糊匹配

项目用途：

- 作者搜索
- 来源搜索
- 文献标题/摘要/DOI 搜索

## 4.10 `join(...)`

代码形态：

```python
db.session.query(Document)
    .join(DocumentAuthor, DocumentAuthor.document_id == Document.id)
    .filter(DocumentAuthor.author_id == author.id)
    .order_by(Document.updated_at.desc())
    .first()
```

典型 SQL：

```sql
SELECT documents.id, documents.user_id, documents.title, documents.updated_at, ...
FROM documents
JOIN document_authors
  ON document_authors.document_id = documents.id
WHERE document_authors.author_id = :author_id
  AND documents.user_id = :user_id
ORDER BY documents.updated_at DESC
LIMIT 1;
```

功能：

- 多表连接查询

项目用途：

- 作者自动补全时找作者最近出现在哪篇文献里
- 重复合并预览时统计某个出版社关联多少文献
- 标签搜索时连 `document_tags`

## 4.11 `any(...)` 和 `has(...)`

这是本项目里非常重要的一类 ORM 写法。

### `any(...)`

代码形态：

```python
Document.keywords.any(Keyword.name.ilike(like))
```

典型 SQL 形态：

```sql
EXISTS (
    SELECT 1
    FROM document_keywords
    JOIN keywords ON keywords.id = document_keywords.keyword_id
    WHERE document_keywords.document_id = documents.id
      AND LOWER(keywords.name) LIKE LOWER(:like)
)
```

功能：

- 判断“当前主表记录是否存在满足条件的关联记录”

项目用途：

- 搜索关键词
- 搜索标签
- 搜索文献作者
- 查找孤立数据 `~Author.document_links.any()`

### `has(...)`

代码形态：

```python
Document.source.has(Source.name.ilike(like))
```

典型 SQL 形态：

```sql
EXISTS (
    SELECT 1
    FROM sources
    WHERE sources.id = documents.source_id
      AND LOWER(sources.name) LIKE LOWER(:like)
)
```

功能：

- 判断一对一/多对一关联对象是否满足条件

项目用途：

- 文献按来源搜索
- 搜索中按作者、来源联动筛选

## 4.12 `group_by(...) + count(distinct(...))`

代码形态：

```python
match_count = func.count(func.distinct(DocumentTag.tag_id))
rows = (
    base.join(DocumentTag, DocumentTag.document_id == Document.id)
    .filter(DocumentTag.tag_id.in_(selected_tag_ids))
    .add_columns(match_count.label("match_count"))
    .group_by(Document.id)
    .order_by(match_count.desc(), Document.updated_at.desc())
    .all()
)
```

典型 SQL：

```sql
SELECT documents.id, documents.user_id, documents.title, ...,
       COUNT(DISTINCT document_tags.tag_id) AS match_count
FROM documents
JOIN document_tags ON document_tags.document_id = documents.id
WHERE documents.user_id = :user_id
  AND document_tags.tag_id IN (:tag1, :tag2, :tag3, ...)
GROUP BY documents.id
ORDER BY match_count DESC, documents.updated_at DESC;
```

功能：

- 聚合统计
- 按命中标签数排序

项目用途：

- 多标签文献搜索结果排序

## 4.13 `distinct().count()`

代码形态：

```python
query.distinct().count()
```

典型 SQL：

```sql
SELECT COUNT(*) FROM (
    SELECT DISTINCT ...
) AS anon_1;
```

功能：

- 统计去重后的记录数

项目用途：

- 重复词典合并预览时统计受影响文献数

## 4.14 `limit(...)`

代码形态：

```python
.limit(ACTIVITY_FETCH_LIMIT).all()
```

典型 SQL：

```sql
SELECT ...
FROM ai_agent_activities
WHERE ...
ORDER BY created_at ASC
LIMIT :limit;
```

功能：

- 限制返回数量
- 防止一次读太多数据

项目用途：

- AI 活动记录抓取
- 合并审计列表

## 4.15 `filter(...).delete(synchronize_session=False)`

代码形态：

```python
AIAgentActivity.query.filter(
    AIAgentActivity.user_id == user_id,
    AIAgentActivity.created_at < cutoff,
).delete(synchronize_session=False)
```

典型 SQL：

```sql
DELETE FROM ai_agent_activities
WHERE user_id = :user_id
  AND created_at < :cutoff;
```

功能：

- 批量删除满足条件的记录

项目用途：

- 删除指定时间点之前的 AI 活动

说明：

- 这是一种“批量 DELETE”
- 和 `db.session.delete(obj)` 删除单个对象不同

## 4.16 `update({...})`

代码形态：

```python
Document.query.filter_by(category_id=cat.id).update({"category_id": None})
```

典型 SQL：

```sql
UPDATE documents
SET category_id = NULL
WHERE category_id = :category_id;
```

功能：

- 批量更新

项目用途：

- 删除分类前，把该分类下的文献全部变成未分类

## 4.17 `with_for_update()`

代码形态：

```python
counter = (
    AuthorCode.query.filter_by(user_id=user_id, name=name)
    .with_for_update()
    .first()
)
```

典型 SQL：

```sql
SELECT author_codes.user_id, author_codes.name, author_codes.next_code
FROM author_codes
WHERE author_codes.user_id = :user_id
  AND author_codes.name = :name
FOR UPDATE;
```

功能：

- 加行锁
- 防止并发情况下两个请求同时拿到同一个编号

项目用途：

- 给同名作者分配下一个 `code`

这是本项目中最典型的“ORM 生成并发控制 SQL”。

## 4.18 `db.session.merge(obj)`

代码形态：

```python
db.session.merge(obj)
```

典型行为：

- 如果主键已存在，转成 `UPDATE`
- 如果主键不存在，转成 `INSERT`

SQL 可能表现为：

```sql
SELECT ... WHERE primary_key = :pk;
UPDATE ... WHERE primary_key = :pk;
```

或

```sql
SELECT ... WHERE primary_key = :pk;
INSERT INTO ...;
```

功能：

- 把一个对象合并回当前会话

项目用途：

- 词典合并回滚时恢复已删除记录

## 4.19 `db.session.add(...) + commit()`

代码形态：

```python
db.session.add(user)
db.session.commit()
```

典型 SQL：

```sql
INSERT INTO users (username, password_hash, email, is_admin, can_review_registrations, is_approved, approval_status, created_at)
VALUES (:username, :password_hash, :email, :is_admin, :can_review_registrations, :is_approved, :approval_status, :created_at);
```

功能：

- 插入新记录

项目用途：

- 用户注册
- 新建文献
- 插入附件元数据
- 插入 AI 活动
- 插入合并审计

## 4.20 改属性 + `commit()`

代码形态：

```python
user.is_approved = True
user.approval_status = "approved"
db.session.commit()
```

典型 SQL：

```sql
UPDATE users
SET is_approved = :is_approved,
    approval_status = :approval_status
WHERE users.id = :id;
```

功能：

- 更新一条已经加载到会话中的记录

项目用途：

- 审核用户
- 编辑文献
- 修改 AI 设置
- 修改用户密码

## 4.21 `db.session.delete(obj)`

代码形态：

```python
db.session.delete(file_record)
db.session.commit()
```

典型 SQL：

```sql
DELETE FROM files
WHERE files.id = :id;
```

功能：

- 删除单个 ORM 对象

项目用途：

- 删除附件
- 删除分类
- 删除作者/标签/关键词/来源等词典项
- 删除文献

## 4.22 `db.session.flush()`

`flush()` 不一定直接对应最终提交，但它会提前把当前待写入内容送到数据库，从而生成 SQL。

代码形态：

```python
db.session.add(document)
db.session.flush()
```

典型结果：

- ORM 会先执行 `INSERT INTO documents ...`
- 然后把数据库生成的 `document.id` 回填到 Python 对象

功能：

- 在正式 `commit()` 之前提前拿到主键
- 后续可以继续插入依赖这个主键的关联记录

项目用途：

- 创建文献后马上插入 `DocumentAuthor`
- 新作者、新关键词、新标签创建后马上用于关联

## 4.23 关系集合操作 `append()` / `clear()`

这一类非常重要，因为它们表面上不是 SQL，底层却会自动生成 SQL。

### `append()`

代码形态：

```python
document.keywords.append(keyword)
```

底层典型 SQL：

```sql
INSERT INTO document_keywords (document_id, keyword_id)
VALUES (:document_id, :keyword_id);
```

功能：

- 建立多对多关联

项目用途：

- 给文献添加关键词
- 给文献添加标签
- 给作者添加机构

### `clear()`

代码形态：

```python
document.keywords.clear()
```

底层典型 SQL：

```sql
DELETE FROM document_keywords
WHERE document_id = :document_id;
```

功能：

- 清空某个对象当前的关联关系

项目用途：

- 编辑文献时重建关键词集合
- 编辑文献时重建标签集合
- 编辑文献时清空作者关联再重新插入

## 4.24 `db.metadata.create_all(...)` / `drop_all(...)`

代码形态：

```python
db.metadata.create_all(bind=op.get_bind(), checkfirst=True)
```

典型行为：

- ORM 根据模型自动生成建表 SQL
- 包括 `CREATE TABLE`
- `CREATE INDEX`
- `ALTER TABLE ... ADD CONSTRAINT`

功能：

- 自动建表
- 用于 Alembic 基线迁移

项目用途：

- `migrations/versions/20260624_0001_course_project_baseline.py`

## 5. 各文件里 ORM 代码分别在做什么

下面按文件归纳，尽量不漏掉主要 ORM 功能。

## 5.1 `app/__init__.py`

主要 ORM 功能：

- 启动时查管理员是否存在
- 不存在则插入管理员
- `db.session.get(models.User, int(user_id))` 作为登录态加载
- `db.session.execute(text("SELECT 1"))` 做健康检查

对应 SQL 类型：

- `SELECT ... WHERE username = ? LIMIT 1`
- `INSERT INTO users ...`
- `SELECT ... WHERE id = ?`
- 原生 SQL `SELECT 1`

## 5.2 `app/blueprints/auth.py`

主要 ORM 功能：

- 注册时查用户名是否重复
- 注册时查邮箱是否重复
- 注册成功插入新用户
- 登录时按用户名查询

对应 SQL 类型：

- `SELECT ... WHERE username = ? LIMIT 1`
- `SELECT ... WHERE email = ? LIMIT 1`
- `INSERT INTO users ...`

## 5.3 `app/blueprints/admin.py`

主要 ORM 功能：

- 查询待审批用户
- 查询全部用户
- 更新用户审批状态
- 更新次级管理员权限

对应 SQL 类型：

- `SELECT ... WHERE is_approved = 0 AND approval_status = 'pending' ORDER BY ...`
- `SELECT ... FROM users ORDER BY ...`
- `UPDATE users SET is_approved = ?, approval_status = ? WHERE id = ?`
- `UPDATE users SET can_review_registrations = ? WHERE id = ?`

## 5.4 `app/blueprints/categories.py`

主要 ORM 功能：

- 查询当前用户的分类
- 按 id 查父分类
- 插入新分类
- 改分类名称
- 批量把文献改为未分类
- 删除分类

对应 SQL 类型：

- `SELECT ... FROM categories WHERE user_id = ?`
- `INSERT INTO categories ...`
- `UPDATE categories SET name = ? WHERE id = ?`
- `UPDATE documents SET category_id = NULL WHERE category_id = ?`
- `DELETE FROM categories WHERE id = ?`

## 5.5 `app/blueprints/documents.py`

这是 ORM 使用最密集的文件。

主要 ORM 功能：

- 分类树查询
- 文献列表分页
- 文献搜索
- 单篇文献加载
- 新建文献
- 编辑文献
- 批量删除
- 批量改分类
- 附件下载前校验归属
- 附件删除
- 作者自动补全

涉及的 SQL 类型非常丰富：

- 普通 `SELECT`
- 带 `ORDER BY / LIMIT / OFFSET` 的分页查询
- `OR` 条件搜索
- `ILIKE` 模糊匹配
- `IN` 批量匹配
- `JOIN`
- `EXISTS` 子查询
- `GROUP BY`
- `COUNT(DISTINCT ...)`
- `INSERT`
- `UPDATE`
- `DELETE`
- 关联表插入/删除

这部分基本覆盖了本项目 ORM 生成 SQL 的绝大多数形态。

## 5.6 `app/blueprints/batch_bibtex.py`

主要 ORM 功能：

- 读取用户设置
- 批量导入前查分类合法性
- 按 DOI 或标题+年份查重
- 插入文献
- 插入文献作者关系
- 批量导入成功后提交

对应 SQL 类型：

- `SELECT ... FROM user_settings WHERE user_id = ?`
- `SELECT ... FROM categories WHERE id = ? AND user_id = ?`
- `SELECT ... FROM documents WHERE user_id = ? AND doi = ? LIMIT 1`
- `SELECT ... FROM documents WHERE user_id = ? AND title = ? AND publication_year = ? LIMIT 1`
- `INSERT INTO documents ...`
- `INSERT INTO document_authors ...`

## 5.7 `app/blueprints/bibtex.py`

主要 ORM 功能：

- 导出全部文献前查询当前用户全部文献
- 导出单篇文献前查询目标文献

SQL 类型：

- `SELECT ... FROM documents WHERE user_id = ?`
- `SELECT ... FROM documents WHERE id = ? AND user_id = ? LIMIT 1`

## 5.8 `app/blueprints/library.py`

主要 ORM 功能：

- 查询作者、机构、出版社、来源、关键词、标签列表
- 删除单个词典项
- 调用重复合并/回滚流程
- 返回自动补全 JSON

SQL 类型：

- `SELECT ... ORDER BY name`
- `DELETE FROM authors/affiliations/publishers/sources/keywords/tags WHERE id = ?`

## 5.9 `app/blueprints/settings.py`

主要 ORM 功能：

- 读取或创建 `UserSetting`
- 更新 MinerU 地址
- 更新密码
- 更新 AI Agent 设置

SQL 类型：

- `SELECT ... FROM user_settings WHERE user_id = ?`
- `INSERT INTO user_settings ...`
- `UPDATE user_settings SET mineru_url = ? WHERE user_id = ?`
- `UPDATE users SET password_hash = ? WHERE id = ?`
- `UPDATE ai_agent_settings SET ... WHERE user_id = ?`

## 5.10 `app/blueprints/ai_agent.py`

主要 ORM 功能：

- 读取 AI Agent 状态
- 更新 AI Agent 状态
- 插入活动记录

SQL 类型：

- `SELECT ... FROM ai_agent_settings WHERE user_id = ?`
- `UPDATE ai_agent_settings SET ... WHERE user_id = ?`
- `INSERT INTO ai_agent_activities ...`

## 5.11 `app/services/upsert.py`

这是“字典表复用与去重”的核心 ORM 文件。

主要 ORM 功能：

- 查作者是否存在
- 按主键读 `AuthorCode`
- 锁住 `AuthorCode` 记录并分配编号
- 插入作者
- 插入作者编号计数器
- 查/建机构
- 查/建关键词
- 查/建标签
- 查/建出版社
- 查/建来源

它体现的 SQL 类型：

- `SELECT ... LIMIT 1`
- `SELECT ... FOR UPDATE`
- `INSERT INTO authors ...`
- `INSERT INTO author_codes ...`
- `INSERT INTO affiliations/keywords/tags/publishers/sources ...`
- 冲突时回滚再重试

## 5.12 `app/services/dict_cleanup.py`

这是 ORM 最复杂的服务文件之一。

主要 ORM 功能：

- 查找孤立作者/机构/出版社/来源/关键词/标签
- 批量删除孤立记录
- 构建重复项分组
- 统计合并影响范围
- 执行合并
- 记录合并审计
- 从审计中恢复删除记录
- 回滚关系变化

涉及 SQL 类型：

- `NOT EXISTS`
- `JOIN`
- `COUNT(DISTINCT ...)`
- `DELETE`
- `UPDATE`
- `INSERT`
- `SELECT ... LIMIT ... ORDER BY ...`
- `MERGE` 语义对应的 select+insert/update 组合

如果只看 ORM 复杂度，这个文件和 `documents.py` 是全项目最重要的两个数据库文件。

## 5.13 `app/services/ai_agent.py`

主要 ORM 功能：

- 读取或创建 AI 设置
- 插入活动记录
- 按时间范围查询活动记录
- 按日期保存或更新日报/周报
- 查询某月日报
- 查询某月周报
- 删除截止时间前的活动

SQL 类型：

- `SELECT ... WHERE user_id = ?`
- `INSERT INTO ai_agent_settings ...`
- `INSERT INTO ai_agent_activities ...`
- `SELECT ... WHERE created_at >= ? ORDER BY ... LIMIT ?`
- `SELECT ... WHERE start_date >= ? AND start_date < ? ORDER BY ...`
- `UPDATE ai_agent_journals SET ... WHERE id = ?`
- `DELETE FROM ai_agent_activities WHERE created_at < ?`

## 5.14 `app/services/file_io.py`

主要 ORM 功能：

- 附件文件保存到磁盘后，插入 `File` 元数据

SQL 类型：

- `INSERT INTO files (document_id, file_path, original_name, file_size, mime_type, uploaded_at) VALUES (...)`

## 5.15 `app/services/schema_bootstrap.py`

这个文件是数据库相关，但边界要讲清楚：

- 它不是 ORM 生成 SQL 的主战场
- 它主要使用原生 SQL 做旧库修复

例如：

- `ALTER TABLE users ADD COLUMN ...`
- `UPDATE users SET ...`
- `ALTER TABLE documents ADD COLUMN ...`

因此这部分更适合归类为“原生 SQL 兼容修复”，不是典型 ORM 查询。

## 6. ORM 自动生成的关联 SQL：最容易被忽略但很重要

这一部分最容易在报告里漏掉，但其实非常关键。

### 6.1 删除文献时的关联影响

`Document` 模型上有这些关系：

- `author_links`
- `keywords`
- `tags`
- `files`

当代码执行：

```python
db.session.delete(doc)
```

时，ORM 可能会联动生成多类 SQL：

- 删除 `documents`
- 删除 `document_authors`
- 删除 `document_keywords`
- 删除 `document_tags`
- 删除 `files`

其中有的由代码显式处理，有的由关系 `cascade="all, delete-orphan"` 自动触发。

### 6.2 编辑文献时重建关联

例如：

```python
document.keywords.clear()
document.keywords.append(...)
```

它底层对应的是：

1. 先删掉旧关联
2. 再插入新关联

这是一类非常典型的 ORM 自动生成 SQL 行为。

### 6.3 给作者添加机构

代码：

```python
author.affiliations.append(affiliation)
```

底层会生成：

```sql
INSERT INTO author_affiliations (author_id, affiliation_id)
VALUES (:author_id, :affiliation_id);
```

## 7. ORM 没有覆盖、而是手写 SQL 的边界

为了不混淆，必须把边界写清楚。

本项目中不是所有数据库操作都靠 ORM 生成，以下属于原生 SQL：

- `app/__init__.py`
  - `SELECT 1`
- `app/services/schema_bootstrap.py`
  - `ALTER TABLE ... ADD COLUMN ...`
  - `UPDATE users SET ...`
- 测试文件里也有少量原生 SQL 用于建表/探测结构

所以更准确的说法是：

> 本项目绝大多数业务 SQL 都由 ORM 生成；少量底层维护、健康检查和旧库修复使用手写 SQL。

## 8. 如果想亲眼看到 ORM 生成的 SQL，可以怎么做

虽然本项目目前没有默认打开 SQL 回显，但如果要观察真实生成 SQL，可以临时开启 SQLAlchemy 的 echo。

常见方式是给应用增加：

```python
SQLALCHEMY_ECHO = True
```

或者给引擎配置加上：

```python
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_pre_ping": True,
    "echo": True,
}
```

这样运行后，控制台就会打印 ORM 最终送到数据库的 SQL。

注意：

- 这更适合本地调试
- 不建议在生产环境长期打开

## 9. 本项目 ORM 能力清单

为了便于汇报，最后把 ORM 已实际使用的能力压缩成一张清单。

### 9.1 表与结构层

- 模型映射表
- 主键
- 复合主键
- 外键
- 唯一约束
- 非空约束
- 默认值
- 枚举字段
- 索引
- 关系定义
- 级联删除

### 9.2 查询层

- 主键查询
- 条件查询
- 多条件查询
- 模糊查询
- 排序
- 分页
- `IN` 查询
- `OR` 查询
- `JOIN`
- `EXISTS`
- 聚合
- 分组
- 去重统计
- 限量查询

### 9.3 写入层

- 插入单条记录
- 插入关联记录
- 插入多对多关系
- 更新已加载对象
- 批量更新
- 删除单条对象
- 批量删除
- 关系清空与重建
- merge 恢复对象

### 9.4 事务与并发层

- `commit()`
- `rollback()`
- `flush()`
- `with_for_update()` 行锁

### 9.5 模式维护层

- `create_all()`
- `drop_all()`
- Alembic 基线迁移

## 10. 最后总结

如果只用一句话概括本项目中“ORM 让 SQL 长什么样”：

> 在这个项目里，ORM 并不是简单把 `SELECT` 写短一点，而是完整负责了表映射、主外键关系、单表查询、多表连接、模糊搜索、聚合统计、分页、插入、更新、删除、事务控制、并发锁和部分模式创建；最终生成出来的 SQL 主要是 `SELECT / INSERT / UPDATE / DELETE / EXISTS / JOIN / GROUP BY / COUNT / LIMIT / FOR UPDATE / CREATE TABLE` 这一整套关系数据库语句。

如果要用于课堂展示，可以把重点放在下面五点：

1. 模型类就是表结构，字段定义会变成列、约束和索引。
2. `filter_by / filter / first / all / order_by / paginate` 这类 ORM 写法，本质上都在生成 `SELECT`。
3. `add / delete / commit / rollback / flush` 对应 `INSERT / DELETE / UPDATE / 事务控制`。
4. `join / any / has / group_by / count(distinct(...))` 让 ORM 可以生成复杂查询，而不只是简单查一张表。
5. `with_for_update()`、关系级联、Alembic 迁移，说明项目已经把 ORM 用到了工程化层面，而不是停留在入门 CRUD。
