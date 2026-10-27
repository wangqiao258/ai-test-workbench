# AI 协同测试工作台 平台镜像（P0）
# root 运行是 2026-10-23 用户明确的取舍（内网单机工具，见 docs/部署与执行引擎设计.md §3-3/§10）
FROM python:3.13-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py db.py openapi_gen.py ./
COPY api/ api/
COPY core/ core/
COPY templates/ templates/
COPY static/ static/
COPY tests/ tests/
# 运维脚本（存量回填）：容器内可直接 python scripts/xxx.py --apply
COPY scripts/ scripts/
# AI 手册：/api/guide 读它，是规则的唯一真相源（.dockerignore 里单独放行）
COPY docs/ai_guide.md docs/ai_guide_reference.md docs/

ENV APP_HOST=0.0.0.0 APP_PORT=8501
EXPOSE 8501
CMD ["python", "app.py"]
