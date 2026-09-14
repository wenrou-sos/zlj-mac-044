#!/usr/bin/env bash
# 一键启动：安装依赖 -> 迁移 -> 写入样例数据 -> 启动服务
set -e
cd "$(dirname "$0")"

python3 -m pip install -r requirements.txt --break-system-packages 2>/dev/null \
  || python3 -m pip install -r requirements.txt

python3 manage.py migrate
python3 manage.py seed

echo ""
echo "=============================================="
echo " 印刷厂生产管理系统已启动"
echo " 访问地址: http://127.0.0.1:8000"
echo " 后台管理: http://127.0.0.1:8000/admin/"
echo "=============================================="
python3 manage.py runserver 0.0.0.0:8000
