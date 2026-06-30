# 个人文献管理系统

本项目是一个基于 Flask 的个人文献管理系统，面向课程期末验收场景，支持用户注册与审批、文献录入与检索、分类管理、BibTeX 导入导出、PDF 识别入库，以及字典清洗与 AI 日志辅助功能。本文档重点说明系统安装、使用、自动化测试与部署验证步骤。

## 1. 系统概述

### 1.1 项目目标

系统用于管理学术文献与附属 PDF 文件，解决手工整理文献效率低、元数据不统一、后续检索困难等问题。项目将文献元数据管理、分类组织、BibTeX 互通和 MinerU PDF 识别整合到同一 Web 系统中。

### 1.2 主要功能

- 用户注册、登录、管理员审批
- 文献新增、编辑、删除、附件上传与下载
- 树形分类管理与批量分类调整
- 按标题、作者、来源、年份、标签、阅读状态等条件检索
- BibTeX 导入与导出
- 基于 MinerU 的单篇 PDF 识别
- 基于 MinerU 的批量 PDF 识别与导入
- 作者、关键词、标签、来源、出版社等字典维护
- 孤立字典清理、重复项合并与回滚
- AI 活动记录与日报、周报展示

### 1.3 技术栈

- 后端框架：Flask 3
- 数据库：MySQL 8（默认），SQLAlchemy 2
- 数据迁移：Alembic
- 前端：Jinja2 + Bootstrap
- 自动化测试：pytest
- PDF 解析：MinerU 本地 API 服务

## 2. 运行环境要求

建议使用以下环境完成课程验收：

- Python 3.10 及以上
- MySQL 8.0
- Windows 10/11 或 Linux
- 可联网环境（首次安装依赖与 MinerU 时需要）

本仓库默认使用 MySQL 连接串：

```env
mysql+pymysql://root:数据库密码@localhost:3306/library_work?charset=utf8mb4
```

## 3. 目录结构

```text
app/                Flask 应用、蓝图、模板、静态资源、业务逻辑
migrations/         Alembic 数据库迁移脚本
tests/              pytest 自动化测试
docs/               项目补充文档
uploads/            上传的 PDF 附件
instance/           Flask 实例目录
run.py              本地开发启动入口
config.py           配置文件
requirements.txt    Python 依赖列表
.env.example        环境变量示例
```

## 4. 系统安装与部署

### 4.1 获取项目代码

```powershell
git clone <your-repo-url>
cd 云端服务器版本
```

### 4.2 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4.3 创建数据库

在 MySQL 中执行：

```sql
CREATE DATABASE library_work
DEFAULT CHARACTER SET utf8mb4
DEFAULT COLLATE utf8mb4_unicode_ci;
```

### 4.4 配置环境变量

复制示例文件：

```powershell
Copy-Item .env.example .env
```

建议至少修改以下字段：

```env
FLASK_ENV=dev
FLASK_SECRET_KEY=replace-with-a-long-random-secret
AI_AGENT_API_KEY_ENCRYPTION_KEY=replace-with-32-byte-random-key
DATABASE_URL=mysql+pymysql://root:你的数据库密码@localhost:3306/library_work?charset=utf8mb4
UPLOAD_FOLDER=uploads
MAX_CONTENT_LENGTH=209715200
DEFAULT_MINERU_URL=http://127.0.0.1:8000
AUTO_START_MINERU=false
```

说明：

- `FLASK_ENV=dev` 表示本地验收环境，使用 `python run.py` 启动
- `AUTO_START_MINERU=false` 表示由用户手工启动 MinerU，最稳定，便于排错
- 如果已经把 `mineru-api` 安装到系统环境变量中，也可以设置 `AUTO_START_MINERU=true`，此时 `run.py` 会尝试自动拉起本地 MinerU 服务

### 4.5 初始化数据库

```powershell
flask --app run:app init-db
```

如果数据库是第一次使用，建议再创建一个管理员账号：

```powershell
flask --app run:app create-admin --username admin --password admin123 --email admin@example.com
```

### 4.6 启动系统

```powershell
python run.py
```

默认访问地址：

- 系统首页：`http://127.0.0.1:5000/`
- 健康检查：`http://127.0.0.1:5000/healthz`

### 4.7 生产部署说明（可选）

`run.py` 仅用于本地开发与课程验收。若部署到 Linux 服务器，应使用生产模式并由 Gunicorn/Nginx 托管。项目中已包含 `gunicorn` 依赖，推荐流程如下：

