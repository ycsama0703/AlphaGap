.PHONY: help install daily weekly dry-run test clean init-db lint bootstrap seed

help:
	@echo "AlphaGap — Make targets"
	@echo ""
	@echo "  make install      安装依赖"
	@echo "  make bootstrap    无库时从 db/seed 解压启动语料（新部署/clone 首次用）"
	@echo "  make seed         把当前活库重新压成 db/seed 种子（偶尔刷新快照）"
	@echo "  make init-db      初始化 SQLite schema"
	@echo "  make daily        跑每日 pipeline（生产）"
	@echo "  make dry-run      跑每日 pipeline 但不发邮件、不写 inbox"
	@echo "  make weekly       生成本周报告"
	@echo "  make test         单元测试"
	@echo "  make lint         代码检查"
	@echo "  make clean        清理临时文件"

install:
	pip install -r requirements.txt

bootstrap:
	python -c "from pathlib import Path; from pipeline.config import load_settings; from pipeline.db import _bootstrap_from_seed; p=load_settings().db_path; _bootstrap_from_seed(p); print('DB ready at', p)"

seed:
	@test -f db/alphagap.sqlite || (echo "no live DB to snapshot" && exit 1)
	gzip -c db/alphagap.sqlite > db/seed/alphagap-seed.sqlite.gz
	@echo "refreshed db/seed/alphagap-seed.sqlite.gz ($$(du -h db/seed/alphagap-seed.sqlite.gz | cut -f1))"

init-db:
	python -m pipeline.db init

daily:
	python -m pipeline.main daily

dry-run:
	DRY_RUN=true python -m pipeline.main daily

weekly:
	python -m pipeline.main weekly

test:
	pytest tests/ -v

lint:
	python -m py_compile pipeline/*.py pipeline/**/*.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
