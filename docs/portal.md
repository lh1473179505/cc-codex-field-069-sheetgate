# 门户与表格

`GET /files` 列出可下载的工作簿（需要登录 cookie）。`POST /login` 提交 `{"username":"sheet-bot","password":"sheet-fixture-only"}`，成功后设置 cookie `sg_sid`，并在 JSON 里给出 `download_token`。

`GET /download/{filename}?token=...` 下载 xlsx。每个 token 只能成功下载 **2** 个文件，第 3 次返回 401，`{"error":"token_expired"}`。要用当前 cookie 调 `POST /token/refresh`（空 body）拿新 token，再继续。不要重新登录来绕过续期。不要丢已经写到 sink 的表。

夹具里有三份文件：`sales-q1.xlsx`、`inventory.xlsx`、`returns.xlsx`，所以一轮 token 必然会在中途过期。

## 工作簿结构

- 每个可见工作表的第 1 行是合并单元格的标题（例如 “Q1 Snapshot”），**不是**字段名。
- 第 2 行才是列名。
- `sales-q1.xlsx` 还有一张隐藏表 `Scratch`，里面有一条 west/FAKE 的诱饵行，不能出现在输出里。只处理可见表。

不要依赖本机是否安装了 openpyxl；可以用标准库 zipfile 和 xml 解析 xlsx（Office Open XML）。

## 输出

`--out/sales.jsonl`、`inventory.jsonl`、`returns.jsonl`，字段与第 2 行列名一致，数值保持整数。checkpoint 记录已经完整写入的文件名。中断后用同一 checkpoint 续跑，已完成的文件不要再下载。
