from __future__ import annotations

import json
import io
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote
from urllib import request as urlrequest
from urllib.error import HTTPError
from xml.etree import ElementTree as ET

OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class PortalClient:
    def __init__(self, base, account):
        self.base = base.rstrip("/")
        self.account = account
        self.cookie = None
        self.token = None

    def _request(self, method, path, body=None, with_token=False):
        url = self.base + path
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.cookie:
            headers["Cookie"] = self.cookie
        req = urlrequest.Request(url, data=data, headers=headers, method=method)
        try:
            resp = urlrequest.urlopen(req)
            raw = resp.read()
        except HTTPError as exc:
            payload = {}
            try:
                payload = json.loads(exc.read().decode())
            except (ValueError, UnicodeDecodeError):
                pass
            return exc.code, payload, exc
        set_cookie = resp.headers.get("Set-Cookie")
        if set_cookie:
            self.cookie = set_cookie.split(";", 1)[0]
        if with_token:
            self.token = json.loads(raw.decode())["download_token"]
        return resp.status, raw, resp.headers

    def login(self):
        status, _, _ = self._request("POST", "/login", body=self.account, with_token=True)
        if status != 200:
            raise RuntimeError(f"login failed with status {status}")

    def refresh(self):
        status, payload, _ = self._request("POST", "/token/refresh", body={})
        if status != 200:
            raise RuntimeError(f"token refresh failed with status {status}: {payload}")
        self.token = json.loads(payload.decode())["download_token"]

    def list_files(self):
        status, payload, _ = self._request("GET", "/files")
        if status != 200:
            raise RuntimeError(f"list files failed with status {status}")
        return json.loads(payload.decode())["files"]

    def download(self, filename):
        path = f"/download/{quote(filename)}?token={self.token}"
        status, payload, _ = self._request("GET", path)
        if status == 401 and isinstance(payload, dict) and payload.get("error") == "token_expired":
            self.refresh()
            path = f"/download/{quote(filename)}?token={self.token}"
            status, payload, _ = self._request("GET", path)
        if status != 200:
            raise RuntimeError(f"download {filename} failed with status {status}: {payload}")
        return payload


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _column_index(cell_ref):
    letters = re.match(r"[A-Z]+", cell_ref).group(0)
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _load_shared_strings(archive):
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings = []
    for si in root:
        if _local(si.tag) != "si":
            continue
        strings.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))
    return strings


def _cell_value(cell, shared_strings):
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(t.text or "" for t in cell.iter() if _local(t.tag) == "t")
    value_node = next((n for n in cell if _local(n.tag) == "v"), None)
    if value_node is None:
        return None
    raw = value_node.text
    if cell_type == "s":
        return shared_strings[int(raw)]
    if cell_type == "b":
        return raw == "1"
    if cell_type in ("n", None):
        number = float(raw)
        return int(number) if number.is_integer() else number
    return raw


def _resolve_sheet_path(target, rels):
    for rel in rels:
        if rel.get("Id") == target:
            target_path = rel.get("Target")
            break
    else:
        raise KeyError(f"missing relationship {target}")
    if target_path.startswith("/"):
        return target_path.lstrip("/")
    return "xl/" + target_path.lstrip("/")


def parse_workbook(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        shared_strings = _load_shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rows_out = []
        for sheet in next(el for el in workbook if _local(el.tag) == "sheets"):
            if _local(sheet.tag) != "sheet" or sheet.get("state", "visible") != "visible":
                continue
            rel_id = sheet.get(f"{{{OFFICE_REL_NS}}}id")
            sheet_path = _resolve_sheet_path(rel_id, rels)
            sheet_root = ET.fromstring(archive.read(sheet_path))
            sheet_data = next(
                (el for el in sheet_root if _local(el.tag) == "sheetData"), None
            )
            if sheet_data is None:
                continue
            header = None
            for row in sheet_data:
                if _local(row.tag) != "row":
                    continue
                if int(row.get("r", "1")) == 1:
                    continue
                values = {}
                for cell in row:
                    if _local(cell.tag) != "c":
                        continue
                    values[_column_index(cell.get("r"))] = _cell_value(cell, shared_strings)
                if header is None:
                    header = values
                    continue
                record = {}
                for index, name in header.items():
                    if name is None or str(name) == "":
                        continue
                    record[str(name)] = values.get(index)
                if any(value is not None for value in record.values()):
                    rows_out.append(record)
        return rows_out


def _load_checkpoint(path):
    if not path.is_file():
        return {"completed": []}
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return {"completed": data}
    data.setdefault("completed", [])
    return data


def _save_checkpoint(path, checkpoint):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _output_name(filename):
    stem = filename[:-5] if filename.lower().endswith(".xlsx") else filename
    match = re.match(r"[a-z]+", stem)
    return (match.group(0) if match else stem) + ".jsonl"


def _write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def run_harvest(args):
    out_dir = Path(args.out)
    checkpoint_path = Path(args.checkpoint)
    account = json.loads(Path(args.account).read_text())
    checkpoint = _load_checkpoint(checkpoint_path)
    completed = set(checkpoint["completed"])

    client = PortalClient(args.base, account)
    client.login()
    pending = [name for name in client.list_files() if name not in completed]

    for filename in pending:
        data = client.download(filename)
        rows = parse_workbook(data)
        _write_rows(out_dir / _output_name(filename), rows)
        completed.add(filename)
        checkpoint["completed"] = sorted(completed)
        _save_checkpoint(checkpoint_path, checkpoint)

    print(f"harvest done: {len(completed)} file(s) complete")
    return 0