1. 将 `FLASK_ENV` 设为 `prod`
2. 先执行数据库迁移
3. 使用 Gunicorn 托管 `app:create_app("prod")`
4. 由 Nginx 进行反向代理

如果本次仅为期末汇报验收，使用第 4.6 节的本地启动方式即可。

## 5. 系统使用说明

### 5.1 首次登录与审批

1. 访问 `http://127.0.0.1:5000/`
2. 若未创建管理员，可先通过命令行执行 `create-admin`
3. 普通用户注册后需要管理员在后台审批
4. 审批通过后，用户方可正常登录系统

### 5.2 文献管理

系统支持以下文献操作：

- 手动新增文献
- 编辑文献元数据
- 上传 PDF 附件
- 下载或删除附件
- 删除单篇文献
- 批量删除文献
- 批量调整文献分类

### 5.3 分类管理

在“分类管理”中可以：

- 新建一级或二级分类
- 修改分类名称
- 删除分类

删除分类后，该分类下文献会被解除分类绑定，不会被直接删除。

### 5.4 检索与筛选

系统支持按以下条件组合检索：

- 标题
- 作者
- 来源
- 分类
- 文献类型
- 年份区间
- 阅读状态
- 标签
- 最低评分

### 5.5 BibTeX 导入导出

- 导入：进入 BibTeX 页面后，可粘贴 `.bib` 文本或上传 `.bib` 文件
- 导出：支持导出全部文献，或导出单篇文献 BibTeX

### 5.6 PDF 识别与导入

系统集成了 MinerU 本地服务，支持两种方式：

- 单篇识别：在文献录入页面上传 PDF，自动提取标题、作者、摘要、关键词、DOI 等信息
- 批量识别：在批量导入页面上传 PDF，识别后直接入库

如果识别失败，优先检查：

- MinerU 是否已启动
- `DEFAULT_MINERU_URL` 或用户设置中的 `mineru_url` 是否正确
- 访问 `http://127.0.0.1:8000/health` 是否返回正常 JSON

### 5.7 字典维护与清洗

系统可对作者、关键词、标签、来源、出版社、机构等字典项进行维护，并支持：

- 扫描孤立字典项
- 删除无引用字典项
- 合并重复字典项
- 查看合并审计记录
- 回滚最近一次或指定一次合并操作

### 5.8 AI 日志功能

系统保留了 AI 日志与活动汇总模块，可记录用户行为并显示日报、周报。若未配置外部 AI 接口，该功能不影响文献管理主流程。

## 6. 自动化测试与验收说明

本项目现已提供完整的 `pytest` 自动化测试脚本，测试结构参考原版云端项目的 `tests/` 目录组织方式，并按当前仓库的实际功能重新裁剪与补齐。

### 6.1 测试依赖

`pytest` 已加入 [requirements.txt]，安装依赖后即可直接运行测试。

### 6.2 运行方式

执行全部测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

执行单个测试文件：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_routes.py -q
```

查看更详细输出：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```

### 6.3 当前测试结果

在当前仓库环境下，自动化测试已通过：

```text
63 passed
```

### 6.4 覆盖范围

当前测试覆盖以下核心模块：

- 应用启动与配置校验
- 用户注册、登录、管理员审批、角色授权
- 文献新增、编辑、删除、搜索、批量分类
- BibTeX 解析、导入、导出
- 批量 PDF 导入与 MinerU 接口联调逻辑
- 模型关系与 `upsert` 逻辑
- AI 日志设置、状态接口、日报周报逻辑
- 字典清理、标签合并、回滚能力
- `run.py` 开发模式保护逻辑

### 6.5 测试文件说明

`tests/` 目录中的主要测试文件如下：

