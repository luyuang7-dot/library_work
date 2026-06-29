# Personal Library

这是一个用于本地运行的 Flask 文献管理项目精简仓库。

## 保留内容

- `app/`: Flask 应用、模板、静态资源与业务逻辑
- `migrations/`: Alembic 数据库迁移
- `run.py`: 本地开发启动入口
- `config.py`: 运行配置
- `requirements.txt`: 本地运行依赖
- `alembic.ini`: Alembic 配置
- `VERSION`: 应用版本号
- `.env.example`: 本地环境变量示例

## 本地启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
flask --app run:app init-db
python run.py
```

## 关键环境变量

```env
FLASK_ENV=dev
FLASK_SECRET_KEY=replace-with-local-secret
AI_AGENT_API_KEY_ENCRYPTION_KEY=replace-with-local-ai-key
DATABASE_URL=mysql+pymysql://root:@localhost:3306/library_work?charset=utf8mb4
UPLOAD_FOLDER=uploads
DEFAULT_MINERU_URL=http://127.0.0.1:8000
AUTO_START_MINERU=false
```
