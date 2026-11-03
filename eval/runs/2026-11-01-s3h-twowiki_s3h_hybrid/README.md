# Compressed files

Files over 50 MB are committed gzip-compressed (#163). Unpack them with:

```bash
find eval/runs/2026-11-01-s3h-twowiki_s3h_hybrid -name '*.gz' -exec gunzip -k {} \;
```

Each unpacked file matches the SHA-256 below (checked before the commit).

| File | Bytes | SHA-256 of the uncompressed file |
|---|---|---|
| `context_export.jsonl` | 59152084 | `b6f5d1fa3b91728676fcd8fd26144520c0c3cee3006c7b42b34300a9ad870166` |
| `journal.jsonl` | 81359789 | `26046af0808ffc20fbbc4ba561facd548dddf87d122728dbb4216ab1f0eea491` |