- [tests/conftest.py](/D:/GitHub项目/数据库项目/云端服务器版本/tests/conftest.py)：统一测试夹具
- [tests/test_app_init.py](/D:/GitHub项目/数据库项目/云端服务器版本/tests/test_app_init.py)：应用启动与配置检查
- [tests/test_admin.py](/D:/GitHub项目/数据库项目/云端服务器版本/tests/test_admin.py)：管理员审批与权限控制
- [tests/test_routes.py](/D:/GitHub项目/数据库项目/云端服务器版本/tests/test_routes.py)：主要页面路由与文献主流程
- [tests/test_bibtex_io.py](/D:/GitHub项目/数据库项目/云端服务器版本/tests/test_bibtex_io.py)：BibTeX 服务层
- [tests/test_batch_bibtex.py](/D:/GitHub项目/数据库项目/云端服务器版本/tests/test_batch_bibtex.py)：批量 PDF / BibTeX 流程
- [tests/test_models.py](/D:/GitHub项目/数据库项目/云端服务器版本/tests/test_models.py)：模型关系与 `upsert`
- [tests/test_ai_agent.py](/D:/GitHub项目/数据库项目/云端服务器版本/tests/test_ai_agent.py)：AI 日志与聚合逻辑
- [tests/test_dict_cleanup.py](/D:/GitHub项目/数据库项目/云端服务器版本/tests/test_dict_cleanup.py)：字典合并、回滚、清理
- [tests/test_settings_mineru.py](/D:/GitHub项目/数据库项目/云端服务器版本/tests/test_settings_mineru.py)：设置页与 MinerU 健康检查
- [tests/test_run_py.py](/D:/GitHub项目/数据库项目/云端服务器版本/tests/test_run_py.py)：开发模式启动限制

## 7. MinerU 本地部署说明

本项目通过 `app/services/mineru_client.py` 对接 MinerU 的 `/health` 与 `/file_parse` 接口，因此本地部署完成后，只要 `http://127.0.0.1:8000/health` 可访问，系统就能完成识别功能联调。

### 7.1 官方信息说明

根据 2026 年 6 月 30 日查阅的 MinerU 官方仓库与文档：

- 官方仓库：[MinerU GitHub](https://github.com/opendatalab/MinerU)
- 官方文档首页：[MinerU Docs](https://opendatalab.github.io/MinerU/)
- 官方 README 说明支持 `pip` 或 `uv` 安装
- 官方 3.x 版本保留同步 `POST /file_parse` 接口，兼容本项目现有调用方式

### 7.2 推荐本地部署方式

建议单独创建 MinerU 虚拟环境。若当前机器是 Windows，请优先使用 Python 3.10 至 3.12 创建该环境；根据 2026 年 6 月 30 日查阅的官方 README，Windows 下 Python 3.13 仍存在依赖兼容限制。

```powershell
py -3.12 -m venv .venv-mineru
.\.venv-mineru\Scripts\Activate.ps1
pip install --upgrade pip
pip install uv
uv pip install -U "mineru[all]"
```

安装完成后启动本地 API：

```powershell
mineru-api --host 127.0.0.1 --port 8000
```

启动后访问：

```text
http://127.0.0.1:8000/health
```

若返回健康状态 JSON，则说明部署成功。

### 7.3 与本项目的对接方式

方式一：手工启动 MinerU

```env
DEFAULT_MINERU_URL=http://127.0.0.1:8000
AUTO_START_MINERU=false
```

方式二：让本项目启动时自动拉起 MinerU

```env
DEFAULT_MINERU_URL=http://127.0.0.1:8000
AUTO_START_MINERU=true
MINERU_HOST=127.0.0.1
MINERU_PORT=8000
MINERU_CMD=mineru-api
```

说明：

- `AUTO_START_MINERU=true` 时，`python run.py` 会尝试执行 `mineru-api --host 127.0.0.1 --port 8000`
- 因此必须保证 `mineru-api` 命令已经安装并可在命令行直接调用

### 7.4 常见问题排查

1. `Cannot reach MinerU`

原因：MinerU 未启动，或端口、地址配置错误。

处理：手工访问 `http://127.0.0.1:8000/health` 检查服务状态。

2. `Port 8000 is already in use`

原因：8000 端口被其他程序占用。

处理：更换 `MINERU_PORT`，并同步修改 `DEFAULT_MINERU_URL`。

3. 系统能启动，但 PDF 无法识别

原因：MinerU 未正常返回 `/file_parse` 结果，或 PDF 本身为空或损坏。

处理：先用设置页里的 MinerU 测试接口确认健康，再更换 PDF 重试。

## 8. 项目说明补充

### 8.1 建议执行的基础自检命令

以下命令适合在部署完成后做基础自检：

```powershell
.\.venv\Scripts\python.exe -m compileall app run.py config.py
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -c "from app import create_app; app=create_app('test'); print(app.url_map)"
```

### 8.2 补充材料

- 数据实体说明：[docs/database-entities.md](/D:/GitHub项目/数据库项目/云端服务器版本/docs/database-entities.md)
- 数据库图：[chen_er_diagram.png](/D:/GitHub项目/数据库项目/云端服务器版本/chen_er_diagram.png)
