# sheetgate

从本地门户批量下载表格。下载令牌很短，一批还没拉完就会过期，需要续期并接着跑。隐藏表不要进结果，合并后的标题行也不是字段名。

```
python -m sheetgate site --port 8769 --files fixtures/files
python -m sheetgate harvest --base http://127.0.0.1:8769 --out <out> --checkpoint <ckpt>
python -m sheetgate verify --out <out> --expect fixtures/expected/tables.json
```
