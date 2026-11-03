# Compressed files

Files over 50 MB are committed gzip-compressed (#163). Unpack them with:

```bash
find eval/runs/2026-11-01-s3h-twowiki_s3h_graph_deepseek -name '*.gz' -exec gunzip -k {} \;
```

Each unpacked file matches the SHA-256 below (checked before the commit).

| File | Bytes | SHA-256 of the uncompressed file |
|---|---|---|
| `journal.jsonl` | 67913238 | `87182398c62d112f25047043d1c9219434f4faf41ea01f4acbb7150c0aaa9232` |
