# Review correction: UTF-8 output clipping

Independent review identified malformed UTF-8 replacement expansion: 30,000
invalid bytes become 90,000 encoded replacement-character bytes. Retention was
bounded to 65,536 bytes but the truncation flag incorrectly remained false.

Red: `python -m pytest -q loop/tests/test_reliability.py -k malformed_utf8`
failed both new stdout/stderr cases at the truncation flag (2 failed, 37
deselected). Exit code and retained-byte budget already passed.

Green after reporting decoded clipping as well as raw clipping:
`python -m pytest -q loop/tests/test_reliability.py -k 'malformed_utf8 or output_retention'`
passed 3 tests, 36 deselected. The empty opposite stream remains untruncated.
The final task run supplies the authoritative complete-suite result.
