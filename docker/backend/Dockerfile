FROM python:3.12-slim-bookworm

# 使用 LABEL 替代 MAINTAINER
LABEL maintainer="948080782@qq.com"

# 设置时区
ENV TZ=Asia/Shanghai PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# 设置容器内工作目录
WORKDIR /home

# 将当前主机目录全部文件复制至容器工作目录
COPY ./backend/requirements.txt .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 镜像包含本次二开代码；运行时仅挂载配置和需要持久化的数据。
COPY ./backend/ .
COPY LICENSE /home/LICENSE

# 暴露端口
EXPOSE 8001

# 运行应用
CMD ["python", "main.py", "run", "--env=prod"]
