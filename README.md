# document2word：PDF 识别与 Word 转换系统

将 PDF 文档解析并转换为可编辑的 Word 文档，支持原生 PDF、扫描 PDF 与混合类型页面的统一处理。

项目地址：https://github.com/godhelpgrace/document2word

## 功能概览

- 原生 PDF 提取与排版保真
- 扫描 PDF OCR 识别与结构化
- 混合页面自适应处理管道
- CLI 本地转换与 API 异步任务模式

## 快速开始

### 环境要求
- Python 3.10+
- Redis (用于任务队列，API 模式需要)

### 安装依赖

```bash
pip install -r requirements.txt
```

### 本地测试（CLI 模式，无需 Redis）

```bash
python main.py "your_file.pdf" output.docx
```

### API 模式

1. 启动 Redis:
```bash
redis-server
```

2. 启动 Celery Worker:
```bash
celery -A workers.celery_app worker --loglevel=info
```

3. 启动 API:
```bash
uvicorn api.main:app --reload --port 8000
```

4. 使用 API:
```bash
# 上传并转换
curl -X POST http://localhost:8000/api/v1/convert -F "file=@your_file.pdf"

# 查询状态
curl http://localhost:8000/api/v1/tasks/{task_id}

# 下载结果
curl -O http://localhost:8000/api/v1/tasks/{task_id}/download
```

### Web 服务（内置 UI）

```bash
uvicorn api.main:app --reload --port 8000
```

访问 http://localhost:8000 查看 Web 界面。

### Docker 部署

```bash
cd docker
docker-compose up -d
```

## 项目结构

```
├── api/          # FastAPI 接口
├── pipeline/     # 处理管道
│   ├── classifier/   # 页面类型识别
│   ├── native/       # 原生 PDF 处理
│   ├── scanned/      # 扫描 PDF 处理
│   └── hybrid/       # 混合 PDF 处理
├── model/        # 数据模型
├── render/       # DOCX 渲染
├── workers/      # Celery 任务
├── storage/      # 文件与任务存储
├── docker/       # Docker 配置
└── main.py       # CLI 入口
```
