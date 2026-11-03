# Compressed files

Files over 50 MB are committed gzip-compressed (#163). Unpack them with:

```bash
find eval/runs/2026-11-01-s3h-twowiki_s3h_graph_haiku -name '*.gz' -exec gunzip -k {} \;
```

Each unpacked file matches the SHA-256 below (checked before the commit).

| File | Bytes | SHA-256 of the uncompressed file |
|---|---|---|
| `journal.jsonl` | 54223023 | `9a5670d97bac6d607132d30f10b8e689896d1073a084a2c83f0f920a152fc9d9` |
