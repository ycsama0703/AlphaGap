.PHONY: help install daily weekly dry-run test clean init-db lint

help:
	@echo "AlphaGap — Make targets"
	@echo ""
	@echo "  make install      安装依赖"
	@echo "  make init-db      初始化 SQLite schema"
	@echo "  make daily        跑每日 pipeline（生产）"
	@echo "  make dry-run      跑每日 pipeline 但不发邮件、不写 inbox"
	@echo "  make weekly       生成本周报告"
	@echo "  make test         单元测试"
	@echo "  make lint         代码检查"
	@echo "  make clean        清理临时文件"

install:
	pip install -r requirements.txt

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
