# Compressed run files (#149)

Every file of this run directory over 10 MB is committed gzipped (`*.gz`), since the uncompressed journal is over
GitHub's 100 MB file limit. The bytes inside are exactly what the run wrote. Unpack them in place before reading the
run with `lancet-eval` or `python -m lancet_eval.explore_readout`:

```bash
find <this directory> -name '*.gz' -exec gunzip -k {} \;
```
